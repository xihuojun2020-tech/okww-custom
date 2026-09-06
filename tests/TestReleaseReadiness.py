import re
import runpy
import tempfile
import unittest
import zipfile
from pathlib import Path


class TestReleaseReadiness(unittest.TestCase):
    def test_version_and_release_notes_are_synchronized(self):
        version = re.search(r'version\s*=\s*"([0-9]+\.[0-9]{2}\.[0-9]{2})"',
                            Path("config.py").read_text(encoding="utf-8")).group(1)
        changelog = Path("更新日志.md").read_text(encoding="utf-8")
        from scripts.validate_release import validate_release
        self.assertEqual(version, validate_release(Path.cwd()))
        self.assertEqual(version, re.search(r'^##\s+([0-9]+\.[0-9]{2}\.[0-9]{2})', changelog, re.M).group(1))

    def test_about_reads_packaged_changelog_and_reports_missing_source(self):
        from unittest.mock import patch
        from custom_ok.ok.gui.about.AboutTab import AboutTab
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / '更新日志.md'
            path.write_text('## 9.99.99\n验证共同来源', encoding='utf-8')
            with patch('custom_ok.ok.gui.about.AboutTab.get_path_relative_to_exe', return_value=str(path)):
                self.assertEqual(path.read_text(encoding='utf-8'), AboutTab._read_update_log())
                path.unlink()
                self.assertIn('未能读取', AboutTab._read_update_log())

    def test_sensitive_runtime_boundaries_are_ignored(self):
        ignored = Path(".gitignore").read_text(encoding="utf-8")
        for entry in ("账号备份/", "config_bundle_transactions/", "config_integrity_incidents/"):
            self.assertIn(entry, ignored)

    def test_required_runtime_interfaces_exist(self):
        from src.account_graph_store import AccountGraphStore
        from src.observability import CorrelationContext, redact_message
        from src.runtime import AccountSelectionService, SequenceSnapshotService, TaskRunCoordinator
        self.assertTrue(all((AccountGraphStore, CorrelationContext, redact_message,
                             AccountSelectionService, SequenceSnapshotService, TaskRunCoordinator)))

    def test_personal_release_pipeline_has_no_upstream_secrets_or_distribution_jobs(self):
        build = Path(".github/workflows/build.yml").read_text(encoding="utf-8")
        lowered = build.lower()
        for forbidden in ("partial-sync-repo", "signpath", "mirrorchyan", "cnb_token", "ok_gh"):
            self.assertNotIn(forbidden, lowered)
        for stage in ("validate-version", "tests", "package", "package-smoke",
                      "checksums", "github-release"):
            self.assertIn(stage, lowered)
        self.assertIn("refs/tags/v", build)
        self.assertIn("SHA256SUMS.txt", build)

    def test_manual_candidate_build_cannot_publish_a_release(self):
        build = Path(".github/workflows/build.yml").read_text(encoding="utf-8")
        self.assertIn("build_candidate:", build)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.build_candidate", build)
        release_job = build.split("  github-release:", 1)[1]
        self.assertIn("if: startsWith(github.ref, 'refs/tags/v')", release_job)

    def test_optional_mirrorchyan_workflows_are_removed(self):
        self.assertFalse(Path(".github/workflows/mirrorchyan_uploading.yml").exists())
        self.assertFalse(Path(".github/workflows/mirrorchyan_release_note.yml").exists())

    def test_release_validation_and_package_smoke_scripts_exist(self):
        self.assertTrue(Path("scripts/validate_release.py").is_file())
        self.assertTrue(Path("scripts/package_smoke.py").is_file())

    def test_update_package_uses_complete_tracked_overlay_without_local_state(self):
        builder = runpy.run_path('打包更新.py')
        files = dict(builder['collect_files']())
        for name in ('auto_proxy.py', 'assets/coco_annotations.json',
                     'assets/images/logout_power_icon.png',
                     'custom_ok/ok/gui/MainWindow.py', 'custom_ok/ok/gui/about/AboutTab.py',
                     'custom_ok/ok/gui/start/StartTab.py', '更新日志.md', 'requirements.txt'):
            self.assertIn(name, files)
        self.assertFalse(any(name.startswith(('configs/', '.venv/')) for name in files))
        deploy = Path('deploy.txt').read_text(encoding='utf-8').splitlines()
        for name in ('custom_ok', '更新日志.md', 'requirements.txt', 'auto_proxy.py'):
            self.assertIn(name, deploy)
        with self.assertRaisesRegex(ValueError, '缺失'):
            builder['collect_files'](tracked_files=[*files, 'src/missing-required-source.py'])

    def test_release_validator_requires_current_heading_not_a_version_mention(self):
        from scripts.validate_release import validate_release
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'config.py').write_text('version = "9.99.99"', encoding='utf-8')
            (root / '更新日志.md').write_text('mentions 9.99.99 but no release heading', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '更新日志'):
                validate_release(root)

    def test_direct_dependencies_match_the_runtime_lock(self):
        def requirements(path):
            return {line.strip().lower() for line in Path(path).read_text(encoding='utf-8').splitlines()
                    if line.strip() and not line.lstrip().startswith('#')}
        locked = requirements('requirements.txt')
        self.assertTrue(requirements('requirements.in') <= locked)
        self.assertTrue(all('==' in line and '>=' not in line for line in locked))

    def test_pc_only_release_excludes_abandoned_android_artifacts(self):
        config_text = Path("config.py").read_text(encoding="utf-8")
        sync_items = runpy.run_path("打包更新.py")["SYNC_ITEMS"]
        self.assertNotIn("android_config", config_text)
        self.assertNotIn("probe_mumu.py", sync_items)
        for removed in (
            "src/android",
            "android",
            "assets/android",
            "custom_ok/ok/device/capture_methods/nemu_ipc.py",
            "scripts/preflight_mumu.py",
        ):
            self.assertFalse(Path(removed).exists(), removed)

    def test_release_validator_rejects_mismatched_tag(self):
        from scripts.validate_release import validate_release
        version = validate_release(Path.cwd())
        with self.assertRaises(ValueError):
            validate_release(Path.cwd(), f"v{version}.invalid")

    def test_package_smoke_rejects_runtime_config_inside_zip(self):
        from scripts.package_smoke import inspect_distribution
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "candidate.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("working/configs/profile.json", "{}")
            with self.assertRaises(ValueError):
                inspect_distribution(Path(temp))

    def test_package_smoke_allows_notification_but_rejects_other_configs(self):
        from scripts.package_smoke import inspect_distribution
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            allowed = root / "allowed.zip"
            with zipfile.ZipFile(allowed, "w") as package:
                package.writestr("configs/Notification.json", "{}")
            self.assertEqual(inspect_distribution(root), (allowed,))

            forbidden = root / "forbidden.zip"
            with zipfile.ZipFile(forbidden, "w") as package:
                package.writestr("configs/profile.json", "{}")
            with self.assertRaises(ValueError):
                inspect_distribution(root)


if __name__ == "__main__":
    unittest.main()
