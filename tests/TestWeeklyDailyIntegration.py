import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ok import TaskDisabledException
from src.task.DailyTask import DailyTask
from src.task.MultiAccountDailyTask import MultiAccountDailyTask
from src.task.weekly_boss import (WEEKLY_TARGET, WEEKLY_MONDAY, WEEKLY_SUNDAY,
                                WEEKLY_BOSSES, WeeklyBossResult, weekly_check_window, weekly_check_due)


class TestWeeklyDailyIntegration(unittest.TestCase):
    def setUp(self):
        # Tests that exercise the automatic weekly entry need an eligible game day.
        # Explicit boundary cases below still supply their own dates.
        class MondayClock(datetime):
            @classmethod
            def now(cls, tz=None):
                from datetime import timezone, timedelta
                value = datetime(2026, 10, 5, 12, tzinfo=timezone(timedelta(hours=8)))
                return value.astimezone(tz) if tz else value.replace(tzinfo=None)
        clock = patch('src.task.weekly_boss.datetime', MondayClock)
        clock.start()
        self.addCleanup(clock.stop)

    class SharedGardenState:
        def __init__(self):
            self.completions = {}
            self.progress = {}
            self.fail_write = False

        def get_completion(self, profile_id, key):
            return self.completions.get((profile_id, key))

        def record_completion(self, profile_id, key, timestamp):
            if self.fail_write:
                from src.config_integrity import ConfigWriteBlocked
                raise ConfigWriteBlocked('write blocked')
            self.completions[(profile_id, key)] = timestamp

        def set_progress(self, key, value):
            self.progress[key] = value

    @staticmethod
    def garden_daily(service, points=(6000, 6000), mode='daily'):
        from src.task.GardenTask import GardenTask
        daily = object.__new__(DailyTask)
        daily.integrity_service = service
        daily._verified_profile_id = 'profile-a1'
        daily._profile_get = lambda key, default=None: mode if key == 'Garden Execution Mode' else default
        daily._readonly_active_profile_id = lambda: 'profile-a1'
        daily.get_last_completed = lambda key: service.get_completion('profile-a1', key)
        daily.sleep = Mock()
        daily._refresh_weekly_garden_consumers = Mock()
        garden = object.__new__(GardenTask)
        garden.last_result = None
        garden.open_garden_weekly_page = Mock()
        garden.read_weekly_garden_points = Mock(side_effect=list(points))
        garden.record_verified_result = Mock(return_value='weekly_garden:profile-a1:week')
        daily.get_task_by_class = Mock(return_value=garden)
        def run_garden(_task_class):
            from src.task.weekly_garden import GardenRunResult, garden_week_key
            garden.last_result = GardenRunResult('completed', garden_week_key(), 6000, True,
                                                  'weekly_garden:profile-a1:week')
        daily.run_task_by_class = Mock(side_effect=run_garden)
        return daily, garden

    def test_daily_write_is_shared_with_weekly_sequence_and_daily_skip(self):
        from src.task.weekly_garden import GARDEN_INDEPENDENT
        service = self.SharedGardenState()
        daily, garden = self.garden_daily(service, mode=GARDEN_INDEPENDENT)
        result = daily.run_weekly_garden_only()
        self.assertTrue(result.done)
        self.assertIn(('profile-a1', 'Weekly Garden'), service.completions)
        self.assertNotIn(('profile-a1', 'Daily Task'), service.completions)

        weekly = object.__new__(__import__(
            'src.task.MultiAccountWeeklyGardenTask', fromlist=['MultiAccountWeeklyGardenTask']
        ).MultiAccountWeeklyGardenTask)
        weekly.integrity_service = service
        weekly._profile_id_for = lambda account: {'A1': 'profile-a1', 'A3': 'profile-a1'}[account]
        weekly._load_profiles = lambda: {
            'A1': {'task_config': {'Garden Execution Mode': GARDEN_INDEPENDENT}},
            'A3': {'task_config': {'Garden Execution Mode': GARDEN_INDEPENDENT}},
        }
        weekly.get_sequence_accounts = lambda: ['A3']  # same profile is shared across sequences
        self.assertTrue(weekly._garden_done('A3'))

        daily._profile_get = lambda key, default=None: (
            'daily' if key == 'Garden Execution Mode' else 'Monday')
        daily.info_set = Mock()
        daily.log_info = Mock()
        daily.check_weekly_garden()
        self.assertEqual(daily.get_task_by_class.call_count, 1)
        self.assertEqual(garden.open_garden_weekly_page.call_count, 1)
        daily.run_task_by_class.assert_not_called()

    def test_weekly_entry_writes_shared_completion_and_daily_entry_reads_it(self):
        from src.task.weekly_garden import GARDEN_INDEPENDENT
        from src.task.MultiAccountWeeklyGardenTask import MultiAccountWeeklyGardenTask
        service = self.SharedGardenState()
        daily, garden = self.garden_daily(service, mode=GARDEN_INDEPENDENT)
        weekly = object.__new__(MultiAccountWeeklyGardenTask)
        weekly.integrity_service = service
        weekly._garden_week_key = 'week'
        weekly._garden_entered = set()
        weekly._account_attempts = {}
        weekly._retry_phase = False
        weekly._load_profiles = lambda: {
            'A1': {'task_config': {'Garden Execution Mode': GARDEN_INDEPENDENT}},
        }
        weekly._profile_id_for = lambda _account: 'profile-a1'
        weekly._failure_key = lambda _account: 'profile-a1'
        weekly._require_daily_profile = Mock()
        weekly.get_task_by_class = Mock(return_value=daily)
        weekly._mark_done = Mock()
        weekly._save_today_progress = Mock()
        weekly._resolve_failure = Mock()
        weekly._refresh_garden_status = Mock()
        weekly.info_set = Mock()
        weekly.log_info = Mock()
        weekly.log_error = Mock()
        weekly.screenshot = Mock()
        weekly._check_progress_date = Mock()
        success, error = weekly._execute_account_task('A1')
        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertTrue(weekly._garden_done('A1'))
        self.assertNotIn(('profile-a1', 'Daily Task'), service.completions)
        daily._profile_get = lambda key, default=None: 'daily' if key == 'Garden Execution Mode' else 'Monday'
        daily.info_set = Mock()
        daily.log_info = Mock()
        daily.check_weekly_garden()
        self.assertEqual(garden.open_garden_weekly_page.call_count, 1)
        self.assertEqual(len(service.completions), 1)

    def test_multi_account_daily_uses_the_same_garden_completion_contract(self):
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask
        from src.task.MultiAccountWeeklyGardenTask import MultiAccountWeeklyGardenTask
        from src.task.weekly_garden import GARDEN_DAILY
        service = self.SharedGardenState()
        daily, _garden = self.garden_daily(service, mode=GARDEN_DAILY)
        multi = object.__new__(MultiAccountDailyTask)
        multi.integrity_service = service
        multi.info = {}
        multi.done_set = set()
        multi.failed_accounts = {}
        multi._account_attempts = {}
        multi._profile_id_for = lambda _account: 'profile-a1'
        multi._check_progress_date = Mock()
        multi._require_daily_profile = Mock()
        multi._daily_is_done = lambda _account: False
        multi.run_task_by_class = Mock(side_effect=lambda _task: daily.run_weekly_garden_only())
        multi.info_set = Mock()
        multi.log_info = Mock()
        multi.log_error = Mock()
        multi._mark_done = Mock()
        multi._save_today_progress = Mock()
        multi._resolve_failure = Mock()
        result, error = multi._run_daily_account('A1')
        self.assertTrue(result)
        self.assertIsNone(error)
        self.assertIn(('profile-a1', 'Weekly Garden'), service.completions)
        self.assertNotIn(('profile-a1', 'Daily Task'), service.completions)

        weekly = object.__new__(MultiAccountWeeklyGardenTask)
        weekly.integrity_service = service
        weekly._profile_id_for = lambda _account: 'profile-a1'
        weekly._load_profiles = lambda: {
            'A1': {'task_config': {'Garden Execution Mode': GARDEN_DAILY}},
        }
        self.assertTrue(weekly._garden_done('A1'))

    def test_shared_completion_refreshes_weekly_card_state_and_emits_task_change(self):
        from ok import og
        from src.task.MultiAccountWeeklyGardenTask import MultiAccountWeeklyGardenTask
        weekly = object.__new__(MultiAccountWeeklyGardenTask)
        weekly._refresh_garden_status = Mock()
        executor = SimpleNamespace(onetime_tasks=[weekly])
        emit = Mock()
        with patch.object(og, 'executor', executor), \
                patch('ok.gui.Communicate.communicate.task', SimpleNamespace(emit=emit)):
            DailyTask._refresh_weekly_garden_consumers(object.__new__(DailyTask))
        weekly._refresh_garden_status.assert_called_once_with()
        emit.assert_called_once_with(weekly)

    def test_garden_write_failure_and_precommit_week_rollover_do_not_mark_done(self):
        from src.task.weekly_garden import GARDEN_INDEPENDENT
        from src.config_integrity import ConfigWriteBlocked
        service = self.SharedGardenState()
        service.fail_write = True
        daily, _garden = self.garden_daily(service, mode=GARDEN_INDEPENDENT)
        with self.assertRaises(ConfigWriteBlocked):
            daily.run_weekly_garden_only()
        self.assertFalse(service.completions)

        service.fail_write = False
        service.completions.clear()
        daily, garden = self.garden_daily(service, points=(0, 0, 1200, 1200),
                                          mode=GARDEN_INDEPENDENT)
        from src.task.weekly_garden import GardenRunResult
        daily.run_task_by_class = Mock(side_effect=lambda _task: setattr(
            garden, 'last_result', GardenRunResult('completed', 'week-one', 6000, True)))
        weeks = iter(['week-one', 'week-one', 'week-two'])
        with patch('src.task.weekly_garden.garden_week_key', side_effect=lambda: next(weeks)):
            with self.assertRaisesRegex(RuntimeError, '周重置'):
                daily.run_weekly_garden_only()
        self.assertFalse(service.completions)

    def test_weekly_garden_finished_exception_propagates_without_recovery(self):
        from ok.task.exceptions import FinishedException
        task = object.__new__(DailyTask)
        task._profile_get = lambda key, default=None: 'daily' if key == 'Garden Execution Mode' else 'Monday'
        task.get_last_completed = Mock(return_value=None)
        task.info_set = Mock()
        task.log_info = Mock()
        task.run_weekly_garden_only = Mock(side_effect=FinishedException())
        task.log_error = Mock()
        task.screenshot = Mock()
        task.ensure_main = Mock()
        with patch('src.task.DailyTask.weekly_garden_check_due', return_value=True):
            with self.assertRaises(FinishedException):
                task.check_weekly_garden()
        task.log_error.assert_not_called()
        task.screenshot.assert_not_called()
        task.ensure_main.assert_not_called()

    def test_daily_garden_failure_is_visible_as_pending_check(self):
        task = object.__new__(DailyTask)
        task._profile_get = lambda key, default=None: 'daily' if key == 'Garden Execution Mode' else 'Monday'
        task.get_last_completed = Mock(return_value=None)
        task.info_set = Mock()
        task.log_info = Mock()
        task.run_weekly_garden_only = Mock(side_effect=RuntimeError('积分未确认'))
        task.log_error = Mock()
        task.screenshot = Mock()
        task.ensure_main = Mock()
        with patch('src.task.DailyTask.weekly_garden_check_due', return_value=True):
            task.check_weekly_garden()
        task.info_set.assert_any_call('每周乐园检查结果', '待补检：积分未确认')
        task.log_error.assert_called_once()

    def test_low_stamina_is_pending_without_error_or_completion(self):
        task = self.daily(WeeklyBossResult(3, 2, 1, reason='当前体力不足'))
        task.check_weekly_boss()
        task.integrity_service.record_completion.assert_not_called()
        task.log_error.assert_not_called()
        task.screenshot.assert_not_called()
        self.assertIn('体力不足', task.info_set.call_args.args[1])

    def test_monday_catchup_and_independent_sunday(self):
        target = WEEKLY_BOSSES[0].key
        for day in range(7, 13):
            now = datetime(2026, 9, day, 12)
            self.assertEqual(day == 7, weekly_check_due(target, None, now))
            self.assertFalse(weekly_check_due(target, '2026-09-07T12:00:00+08:00', now))
        sunday = datetime(2026, 9, 13, 12)
        self.assertTrue(weekly_check_due(target, '2026-09-07T12:00:00+08:00', sunday))
        self.assertFalse(weekly_check_due(target, '2026-09-13T10:00:00+08:00', sunday))
        self.assertTrue(weekly_check_due(target, '2026-09-13T10:00:00+08:00', datetime(2026, 9, 14, 12)))

    def test_refresh_boundary_and_timezone(self):
        before = datetime.fromisoformat('2026-09-14T03:59:59+08:00')
        after = datetime.fromisoformat('2026-09-14T04:00:00+08:00')
        self.assertEqual(weekly_check_window(before)[1], WEEKLY_SUNDAY)
        self.assertEqual(weekly_check_window(after)[1], WEEKLY_MONDAY)
        self.assertEqual(weekly_check_window(after), weekly_check_window(datetime.fromisoformat('2026-09-13T20:00:00+00:00')))

    def test_disabled_invalid_and_corrupt_stamp(self):
        self.assertFalse(weekly_check_due('无', None))
        with self.assertRaises(ValueError):
            weekly_check_due('invalid', None)
        self.assertTrue(weekly_check_due(WEEKLY_BOSSES[0].key, 'broken'))
        self.assertFalse(weekly_check_due(WEEKLY_BOSSES[0].key, '2026-09-09T14:00:00+08:00',
                                        datetime(2026, 9, 9, 12)))

    def daily(self, result=WeeklyBossResult(3, 3, 0)):
        task = object.__new__(DailyTask)
        task.integrity_service = Mock()
        task._active_profile_id = Mock(return_value='uuid-a1')
        task._profile_get = Mock(side_effect=lambda key, default=None:
                                WEEKLY_BOSSES[0].key if key == WEEKLY_TARGET else default)
        task.get_last_completed = Mock(return_value=None)
        task._publish_daily_stage = Mock()
        task.get_task_by_class = Mock(return_value=SimpleNamespace(run_for_plan=Mock(return_value=result)))
        task.info_set = Mock()
        task.log_error = Mock()
        task.log_info = Mock()
        task.screenshot = Mock()
        task.ensure_main = Mock()
        return task

    def test_zero_and_success_record_explicit_account(self):
        for result in (WeeklyBossResult(0, 0, 0), WeeklyBossResult(3, 3, 0)):
            task = self.daily(result)
            task.check_weekly_boss()
            self.assertEqual(task.integrity_service.record_completion.call_args.args[0], 'uuid-a1')
            args = task.get_task_by_class.return_value.run_for_plan.call_args.args
            self.assertEqual(args[0], 'uuid-a1')
            self.assertEqual(args[1]()[WEEKLY_TARGET], WEEKLY_BOSSES[0].key)
            self.assertIs(args[2], task.integrity_service)

    def test_partial_and_failure_are_pending_without_completion(self):
        task = self.daily(WeeklyBossResult(3, 1, 2))
        task.check_weekly_boss()
        task.integrity_service.record_completion.assert_not_called()
        task.ensure_main.assert_called_once()
        task = self.daily()
        task.get_task_by_class.return_value.run_for_plan.side_effect = RuntimeError('体力不足')
        task.check_weekly_boss()
        task.integrity_service.record_completion.assert_not_called()

    def test_stop_and_unrecoverable_world_propagate(self):
        task = self.daily()
        task.get_task_by_class.return_value.run_for_plan.side_effect = TaskDisabledException()
        with self.assertRaises(TaskDisabledException):
            task.check_weekly_boss()
        task.ensure_main.assert_not_called()
        task = self.daily(None)
        task.ensure_main.side_effect = RuntimeError('world unavailable')
        with self.assertRaisesRegex(RuntimeError, 'world unavailable'):
            task.check_weekly_boss()

    def test_repeated_check_preserves_pending_in_same_run(self):
        task=self.daily(None)
        task.check_weekly_boss()
        count=task.info_set.call_count
        task.check_weekly_boss()
        self.assertEqual(task.info_set.call_count,count)
        self.assertIn('待补检',task.info_set.call_args.args[1])
        task.get_task_by_class.return_value.run_for_plan.assert_called_once()
        task._weekly_checked_run=None  # next daily run gets its own attempt
        task.check_weekly_boss()
        self.assertEqual(task.get_task_by_class.return_value.run_for_plan.call_count,2)

    def test_cross_refresh_does_not_write_new_week_completion(self):
        task = self.daily()
        windows = [(datetime(2026, 9, 7).date(), WEEKLY_SUNDAY),
                   (datetime(2026, 9, 14).date(), WEEKLY_MONDAY)]
        with patch('src.task.DailyTask.weekly_check_window', side_effect=windows):
            task.check_weekly_boss()
        task.integrity_service.record_completion.assert_not_called()

    def test_finished_daily_is_selected_for_weekly_retry_once_per_run(self):
        task = object.__new__(MultiAccountDailyTask)
        task.integrity_service = Mock()
        task.done_set = {'a1', 'a3', 'a4'}
        task._weekly_attempted = set()
        task._profile_id_for = lambda name: name
        task._load_profiles = lambda: {
            'a1': {WEEKLY_TARGET: WEEKLY_BOSSES[0].key},
            'a3': {WEEKLY_TARGET: WEEKLY_BOSSES[1].key},
            'a4': {WEEKLY_TARGET: '无'},
        }
        task.integrity_service.get_completion.return_value = None
        self.assertFalse(task._is_done('a1'))
        self.assertFalse(task._is_done('a3'))
        self.assertTrue(task._is_done('a4'))
        task._weekly_attempted.add('a1')
        self.assertTrue(task._is_done('a1'))
        self.assertFalse(task._is_done('a3'))
        task._weekly_attempted.clear()
        self.assertFalse(task._is_done('a1'))

    def test_weekly_only_does_not_rerun_daily(self):
        task = object.__new__(MultiAccountDailyTask)
        task.info_set = Mock()
        task._require_daily_profile = Mock()
        task._daily_is_done = Mock(return_value=True)
        task.get_task_by_class = Mock()
        task.run_task_by_class = Mock()
        task.log_info = Mock()
        task._mark_done = Mock()
        task._save_today_progress = Mock()
        self.assertEqual(task._run_daily_account('a1'), (True, None))
        task.get_task_by_class.return_value.run_weekly_boss_only.assert_called_once()
        task.run_task_by_class.assert_not_called()

    def test_weekly_runs_before_farming_with_refreshed_activity(self):
        task = object.__new__(DailyTask)
        events = []
        task.integrity_service = None
        task._runtime_overrides = {}
        task.support_tasks = ['Tacet Suppression', 'Forgery Challenge', 'Simulation Challenge']
        for name in ('_publish_daily_stage', '_ensure_run_account_confirmation', 'validate_daily_tasks',
                     'log_info', 'ensure_main', 'ensure_daily_profiles', '_sync_sequence_options'):
            setattr(task, name, Mock())
        task.get_active_profile_name = Mock(return_value='A1')
        task._readonly_profile_config = Mock(return_value={})
        task._profile_get = lambda key, default=None: ('Tacet Suppression' if key == 'Which to Farm'
                                                      else [] if key == 'Tacet Discord Nests to Farm' else False if 'Nightmare' in key and isinstance(default, bool) else default)
        task.get_last_completed = Mock(return_value=None)
        reads = iter([(0, False), (180, True), (180, True)])
        task.open_daily = lambda: (events.append('read'), next(reads))[1]
        task.check_weekly_boss = lambda: events.append('weekly') or True
        def farm(**kwargs):
            events.append('farm')
            self.assertFalse(kwargs['activity_ready'])
            self.assertEqual(kwargs['used_stamina'], 0)
            raise RuntimeError('test reached refreshed farming')
        task.get_task_by_class = Mock(return_value=SimpleNamespace(farm_tacet=farm))
        with patch('src.task.DailyTask.require_account_runtime_for_task'), \
                patch('src.task.DailyTask.WWOneTimeTask.run'), patch.object(DailyTask, 'logged_in', False):
            with self.assertRaisesRegex(RuntimeError, 'test reached refreshed farming'):
                task._run_daily_inner()
        self.assertEqual(events, ['read', 'weekly', 'farm'])

    def test_target_wrapper_preserves_standalone_config_and_restores_state(self):
        from src.task.WeeklyBossTask import WeeklyBossTask
        task = object.__new__(WeeklyBossTask)
        task.skip_combat_check = False
        task._release_movement = Mock()
        task.run_weekly = Mock(return_value=WeeklyBossResult(0, 0, 0))
        with patch.object(WeeklyBossTask, 'width', 1920), patch.object(WeeklyBossTask, 'height', 1080), \
                patch.object(WeeklyBossTask, 'game_lang', 'zh_CN'):
            for boss in WEEKLY_BOSSES[:2]:
                task.run_for_target(boss.key)
                task.run_weekly.assert_called_with(boss.key)
                self.assertFalse(task.skip_combat_check)

    def test_config_option_roundtrip(self):
        from src.account_field_metadata import account_field_metadata, restore_account_value
        field = account_field_metadata({WEEKLY_TARGET: '无'})[0]
        self.assertEqual(len(field.options), 13)
        for stored, shown in zip(field.options, field.option_labels):
            self.assertEqual(restore_account_value(shown), stored)


if __name__ == '__main__':
    unittest.main()
