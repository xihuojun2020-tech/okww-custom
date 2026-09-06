import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.account_config_bundle import AccountConfigBundleService
from src.account_config_editor import AccountConfigEditor, AccountLabelMismatch
from src.account_repository import AccountRepositoryError, ProfileEditScope
from src.account_publish_service import AccountPublishService
from src import config_integrity as ci
from tests.fixture_support import make_account_environment, synthetic_identity


class TestAccountDeletion(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = make_account_environment(self.root, names=('A1', 'A3'))
        self.repo = self.env.repository
        self.a, self.b = (synthetic_identity(name)['profile_id'] for name in ('A1', 'A3'))
        self.repo.publish_sequence('S2', [self.b])
        self.repo.record_completion(self.b, 'daily', 'today')
        self.env.integrity.record_completion(self.b, 'daily', 'today')

    def delete(self):
        return self.repo.delete_profile_cascade(self.b, expected_revision=self.repo.load_profile(self.b).revision)

    def test_cascade_delete_removes_all_references_and_both_runtime_stores(self):
        self.assertEqual(self.repo.preview_profile_deletion(self.b).sequence_ids, ('S1', 'S2'))
        self.delete()
        self.assertNotIn(self.b, self.repo.list_profile_ids())
        self.assertEqual(self.repo.load_sequence('S1').profile_ids, (self.a,))
        self.assertEqual(self.repo.load_sequence('S2').profile_ids, ())
        self.assertFalse(self.repo._account_state_path(self.b).exists())
        self.assertNotIn(self.b, ci._read_json(self.env.integrity.paths.runtime)[0]['completed_at'])
        self.assertFalse((self.root / 'configs/accounts/profiles' / (self.b + '.json')).exists())
        self.assertTrue(any((self.repo.backup_dir / self.b).glob('*.dpapi')))
        self.assertTrue(self.env.integrity.check(record_incident=False).ok)
        with self.assertRaisesRegex(AccountRepositoryError, '至少必须保留'):
            self.repo.delete_profile_cascade(self.a, expected_revision=self.repo.load_profile(self.a).revision)

    def test_precommit_failure_restores_exact_files_and_active(self):
        bundle = AccountConfigBundleService(self.root, integrity_service=self.env.integrity)
        paths = [*bundle._transaction_targets([self.b]).values(), self.env.publisher.active_path]
        before = {path: path.read_bytes() if path.exists() else None for path in paths}
        self.repo.deletion_postcheck_hook = lambda: (_ for _ in ()).throw(RuntimeError('forced'))
        with self.assertRaisesRegex(RuntimeError, 'forced'):
            self.delete()
        for path, payload in before.items():
            self.assertEqual(path.read_bytes() if path.exists() else None, payload)
        self.assertIn(self.b, self.repo.list_profile_ids())

    def test_failures_in_preparation_legacy_write_and_activation_keep_old_graph(self):
        for owner, name in ((AccountPublishService, 'prepare'), (ci, 'atomic_write_json'),
                            (AccountPublishService, '_write_active_pointer')):
            with self.subTest(phase=name):
                active = self.env.publisher.active_path.read_bytes()
                state = self.repo._account_state_path(self.b).read_bytes()
                with patch.object(owner, name, side_effect=OSError('forced')):
                    with self.assertRaises(OSError):
                        self.delete()
                self.assertEqual(self.env.publisher.active_path.read_bytes(), active)
                self.assertEqual(self.repo._account_state_path(self.b).read_bytes(), state)
                self.assertIn(self.b, self.repo.list_profile_ids())
                self.assertTrue(self.env.integrity.check(record_incident=False).ok)

    def test_postcommit_mirror_failure_stays_committed_and_recovers(self):
        with patch.object(AccountPublishService, '_mirror_projections', side_effect=OSError('forced mirror')):
            self.delete()
        self.assertTrue(self.repo.last_publish_result.maintenance_errors)
        self.assertNotIn(self.b, self.repo.list_profile_ids())
        self.assertFalse(self.repo._account_state_path(self.b).exists())
        AccountConfigBundleService(self.root).recover_incomplete_transactions()
        self.assertFalse((self.root / 'configs/accounts/profiles' / (self.b + '.json')).exists())
        self.assertFalse(self.env.publisher.maintenance_path.exists())
        self.assertTrue(self.env.integrity.check(record_incident=False).ok)

    def test_editor_requires_exact_account_label(self):
        editor = AccountConfigEditor(self.repo)
        record = self.repo.load_profile(self.b)
        with self.assertRaises(AccountLabelMismatch):
            editor.delete_profile(ProfileEditScope(self.b, record.revision), confirmed_account_label='A4')


if __name__ == '__main__':
    unittest.main()
