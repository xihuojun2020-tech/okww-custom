import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import src.config_backup as config_backup
from src.config_backup import ConfigBackupService
from src.task.DailyTask import DailyTask


class TestConfigBackup(unittest.TestCase):
    def test_daily_snapshot_writes_manifest_and_is_verifiable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_dir = root / "configs"
            backup_dir = root / "backups"
            config_dir.mkdir()
            (config_dir / "nested").mkdir()
            (config_dir / "account.json").write_text('{"id": 1}', encoding="utf-8")
            (config_dir / "nested" / "state.bin").write_bytes(b"state")

            service = ConfigBackupService(config_dir, backup_dir, app_version="1.08.00")
            snapshot = service.create_daily_snapshot(now=1700000000)

            self.assertTrue(snapshot.is_complete)
            self.assertTrue((snapshot.path / "manifest.json").is_file())
            manifest = json.loads((snapshot.path / "manifest.json").read_text(encoding="utf-8"))
            entry = next(item for item in manifest["files"] if item["path"] == "nested/state.bin")
            self.assertEqual(entry["length"], 5)
            self.assertEqual(entry["sha256"], hashlib.sha256(b"state").hexdigest())
            self.assertEqual(service.verify_snapshot(snapshot.path).ok, True)

    def test_nested_manifest_is_backed_up_and_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_dir = root / "configs"
            backup_dir = root / "backups"
            nested = config_dir / "published" / "bundle"
            nested.mkdir(parents=True)
            (nested / "manifest.json").write_text('{"revision": "r1"}', encoding="utf-8")

            service = ConfigBackupService(config_dir, backup_dir)
            snapshot = service.create_daily_snapshot(now=1700000000)

            self.assertTrue((snapshot.path / "published" / "bundle" / "manifest.json").is_file())
            self.assertTrue(service.verify_snapshot(snapshot.path).ok)

    def test_failed_build_does_not_leave_a_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_dir = root / "configs"
            backup_dir = root / "backups"
            config_dir.mkdir()
            (config_dir / "one.txt").write_text("one", encoding="utf-8")
            service = ConfigBackupService(config_dir, backup_dir)

            with self.assertRaises(RuntimeError):
                service.create_daily_snapshot(copy_hook=lambda _src, _dst: (_ for _ in ()).throw(RuntimeError("boom")))
            self.assertEqual(list((backup_dir / "daily").glob("*") if (backup_dir / "daily").exists() else []), [])

    def test_preflight_summary_and_restore_are_transactional(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_dir = root / "configs"
            backup_dir = root / "backups"
            config_dir.mkdir()
            (config_dir / "value.json").write_text('{"value": 1}', encoding="utf-8")
            service = ConfigBackupService(config_dir, backup_dir)
            snapshot = service.create_transaction_snapshot()
            (config_dir / "value.json").write_text('{"value": 2}', encoding="utf-8")

            summary = service.preflight_restore(snapshot.path)
            self.assertTrue(summary.ok)
            self.assertIn("value.json", summary.files)
            service.restore(snapshot.path, confirmed=True)
            self.assertEqual((config_dir / "value.json").read_text(encoding="utf-8"), '{"value": 1}')

    def test_preflight_reports_verified_master_and_sequence_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_dir = root / "configs"
            backup_dir = root / "backups"
            config_dir.mkdir()
            from tests.TestAccountConfigBundle import _master
            from src.config_integrity import ConfigIntegrityService, fingerprint, normalize_master
            master = _master()
            (config_dir / "account_master_config.json").write_text(
                json.dumps(master, ensure_ascii=False), encoding="utf-8")
            projection = ConfigIntegrityService(config_dir)._rebuild_working(master, {})
            (config_dir / "daily_profiles.json").write_text(
                json.dumps(projection, ensure_ascii=False), encoding="utf-8")
            (config_dir / "account_runtime_state.json").write_text(json.dumps({
                "completed_at": {}, "progress": {},
                "accepted_master_fingerprint": fingerprint(normalize_master(master)),
            }), encoding="utf-8")
            service = ConfigBackupService(config_dir, backup_dir)
            snapshot = service.create_daily_snapshot()

            summary = service.preflight_restore(snapshot.path)
            self.assertTrue(summary.ok, summary.error)
            self.assertTrue(summary.master_config_present)
            self.assertEqual(summary.account_count, 2)
            self.assertEqual(summary.sequence_count, 1)
            self.assertEqual(summary.sequence_member_count, 2)
            self.assertEqual(summary.sequence_summary, {"序列1": 2})

    def test_preflight_blocks_snapshot_with_invalid_master_even_if_hashes_match(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_dir = root / "configs"
            backup_dir = root / "backups"
            config_dir.mkdir()
            (config_dir / "account_master_config.json").write_text('{"profiles": {}}', encoding="utf-8")
            service = ConfigBackupService(config_dir, backup_dir)
            snapshot = service.create_daily_snapshot()
            summary = service.preflight_restore(snapshot.path)
            self.assertFalse(summary.ok)
            self.assertIn("invalid account configuration", summary.error)

    def test_retention_removes_old_complete_snapshots_as_whole_units(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_dir = root / "configs"
            backup_dir = root / "backups"
            config_dir.mkdir()
            (config_dir / "value").write_text("x", encoding="utf-8")
            service = ConfigBackupService(config_dir, backup_dir, daily_limit=2, total_limit_bytes=10**9)
            service.create_daily_snapshot(now=1)
            service.create_daily_snapshot(now=2)
            service.create_daily_snapshot(now=3)
            snapshots = list((backup_dir / "daily").iterdir())
            self.assertEqual(len(snapshots), 2)
            self.assertTrue(all((item / "manifest.json").is_file() for item in snapshots))

    def test_failed_second_swap_rolls_back_live_tree_immediately(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_dir = root / "configs"
            backup_dir = root / "backups"
            config_dir.mkdir()
            value = config_dir / "value.json"
            value.write_text('{"value": 1}', encoding="utf-8")
            service = ConfigBackupService(config_dir, backup_dir)
            snapshot = service.create_daily_snapshot()
            value.write_text('{"value": 2}', encoding="utf-8")

            real_replace = config_backup.os.replace

            def fail_new_config(source, destination):
                if Path(destination) == config_dir and Path(source).name.startswith(".restore-"):
                    raise OSError("simulated crash during second swap")
                return real_replace(source, destination)

            with patch.object(config_backup.os, "replace", side_effect=fail_new_config):
                with self.assertRaises(OSError):
                    service.restore(snapshot.path, confirmed=True)
            self.assertTrue(config_dir.is_dir())
            self.assertFalse(service.restore_journal_path.exists())
            self.assertEqual(value.read_text(encoding="utf-8"), '{"value": 2}')

    def test_restore_journal_cannot_target_paths_outside_the_service_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_dir = root / "configs"
            backup_dir = root / "backups"
            sentinel = root / "do-not-delete"
            config_dir.mkdir()
            backup_dir.mkdir()
            sentinel.mkdir()
            (sentinel / "keep.txt").write_text("keep", encoding="utf-8")
            journal = {
                "version": 1, "phase": "prepared", "config_dir": str(config_dir),
                "staging": str(sentinel), "old": str(root / "configs.rollback-safe"),
                "source": str(root / "source"),
            }
            (backup_dir / ".restore-journal.json").write_text(json.dumps(journal), encoding="utf-8")

            with self.assertRaises(RuntimeError):
                ConfigBackupService(config_dir, backup_dir)
            self.assertEqual((sentinel / "keep.txt").read_text(encoding="utf-8"), "keep")
            self.assertTrue((backup_dir / '.restore-journal.json').exists())

    def test_shared_backup_resolver_precedence_and_config_exclusion(self):
        from src.storage import resolve_config_backup_dir, get_config_backup_dir
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for values, expected in [({}, root / 'configs_backup'),
                                     ({'legacy_backup_dir': 'old'}, root / 'old'),
                                     ({'warehouse_root': 'warehouse', 'legacy_backup_dir': 'old'},
                                      root / 'warehouse/ok仓库/配置备份'),
                                     ({'legacy_backup_dir': str(root / 'configs/backups')}, root / 'configs_backup')]:
                self.assertEqual(resolve_config_backup_dir(root, **values), expected)
            settings = {'数据仓库文件夹': {'数据仓库文件夹': str(root / 'warehouse')},
                        'Config Backup': {'Config Backup Directory': str(root / 'old')}}
            with patch('ok.og.executor', SimpleNamespace(global_config=SimpleNamespace(get_config=settings.get))):
                self.assertEqual(get_config_backup_dir(root), root / 'warehouse/ok仓库/配置备份')

    def test_external_and_cross_volume_restore_roundtrip(self):
        from tests.fixture_support import make_account_environment
        volumes = [None]
        if os.name == 'nt' and Path('C:/').exists() and Path('E:/').exists():
            volumes.append('E:/AI work/ok-wuthering-waves-master/test_out')
        for application_volume in volumes:
            with self.subTest(volume=application_volume), tempfile.TemporaryDirectory(dir=application_volume) as temp, \
                    tempfile.TemporaryDirectory() as external:
                env = make_account_environment(Path(temp))
                config = env.integrity.paths.config_dir
                state = config / '运行状态/账号/test.json'
                state.parent.mkdir(parents=True, exist_ok=True)
                state.write_text('{"completed": true}', encoding='utf-8')
                service = ConfigBackupService(config, Path(external) / 'warehouse/backups')
                snapshot = service.create_daily_snapshot()
                expected = {p.relative_to(config): p.read_bytes() for p in config.rglob('*') if p.is_file()}
                state.write_text('{"completed": false}', encoding='utf-8')
                real_replace = os.replace
                renamed = []
                def same_volume(source, target):
                    if Path(target) == config or Path(source) == config:
                        self.assertEqual(Path(source).parent, config.parent)
                        self.assertEqual(Path(target).parent, config.parent)
                        renamed.append((source, target))
                    return real_replace(source, target)
                with patch.object(config_backup.os, 'replace', side_effect=same_volume):
                    self.assertTrue(service.restore(snapshot.path, confirmed=True).ok)
                actual = {p.relative_to(config): p.read_bytes() for p in config.rglob('*') if p.is_file()}
                self.assertEqual(actual, expected)
                self.assertEqual(len(renamed), 2)
                if application_volume:
                    self.assertNotEqual(config.drive, service.backup_dir.drive)
                self.assertTrue(service.verify_snapshot(snapshot.path).ok)

    def test_restore_faults_preserve_old_tree_and_source(self):
        for fault in ('copy', 'source_changes', 'first_swap', 'final_check'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temp:
                config = Path(temp) / 'app/configs'
                config.mkdir(parents=True)
                value = config / 'value'
                value.write_text('old')
                service = ConfigBackupService(config, Path(temp) / 'warehouse/backups', transaction_limit=0)
                snapshot = service.create_transaction_snapshot()
                value.write_text('current')
                real_copy, real_replace = service._copy_tree, os.replace
                def copy(source, target, **kwargs):
                    if Path(source) == snapshot.path:
                        if fault == 'copy':
                            raise OSError('copy failed')
                        if fault == 'source_changes':
                            (snapshot.path / 'value').write_text('changed')
                    return real_copy(source, target, **kwargs)
                def replace(source, target):
                    if fault == 'first_swap' and Path(source) == config:
                        raise PermissionError('target in use')
                    return real_replace(source, target)
                with patch.object(service, '_copy_tree', side_effect=copy), \
                        patch.object(config_backup.os, 'replace', side_effect=replace), \
                        patch.object(service, '_account_tree_valid', return_value=fault != 'final_check'):
                    with self.assertRaises((OSError, RuntimeError)):
                        service.restore(snapshot.path, confirmed=True)
                self.assertEqual(value.read_text(), 'current')
                self.assertTrue(snapshot.path.exists())
                self.assertFalse(service.restore_journal_path.exists())

    def test_interrupted_restore_recovers_each_directory_swap_phase(self):
        class Interrupted(BaseException):
            pass
        for phase in ('prepared', 'verified', 'first_swap', 'second_swap', 'activated'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                config = root / 'configs'
                config.mkdir()
                value = config / 'value'
                value.write_text('snapshot')
                service = ConfigBackupService(config, root / 'backups')
                snapshot = service.create_daily_snapshot()
                value.write_text('current')
                real_write, real_replace = service._write_restore_journal, os.replace
                def write(journal):
                    real_write(journal)
                    if journal['phase'] == phase:
                        raise Interrupted()
                def replace(source, target):
                    real_replace(source, target)
                    if (phase == 'first_swap' and Path(source) == config or
                            phase == 'second_swap' and Path(target) == config):
                        raise Interrupted()
                with patch.object(service, '_write_restore_journal', side_effect=write), \
                        patch.object(config_backup.os, 'replace', side_effect=replace):
                    with self.assertRaises(Interrupted):
                        service.restore(snapshot.path, confirmed=True)
                # New constructor sees the target-side journal even when the
                # warehouse setting cannot be read because configs is absent.
                recovered = ConfigBackupService(config, root / 'default-backups')
                self.assertEqual(value.read_text(), 'snapshot' if phase == 'activated' else 'current')
                self.assertFalse(recovered.restore_journal_path.exists())
                self.assertFalse(list(root.glob('configs.rollback-*')))
                self.assertFalse(list(root.glob('.restore-*')))

    def test_restore_blocks_running_or_paused_task(self):
        with tempfile.TemporaryDirectory() as temp:
            service = ConfigBackupService(Path(temp) / 'configs', Path(temp) / 'backups')
            with patch('ok.og.executor', SimpleNamespace(current_task=object())):
                with self.assertRaisesRegex(Exception, '运行或暂停'):
                    service.restore(service.backup_dir / 'snapshot', confirmed=True)

    def test_cleanup_failure_or_no_progress_only_attempts_once(self):
        for failure in (PermissionError('locked'), None):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                config = root / 'configs'
                config.mkdir()
                (config / 'value').write_text('value')
                service = ConfigBackupService(config, root / 'backups')
                snapshot = service.create_daily_snapshot()
                service.total_limit_bytes = 0
                calls = []
                def remove(path, *args, **kwargs):
                    calls.append(path)
                    if len(calls) > 1:
                        raise AssertionError('cleanup repeated an undeletable candidate')
                    if failure:
                        raise failure
                with patch.object(config_backup.shutil, 'rmtree', side_effect=remove), \
                        self.assertLogs('src.config_backup', level='WARNING'):
                    service.cleanup()
                self.assertEqual(calls, [snapshot.path])
                self.assertTrue(snapshot.path.exists())
                service.cleanup()
                self.assertFalse(snapshot.path.exists())
                service.cleanup()  # Empty candidates terminate as well.

    def test_cleanup_retains_all_snapshots_while_restore_is_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / 'configs'
            config.mkdir()
            service = ConfigBackupService(config, root / 'backups')
            source = service.create_daily_snapshot()
            rollback = service.create_transaction_snapshot()
            service.restore_journal_path.parent.mkdir(parents=True, exist_ok=True)
            service.restore_journal_path.write_text('{}')
            service.daily_limit = service.transaction_limit = service.total_limit_bytes = 0
            service.cleanup()
            self.assertTrue(source.path.exists())
            self.assertTrue(rollback.path.exists())

    def test_snapshot_manifest_paths_and_descendant_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / 'configs'
            config.mkdir()
            (config / 'value').write_text('value')
            service = ConfigBackupService(config, root / 'backups')
            snapshot = service.create_daily_snapshot()
            manifest_path = snapshot.path / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            original = manifest['files'][0].copy()
            for name in ('../value', '/value', 'C:/value', 'nested\\value', './value'):
                with self.subTest(name=name):
                    manifest['files'] = [dict(original, path=name)]
                    manifest_path.write_text(json.dumps(manifest))
                    self.assertFalse(service.verify_snapshot(snapshot.path).ok)
            manifest['files'] = [original, original]
            manifest_path.write_text(json.dumps(manifest))
            self.assertFalse(service.verify_snapshot(snapshot.path).ok)
            manifest['files'] = [original]
            manifest_path.write_text(json.dumps(manifest))
            link = snapshot.path / 'outside'
            link.symlink_to(config, target_is_directory=True)
            try:
                self.assertFalse(service.verify_snapshot(snapshot.path).ok)
            finally:
                link.unlink()

    def test_preflight_rejects_damaged_active_even_when_snapshot_hashes_match(self):
        from tests.fixture_support import make_account_environment
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            env = make_account_environment(root)
            active = env.publisher.load_active()
            profile = next((active.bundle_dir / 'profiles').glob('*.json'))
            profile.write_text('{}')
            service = ConfigBackupService(env.integrity.paths.config_dir, root / 'backups')
            snapshot = service.create_daily_snapshot()
            self.assertTrue(service.verify_snapshot(snapshot.path).ok)
            self.assertFalse(service.preflight_restore(snapshot.path).ok)

    def test_daily_task_injects_governed_transaction_snapshot_hook(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_dir = root / "configs"
            backup_dir = root / "backups"
            config_dir.mkdir()
            (config_dir / "master.json").write_text('{"value": 1}', encoding="utf-8")
            backup = ConfigBackupService(config_dir, backup_dir)

            class FakeBundleService:
                def __init__(self, *, transaction_snapshot_hook=None):
                    self.hook = transaction_snapshot_hook

            task = DailyTask.__new__(DailyTask)
            task._config_backup_service = lambda: backup
            fake_module = SimpleNamespace(AccountConfigBundleService=FakeBundleService)
            with patch("src.task.DailyTask.importlib.import_module", return_value=fake_module):
                service = task._get_account_bundle_service()
            snapshot_path = service.hook({"ignored": b"before"})

            self.assertTrue(Path(snapshot_path).is_dir())
            self.assertEqual(Path(snapshot_path).parent.name, "transactions")
            self.assertFalse((root / "config_bundle_transactions").exists())

    def test_daily_task_sequence_repair_creates_snapshot_before_core_write(self):
        calls = []

        class Integrity:
            def detect_missing_sequences(self):
                return {"eligible": True, "sequence_count": 2, "account_count": 3}

            def repair_missing_sequences(self, *, confirm=False):
                calls.append(("repair", confirm))
                return "repaired"

        task = DailyTask.__new__(DailyTask)
        task.integrity_service = Integrity()
        task.log_info = lambda *_args, **_kwargs: None
        task._confirm_legacy_sequence_repair = lambda _detection: True
        task._transaction_snapshot_hook = lambda _before=None: calls.append(("snapshot", True)) or "snapshot-path"

        self.assertEqual(task.repair_legacy_sequences(), "repaired")
        self.assertEqual(calls, [("snapshot", True), ("repair", True)])


if __name__ == "__main__":
    unittest.main()
