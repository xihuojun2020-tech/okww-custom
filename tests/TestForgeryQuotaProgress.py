import copy
import tempfile
import unittest
from uuid import uuid4
from src.config_integrity import ConfigIntegrityService
from src.task.forgery_quota_progress import ForgeryQuotaProgress, preserve_forgery_progress


class TestForgeryQuotaProgress(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = ConfigIntegrityService(self.temp.name)
        self.progress = ForgeryQuotaProgress(self.service, 'a1')
        self.goal = str(uuid4())

    def test_confirmed_only_persistent_idempotent_and_account_isolation(self):
        event = self.progress.begin(self.goal, 1, 80, 'rev')
        self.assertEqual({}, self.progress.earned())
        with self.assertRaises(RuntimeError):
            self.progress.begin(self.goal, 1, 40, 'rev')
        self.progress.resolve(event, 40)
        self.progress.resolve(event, 40)
        self.assertEqual({self.goal: 25}, self.progress.earned())
        self.assertEqual({self.goal: 25}, ForgeryQuotaProgress(self.service, 'a1').earned())
        self.assertEqual({}, ForgeryQuotaProgress(self.service, 'a3').earned())
        with self.assertRaises(ValueError):
            self.progress.resolve(event, 80)

    def test_cancel_and_uncertain_cost(self):
        event = self.progress.begin(self.goal, 2, 40, 'rev')
        with self.assertRaises(ValueError):
            self.progress.resolve(event, 60)
        self.assertIn(event, self.progress.pending())
        self.progress.resolve(event, 0)
        self.assertEqual({}, self.progress.earned())
        event = self.progress.begin(self.goal, 2, 80, 'rev')
        self.progress.resolve(event, 80)
        self.assertEqual({self.goal: 50}, self.progress.earned())

    def test_union_preserves_independent_events_and_resolved_state(self):
        event = self.progress.begin(self.goal, 1, 80, 'rev')
        old = {'progress': {self.progress.key: copy.deepcopy(self.progress.read())}}
        self.progress.resolve(event, 80)
        pending = self.progress.begin(self.goal, 1, 40, 'rev')
        current = {'progress': {self.progress.key: self.progress.read()}}
        result = preserve_forgery_progress(old, current)
        events = result['progress'][self.progress.key]['events']
        self.assertEqual('confirmed', events[event]['state'])
        self.assertEqual('pending', events[pending]['state'])
        stale = {'progress': {self.progress.key: {'events': {}}}}
        self.assertEqual(events, preserve_forgery_progress(current, stale)['progress'][self.progress.key]['events'])

    def test_backup_restore_retains_claims_and_pending(self):
        from pathlib import Path
        from src.config_backup import ConfigBackupService
        backup = ConfigBackupService(Path(self.temp.name) / 'configs', Path(self.temp.name) / 'backups', harden_permissions=False)
        event = self.progress.begin(self.goal, 1, 80, 'rev')
        snapshot = backup.create_transaction_snapshot()
        self.progress.resolve(event, 80)
        pending = self.progress.begin(self.goal, 1, 40, 'rev')
        backup.restore(snapshot.path, confirmed=True)
        self.assertEqual({self.goal: 50}, self.progress.earned())
        self.assertIn(pending, self.progress.pending())

    def test_import_old_bundle_preserves_confirmed_claim_and_pending(self):
        from pathlib import Path
        from tests.fixture_support import make_account_environment
        from src.account_config_bundle import AccountConfigBundleService
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(Path(temp))
            identity = env.repository.list_profiles()[0].profile_id
            progress = ForgeryQuotaProgress(env.integrity, identity)
            bundle_service = AccountConfigBundleService(temp, integrity_service=env.integrity)
            event = progress.begin(self.goal, 1, 80, 'rev')
            old = bundle_service.export_bundle()
            progress.resolve(event, 80)
            pending = progress.begin(self.goal, 1, 40, 'rev')
            bundle_service.import_bundle(old, confirm=True, trust_external=True)
            self.assertEqual({self.goal: 50}, progress.earned())
            self.assertIn(pending, progress.pending())
