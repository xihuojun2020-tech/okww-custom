"""Regression coverage for replacing confirmation dialogs with game identity."""
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.config_integrity import ConfigIntegrityBlocked
from src.task.DailyTask import DailyTask
from src.task.MultiAccountDailyTask import MultiAccountDailyTask, CURRENT_ACCOUNT, CURRENT_SEQUENCE
from src.task.MultiAccountWeeklyGardenTask import MultiAccountWeeklyGardenTask
from src.task.account_feature_verification import (FeatureRun, Observation, begin_task_run,
                                                  current_feature_run)
from tests.fixture_support import make_account_environment


class TestTaskAccountStart(unittest.TestCase):
    def setup_tasks(self, env):
        daily = object.__new__(DailyTask)
        daily.integrity_service = env.integrity
        daily.config = {'Daily Profile': 'A1'}
        daily._runtime_overrides = {}
        daily.info_set = Mock()
        daily.ensure_main = Mock()
        owner = object.__new__(MultiAccountDailyTask)
        owner.integrity_service = env.integrity
        owner.config = {CURRENT_ACCOUNT: 'A3', CURRENT_SEQUENCE: 'S1'}
        owner._load_profiles = lambda: env.repository.legacy_profile_projection()['profiles']
        owner.get_sequence_accounts = Mock(return_value=['A1', 'A3', 'A4'])
        owner._link_daily_profile = Mock(return_value=True)
        owner.info_set = Mock()
        executor = SimpleNamespace(current_task=daily, _account_feature_run=None,
            check_enabled=Mock(), device_manager=SimpleNamespace(
                hwnd_window=SimpleNamespace(hwnd=12, exists=True)))
        daily._executor = owner._executor = executor
        def lookup(kind):
            return daily if kind is DailyTask else owner if kind is MultiAccountDailyTask else None
        daily.get_task_by_class = owner.get_task_by_class = lookup
        return daily, owner, executor

    def test_standalone_uses_multi_selection_without_prompt_and_reads_once_per_start(self):
        with tempfile.TemporaryDirectory() as folder:
            env = make_account_environment(folder)
            daily, owner, executor = self.setup_tasks(env)
            selected = env.repository.legacy_profile_projection()['profiles']['A3']['profile_id']
            with patch('src.account_repository.get_default_repository', return_value=env.repository), \
                 patch('src.task.WWOneTimeTask.WWOneTimeTask.run'), \
                 patch.object(FeatureRun, 'observe', return_value=Observation('verified', 'TEST-FEATURE-A3')) as read:
                daily.before_run()
                self.assertEqual(daily._verified_profile_id, selected)
                self.assertTrue(daily._snapshot_bound_externally)
                self.assertEqual(daily.config['Daily Profile'], 'A1')
                daily._ensure_run_account_confirmation()
                current_feature_run(daily)
                self.assertEqual(read.call_count, 1)
                daily.after_run()
                executor._account_feature_run = None
                daily.before_run()
                self.assertEqual(read.call_count, 2)
                daily.after_run()
                self.assertIsNone(daily._verified_profile_id)

    def test_mismatch_unreadable_and_unbound_stop_before_binding_or_claiming(self):
        for observation in (Observation('verified', 'TEST-FEATURE-A1'),
                            Observation('unreadable'), Observation('verified', 'not-bound')):
            with self.subTest(status=observation.status), tempfile.TemporaryDirectory() as folder:
                env = make_account_environment(folder)
                daily, owner, executor = self.setup_tasks(env)
                daily.bind_verified_profile = Mock()
                with patch('src.account_repository.get_default_repository', return_value=env.repository), \
                     patch('src.task.WWOneTimeTask.WWOneTimeTask.run'), \
                     patch.object(FeatureRun, 'observe', return_value=observation):
                    with self.assertRaises(ConfigIntegrityBlocked):
                        daily.before_run()
                daily.bind_verified_profile.assert_not_called()
                self.assertIsNone(executor._account_feature_run)

    def test_multi_defers_until_world_then_verifies_once_per_visit(self):
        with tempfile.TemporaryDirectory() as folder:
            env = make_account_environment(folder)
            daily, owner, executor = self.setup_tasks(env)
            executor.current_task = owner
            with patch('src.account_repository.get_default_repository', return_value=env.repository), \
                 patch.object(FeatureRun, 'observe', return_value=Observation('verified', 'TEST-FEATURE-A3')) as read:
                owner.before_run()
                read.assert_not_called()
                owner._require_daily_profile('A3')
                owner._require_daily_profile('A3')
                self.assertEqual(read.call_count, 1)
                daily._ensure_run_account_confirmation()
                self.assertEqual(read.call_count, 1)
                executor._account_feature_run = None  # logout invalidates the old visit
                read.return_value = Observation('verified', 'TEST-FEATURE-A4')
                owner._require_daily_profile('A4')
                self.assertEqual(read.call_count, 2)
                self.assertEqual(daily._verified_profile_name, 'A4')
                owner.after_run()

    def test_multi_mismatch_stops_batch_without_recording_farming_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            env = make_account_environment(folder)
            daily, owner, executor = self.setup_tasks(env)
            executor.current_task = owner
            owner._check_progress_date = Mock()
            owner._account_attempts = {}
            owner._retry_phase = False
            owner._failure_key = lambda name: name
            owner._publish_status = Mock()
            owner._mark_failed = Mock()
            owner.run_task_by_class = Mock()
            with patch('src.account_repository.get_default_repository', return_value=env.repository), \
                 patch.object(FeatureRun, 'observe', return_value=Observation('verified', 'TEST-FEATURE-A1')):
                with self.assertRaises(ConfigIntegrityBlocked):
                    owner._run_daily_account('A3')
            owner._mark_failed.assert_not_called()
            owner.run_task_by_class.assert_not_called()

    def test_weekly_batch_inherits_common_selection_and_tools_do_not_verify(self):
        with tempfile.TemporaryDirectory() as folder:
            env = make_account_environment(folder)
            daily, owner, executor = self.setup_tasks(env)
            weekly = object.__new__(MultiAccountWeeklyGardenTask)
            weekly.config = {CURRENT_ACCOUNT: 'A1', CURRENT_SEQUENCE: 'old'}
            weekly._executor = executor
            weekly.get_task_by_class = daily.get_task_by_class
            weekly.get_sequence_accounts = owner.get_sequence_accounts
            with patch.object(FeatureRun, 'observe') as read:
                begin_task_run(weekly)
                self.assertEqual(weekly.config, owner.config)
                begin_task_run(SimpleNamespace(navigation_section='tests'))
                read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
