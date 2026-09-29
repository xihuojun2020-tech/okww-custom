import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ok import og, TaskDisabledException
from ok.task.exceptions import FinishedException
from src.task.MultiAccountDailyTask import MultiAccountDailyTask
from src.task.MultiAccountDailyTask import CURRENT_SEQUENCE
from src.task.MultiAccountWeeklyGardenTask import (
    MAX_ACCOUNTS, TIME_BUDGET, MultiAccountWeeklyGardenTask,
)
from src.task.weekly_garden import BEIJING, GARDEN_INDEPENDENT, garden_week_key


class MemoryConfig(dict):
    def has_user_config(self):
        return True

    def get_default(self, key):
        return self.get(key)


class TestMultiAccountWeeklyGardenTask(unittest.TestCase):
    def test_shared_completion_is_the_only_non_closed_done_source(self):
        task = object.__new__(MultiAccountWeeklyGardenTask)
        task._profile_id_for = lambda _name: 'profile-a1'
        task._load_profiles = lambda: {'A1': {'task_config': {'Garden Execution Mode': GARDEN_INDEPENDENT}}}
        task.integrity_service = SimpleNamespace(get_completion=lambda *_: None)
        task.done_set = {'profile-a1'}
        self.assertFalse(task._garden_done('A1'))

        task.integrity_service.get_completion = lambda *_: datetime.now(BEIJING).isoformat()
        self.assertTrue(task._garden_done('A1'))

    def test_batch_limits_stop_new_accounts_and_retries_at_account_boundary(self):
        task = object.__new__(MultiAccountWeeklyGardenTask)
        task.config = {MAX_ACCOUNTS: 1, TIME_BUDGET: 0}
        task._garden_entered = {'profile-a1'}
        task._garden_started_at = time.monotonic()
        task.get_sequence_accounts = lambda: ['A1', 'A3']
        task._active_run_snapshot = None
        task._reconcile_failures = Mock()
        with patch.object(MultiAccountDailyTask, '_next_target_account', return_value='A1') as parent:
            self.assertIsNone(task._next_target_account())
            parent.assert_not_called()

    def test_time_budget_can_stop_before_first_account_and_unlimited_retry_stays_at_boundary(self):
        task = object.__new__(MultiAccountWeeklyGardenTask)
        task.config = {MAX_ACCOUNTS: 0, TIME_BUDGET: 1}
        task._garden_entered = set()
        task._garden_started_at = time.monotonic() - 61
        self.assertFalse(task._account_start_allowed('A1'))

        task.config[TIME_BUDGET] = 0
        task._garden_entered = {'profile-a1'}
        task._garden_started_at = time.monotonic()
        task._active_run_snapshot = None
        task.get_sequence_accounts = lambda: ['A1', 'A3']
        task._failure_key = lambda account: {'A1': 'profile-a1', 'A3': 'profile-a3'}[account]
        task._reconcile_failures = Mock()
        with patch.object(MultiAccountDailyTask, '_next_target_account', return_value='A1') as parent:
            self.assertEqual(task._next_target_account(), 'A1')
            parent.assert_called_once_with()

        task._garden_entered.clear()
        task.config[TIME_BUDGET] = 5
        task._garden_started_at = time.monotonic() - 301
        with patch.object(MultiAccountDailyTask, '_next_target_account', return_value='A1') as parent:
            self.assertIsNone(task._next_target_account())
            parent.assert_not_called()

    def test_weekly_progress_uses_separate_file_and_shared_failure_key(self):
        task = object.__new__(MultiAccountWeeklyGardenTask)
        task._garden_week_key = garden_week_key()
        task._garden_progress_file = 'weekly-progress.json'
        self.assertEqual(task._progress_path(), 'weekly-progress.json')
        self.assertEqual(task._progress_key(), f'multi_account_garden:{task._garden_week_key}')
        self.assertEqual(task._failures_key(), f'multi_account_garden_failures:{task._garden_week_key}')

    def test_stop_exceptions_are_never_recorded_as_failures(self):
        for error in (TaskDisabledException('user stopped'), FinishedException()):
            task = object.__new__(MultiAccountWeeklyGardenTask)
            task._check_progress_date = Mock()
            task._failure_key = lambda _account: 'profile-a1'
            task._garden_entered = set()
            task._account_attempts = {}
            task._retry_phase = False
            task.info_set = Mock()
            task._require_daily_profile = Mock()
            task.get_task_by_class = lambda *_: SimpleNamespace(
                run_weekly_garden_only=lambda error=error: (_ for _ in ()).throw(error))
            task._mark_failed = Mock()
            with self.assertRaises(type(error)):
                task._execute_account_task('A1')
            task._mark_failed.assert_not_called()

    def test_weekly_failure_record_keeps_week_and_evidence_reference(self):
        from src.task.weekly_garden import GardenRunResult
        task = object.__new__(MultiAccountWeeklyGardenTask)
        task.failed_accounts = {}
        task._account_attempts = {'profile-a1': 1}
        task._attempt_scope = 'weekly'
        task._failure_key = lambda _account: 'profile-a1'
        task._progress_period = lambda: 'week-key'
        task._last_garden_result = GardenRunResult(
            'pending', 'week-key', error='score unclear', evidence_ref='evidence-42')
        task._save_failed_accounts = Mock()
        task.info_set = Mock()
        task.log_info = Mock()
        result = task._mark_failed('A1', RuntimeError('score unclear'))
        self.assertEqual(result['scope'], 'weekly')
        self.assertEqual(result['week_key'], 'week-key')
        self.assertEqual(result['evidence_ref'], 'evidence-42')
        self.assertEqual(task._save_failed_accounts.call_count, 2)

    def test_garden_score_reader_requires_a_fresh_frame_and_explicit_pair(self):
        from src.task.GardenTask import GardenTask

        task = object.__new__(GardenTask)
        task.log_info = Mock()
        frame = object()
        task.next_frame = Mock(return_value=frame)
        task.ocr = Mock(return_value=[SimpleNamespace(name='6000 / 6000')])
        self.assertEqual(task.read_weekly_garden_points(), 6000)
        self.assertIs(task.ocr.call_args.kwargs['frame'], frame)

        task.next_frame.return_value = None
        task.ocr.reset_mock()
        self.assertIsNone(task.read_weekly_garden_points())
        task.ocr.assert_not_called()

        for text, expected in (('6000', None), ('1200 / 6000', 1200), (' 6000/6000 ', 6000)):
            task.next_frame.return_value = frame
            task.ocr.return_value = [SimpleNamespace(name=text)]
            self.assertEqual(task.read_weekly_garden_points(), expected)

    def test_new_task_is_registered_and_real_card_exposes_weekly_controls(self):
        from config import config
        from src.gui.navigation_sections import task_category
        from tests.fixture_support import make_account_environment
        from ok.gui.tasks.TaskCard import TaskCard
        from PySide6.QtWidgets import QApplication

        self.assertIn(['src.task.MultiAccountWeeklyGardenTask', 'MultiAccountWeeklyGardenTask'],
                      config['onetime_tasks'])
        task = object.__new__(MultiAccountWeeklyGardenTask)
        self.assertEqual(task_category(task), '每周任务')
        app = QApplication.instance() or QApplication([])

        with __import__('tempfile').TemporaryDirectory() as temp:
            env = make_account_environment(temp)
            module = __import__('src.task.MultiAccountWeeklyGardenTask', fromlist=['MultiAccountWeeklyGardenTask'])
            executor = SimpleNamespace(scene=None, text_fix={},
                                        global_config=SimpleNamespace(get_config=lambda _key: {}))
            with patch('src.task.MultiAccountDailyTask.get_default_service', return_value=env.integrity), \
                    patch('src.task.MultiAccountDailyTask.get_default_repository', return_value=env.repository), \
                    patch.object(og, 'app', SimpleNamespace(tr=str)), \
                    patch.object(og, 'executor', SimpleNamespace(waiting_for_task=lambda _task: '')):
                real = module.MultiAccountWeeklyGardenTask(executor=executor, app=None)
                real.config = MemoryConfig(real.default_config)
                real.config[CURRENT_SEQUENCE] = 'S1'
                real.running = False
                real.start_time = 0
                real.info = {}
                real.instructions = 'weekly help should remain hidden like the daily multi-account card'
                card = TaskCard(real, True)
                try:
                    self.assertIsNotNone(card.start_button)
                    self.assertIsNotNone(card.stop_button)
                    self.assertFalse(card.instructions_button.isVisible())
                    self.assertIn('当前序列', card.config_widget_by_key)
                    self.assertIn('当前执行账号', card.config_widget_by_key)
                    self.assertIn('本次最多处理账号数', card.config_widget_by_key)
                    self.assertIn('本次时间预算（分钟）', card.config_widget_by_key)
                finally:
                    card.close()
                daily_multi = MultiAccountDailyTask(executor=executor, app=None)
                daily_multi.config = MemoryConfig(daily_multi.default_config)
                daily_multi.running = False
                daily_multi.start_time = 0
                daily_multi.info = {}
                daily_multi.instructions = 'daily multi-account instructions'
                daily_multi_card = TaskCard(daily_multi, True)
                try:
                    self.assertIsNotNone(daily_multi_card.start_button)
                    self.assertIsNotNone(daily_multi_card.stop_button)
                    self.assertFalse(daily_multi_card.instructions_button.isVisible())
                    self.assertEqual(len(card.all_buttons), len(daily_multi_card.all_buttons))
                finally:
                    daily_multi_card.close()
                daily_multi_config_task = MultiAccountDailyTask(executor=executor, app=None)
                daily_multi_config_task.config = MemoryConfig(daily_multi_config_task.default_config)
                daily_multi_config_task.config[CURRENT_SEQUENCE] = 'S1'
                self.assertEqual(daily_multi_config_task.get_readonly_config_value('当前序列账号'),
                                 ['A1', 'A3', 'A4'])
                daily_multi_config_task.config[CURRENT_SEQUENCE] = '序列1'
                self.assertEqual(daily_multi_config_task.get_readonly_config_value('当前序列账号'),
                                 ['该序列暂无账号'])
                from src.task.DailyTask import DailyTask
                daily = DailyTask(executor=executor, app=None)
                daily.config = MemoryConfig(daily.default_config)
                daily.running = False
                daily.start_time = 0
                daily.info = {}
                daily_card = TaskCard(daily, True)
                try:
                    self.assertIsNotNone(daily_card.start_button)
                    self.assertIsNotNone(daily_card.stop_button)
                finally:
                    daily_card.close()
        app.processEvents()


if __name__ == '__main__':
    unittest.main()
