"""Synthetic configuration transactions and genuine no-device owner leases."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gameframe.process_locks import LeaseUnavailable, data_lease
from src.config_backup import ConfigBackupService
from src.config_integrity import ConfigIntegrityBlocked, _atomic_write_json_unchecked, fingerprint, normalize_master
from src.native_maintenance import MaintenanceCommittedError, NativeMaintenanceService, prepare_native_data
from src.runtime.account_runtime_bootstrap import (
    _reset_account_runtime_for_tests, get_account_runtime, initialize_account_runtime)
from tests.fixture_support import make_account_environment


ROOT = Path(__file__).resolve().parents[1]


class TestNativeMaintenance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'private-data'
        self.fixture = make_account_environment(self.root)
        self.service = NativeMaintenanceService(self.root, 'test-maintenance')
        _reset_account_runtime_for_tests()
        self.addCleanup(_reset_account_runtime_for_tests)

    def shared_owner(self):
        code = f'import sys; sys.path.insert(0, {str(ROOT)!r})\n' + '''
from gameframe.process_locks import data_lease
with data_lease(sys.argv[1]):
    print('ready', flush=True)
    sys.stdin.readline()
'''
        process = subprocess.Popen([sys.executable, '-I', '-X', 'utf8', '-u', '-c', code, str(self.root)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8')
        def close():
            if process.poll() is None:
                process.stdin.write('\n')
                process.stdin.flush()
            output, error = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, output + error)
        self.addCleanup(close)
        self.assertEqual(process.stdout.readline().strip(), 'ready')
        return process

    def interrupted_swap(self):
        configs = self.root / 'configs'
        old = self.root / 'configs.rollback-synthetic'
        configs.rename(old)
        staging = self.root / '.restore-synthetic'
        staging.mkdir()
        journal = self.root / '.configs-restore/journal.json'
        _atomic_write_json_unchecked(journal, {
            'version': 2, 'config_dir': str(configs), 'old': str(old),
            'staging': str(staging), 'phase': 'old_moved', 'had_config': True})
        return journal

    def empty_sequences(self):
        paths = self.fixture.integrity.paths
        master = self.fixture.master
        master['sequences'] = {}
        _atomic_write_json_unchecked(paths.master, master)
        _atomic_write_json_unchecked(paths.working, self.fixture.integrity._rebuild_working(master, {}))
        _atomic_write_json_unchecked(paths.runtime, {
            'accepted_master_fingerprint': fingerprint(normalize_master(master)),
            'completed_at': {}, 'progress': {}})
        _atomic_write_json_unchecked(paths.multi_account_task, {'序列 1 账号': ['A1', 'A3']})

    def test_safe_daily_is_deduplicated_and_paths_are_explicit(self):
        first = prepare_native_data(self.root, 'test-maintenance')
        self.assertEqual(first['status'], 'created')
        self.assertTrue(self.service.verify_snapshot(first['snapshot'].path).ok)
        self.assertEqual(prepare_native_data(self.root, 'test-maintenance')['status'], 'already-created')
        self.assertEqual(self.service.paths()['configs'], self.root / 'configs')
        self.assertEqual(len(list((self.root / 'configs_backup/daily').iterdir())), 1)
        empty = self.root.parent / 'fresh-data'
        self.assertEqual(prepare_native_data(empty, 'test')['status'], 'not-initialized')
        self.assertFalse((empty / 'configs_backup').exists())

    def test_real_shared_owner_blocks_snapshot_restore_and_repair(self):
        snapshot = self.service.create_snapshot()
        preview = self.service.preview_restore(snapshot.path)
        self.shared_owner()
        self.assertEqual(prepare_native_data(self.root, 'test')['status'], 'deferred')
        self.assertTrue(self.service.verify_snapshot(snapshot.path).ok)
        for action in (self.service.create_snapshot,
                       lambda: self.service.restore(snapshot.path, preview, confirmed=True),
                       lambda: self.service.repair_sequences({}, confirmed=True)):
            with self.assertRaises(LeaseUnavailable):
                action()
        self.assertFalse(self.service.paths()['restore_journal'].exists())

    def test_pending_swap_cannot_recover_under_shared_owner(self):
        journal = self.interrupted_swap()
        self.shared_owner()
        before = journal.read_bytes()
        with self.assertRaisesRegex(RuntimeError, '独占锁'):
            prepare_native_data(self.root, 'test')
        with self.assertRaisesRegex(RuntimeError, '独占锁'):
            initialize_account_runtime(self.root, 'test', install_start_guard=False,
                                       backup_dir=self.root / 'configs_backup', restore_prepared=True)
        self.assertEqual(journal.read_bytes(), before)
        self.assertFalse((self.root / 'configs').exists())

    def test_pending_swap_recovers_before_daily_snapshot(self):
        journal = self.interrupted_swap()
        self.assertEqual(prepare_native_data(self.root, 'test')['status'], 'created')
        self.assertFalse(journal.exists())
        self.assertTrue((self.root / 'configs/account_master_config.json').is_file())
        self.assertFalse((self.root / 'configs.rollback-synthetic').exists())

    def test_restore_reloads_fresh_runtime_and_rejects_stale_preview(self):
        old = initialize_account_runtime(self.root, 'test', install_start_guard=False,
                                         backup_dir=self.root / 'configs_backup')
        snapshot = self.service.create_snapshot()
        preview = self.service.preview_restore(snapshot.path)
        master = self.root / 'configs/account_master_config.json'
        master.write_bytes(master.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, '预览'):
            self.service.restore(snapshot.path, preview, confirmed=True)
        preview = self.service.preview_restore(snapshot.path)
        self.assertTrue(self.service.restore(snapshot.path, preview, confirmed=True).ok)
        self.assertIsNot(self.service.runtime, old)
        self.assertIsNot(self.service.runtime.repository, old.repository)
        self.assertIs(get_account_runtime(), self.service.runtime)
        self.assertTrue(self.service.runtime.integrity_result.ok)

    def test_committed_restore_reload_failure_is_explicit(self):
        initialize_account_runtime(self.root, 'test', install_start_guard=False,
                                   backup_dir=self.root / 'configs_backup')
        snapshot = self.service.create_snapshot()
        marker = self.root / 'configs/after-snapshot.json'
        marker.write_text('{}')
        preview = self.service.preview_restore(snapshot.path)
        with patch('src.runtime.account_runtime_bootstrap.initialize_account_runtime',
                   side_effect=RuntimeError('reload fixture')):
            with self.assertRaises(MaintenanceCommittedError) as raised:
                self.service.restore(snapshot.path, preview, confirmed=True)
        self.assertTrue(raised.exception.committed)
        self.assertEqual(raised.exception.operation, 'restore')
        self.assertFalse(marker.exists())
        self.assertIsNone(self.service.runtime)
        self.assertIsNone(get_account_runtime())
        self.assertFalse(self.service.paths()['restore_journal'].exists())

    def test_sequence_repair_revalidates_snapshots_and_reloads(self):
        self.empty_sequences()
        preview = self.service.preview_sequence_repair()
        self.assertTrue(preview['eligible'])
        with self.assertRaises(ConfigIntegrityBlocked):
            self.service.repair_sequences(preview)
        _atomic_write_json_unchecked(self.fixture.integrity.paths.multi_account_task,
                                     {'序列 1 账号': ['A3', 'A1']})
        with self.assertRaises(ConfigIntegrityBlocked):
            self.service.repair_sequences(preview, confirmed=True)
        self.assertFalse((self.root / 'configs_backup/transactions').exists())
        preview = self.service.preview_sequence_repair()
        result = self.service.repair_sequences(preview, confirmed=True)
        self.assertTrue(result.ok)
        self.assertEqual(len(list((self.root / 'configs_backup/transactions').iterdir())), 1)
        self.assertIs(get_account_runtime(), self.service.runtime)
        self.assertTrue(self.service.preview_sequence_repair()['already_applied'])

    def test_worker_pre_data_hook_runs_before_shared_lease(self):
        from gameframe import worker
        from types import SimpleNamespace
        events = []
        class Package:
            def prepare_data(self, root):
                with data_lease(root, exclusive=True):
                    events.append('pre-data')
            def prepare(self, task, root):
                with self_test.assertRaises(LeaseUnavailable):
                    with data_lease(root, exclusive=True):
                        pass
                events.append('prepare')
                raise RuntimeError('stop before device')
            def close(self):
                events.append('close')
        self_test = self
        manifest = SimpleNamespace(version='test', execution='native', supports_session=True,
                                   task=lambda value: SimpleNamespace(id=value), load=lambda: Package())
        with patch.object(worker.PackageManifest, 'read', return_value=manifest), \
                patch.object(worker, 'listen_stop'), patch.object(worker, 'emit'), \
                patch.object(worker, 'create_device') as device:
            self.assertEqual(worker.main(['--package', str(self.root / 'package'), '--task', 'synthetic',
                                          '--data-dir', str(self.root), '--device', '{"type":"replay"}']), 1)
        self.assertEqual(events, ['pre-data', 'prepare', 'close'])
        device.assert_not_called()

    def test_cleanup_reports_deletion_failure_and_completion(self):
        snapshot = self.service.create_snapshot()
        self.assertTrue(self.service.cleanup())
        with data_lease(self.root, exclusive=True):
            engine = ConfigBackupService(self.root / 'configs', self.root / 'configs_backup',
                                         transaction_limit=0)
            with patch('src.config_backup.shutil.rmtree', side_effect=OSError('deletion fixture')):
                with self.assertLogs('src.config_backup', level='WARNING'):
                    self.assertFalse(engine.cleanup())
            self.assertTrue(snapshot.path.exists())
            self.assertTrue(engine.cleanup())
            self.assertFalse(snapshot.path.exists())


if __name__ == '__main__':
    unittest.main()
