import hashlib
import json
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

            service = ConfigBackupService(config_dir, backup_dir)
            self.assertFalse(service.recover_pending_restore())
            self.assertEqual((sentinel / "keep.txt").read_text(encoding="utf-8"), "keep")
            self.assertTrue(service.restore_journal_path.exists())

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
