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
        about = Path("custom_ok/ok/gui/about/AboutTab.py").read_text(encoding="utf-8")
        self.assertRegex(version, r"^[0-9]+\.[0-9]{2}\.[0-9]{2}$")
        self.assertEqual(version, "1.23.01")
        self.assertIn(version, changelog)
        self.assertIn(f"V{version}", about)
        for theme in ("Foreground BitBlt", "WGC", "点击连接", "SendInput"):
            self.assertIn(theme, changelog)
            self.assertIn(theme, about)

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

    def test_update_package_includes_logout_feature_and_release_notes(self):
        sync_items = runpy.run_path("打包更新.py")["SYNC_ITEMS"]
        for required in (
            "assets/coco_annotations.json",
            "assets/images/logout_power_icon.png",
            "assets/images/abyss_period_challenge_icon.png",
            "assets/images/abyss_completed_icon.png",
            "assets/images/abyss_locked_icon.png",
            "custom_ok/ok/gui/about/AboutTab.py",
            "更新日志.md",
        ):
            self.assertIn(required, sync_items)

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


if __name__ == "__main__":
    unittest.main()
