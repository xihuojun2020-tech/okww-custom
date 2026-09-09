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
    def test_monday_catchup_and_independent_sunday(self):
        target = WEEKLY_BOSSES[0].key
        for day in range(7, 13):
            now = datetime(2026, 9, day, 12)
            self.assertTrue(weekly_check_due(target, None, now))
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
        self.assertTrue(weekly_check_due(WEEKLY_BOSSES[0].key, '2026-09-09T14:00:00+08:00',
                                        datetime(2026, 9, 9, 12)))

    def daily(self, result=WeeklyBossResult(3, 3, 0)):
        task = object.__new__(DailyTask)
        task.integrity_service = Mock()
        task._active_profile_id = Mock(return_value='uuid-a1')
        task._profile_get = Mock(return_value=WEEKLY_BOSSES[0].key)
        task.get_last_completed = Mock(return_value=None)
        task._publish_daily_stage = Mock()
        task.get_task_by_class = Mock(return_value=SimpleNamespace(run_for_target=Mock(return_value=result)))
        task.info_set = Mock()
        task.log_error = Mock()
        task.screenshot = Mock()
        task.ensure_main = Mock()
        return task

    def test_zero_and_success_record_explicit_account(self):
        for result in (WeeklyBossResult(0, 0, 0), WeeklyBossResult(3, 3, 0)):
            task = self.daily(result)
            task.check_weekly_boss()
            self.assertEqual(task.integrity_service.record_completion.call_args.args[0], 'uuid-a1')
            self.assertEqual(task.get_task_by_class.return_value.run_for_target.call_args.args, (WEEKLY_BOSSES[0].key,))

    def test_partial_and_failure_are_pending_without_completion(self):
        task = self.daily(WeeklyBossResult(3, 1, 2))
        task.check_weekly_boss()
        task.integrity_service.record_completion.assert_not_called()
        task.ensure_main.assert_called_once()
        task = self.daily()
        task.get_task_by_class.return_value.run_for_target.side_effect = RuntimeError('体力不足')
        task.check_weekly_boss()
        task.integrity_service.record_completion.assert_not_called()

    def test_stop_and_unrecoverable_world_propagate(self):
        task = self.daily()
        task.get_task_by_class.return_value.run_for_target.side_effect = TaskDisabledException()
        with self.assertRaises(TaskDisabledException):
            task.check_weekly_boss()
        task.ensure_main.assert_not_called()
        task = self.daily(None)
        task.ensure_main.side_effect = RuntimeError('world unavailable')
        with self.assertRaisesRegex(RuntimeError, 'world unavailable'):
            task.check_weekly_boss()

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
                                                      else False if 'Nightmare' in key else default)
        reads = iter([(0, False), (180, True)])
        task.open_daily = lambda: (events.append('read'), next(reads))[1]
        task.check_weekly_boss = lambda: events.append('weekly') or True
        def farm(**kwargs):
            events.append('farm')
            self.assertTrue(kwargs['activity_ready'])
            self.assertEqual(kwargs['used_stamina'], 180)
            raise RuntimeError('test reached refreshed farming')
        task.get_task_by_class = Mock(return_value=SimpleNamespace(farm_tacet=farm))
        with patch('src.task.DailyTask.require_account_runtime_for_task'), \
                patch('src.task.DailyTask.WWOneTimeTask.run'), patch.object(DailyTask, 'logged_in', False):
            with self.assertRaisesRegex(RuntimeError, 'test reached refreshed farming'):
                task._run_daily_inner()
        self.assertEqual(events, ['read', 'weekly', 'read', 'farm'])

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
        self.assertEqual(len(field.options), 11)
        for stored, shown in zip(field.options, field.option_labels):
            self.assertEqual(restore_account_value(shown), stored)


if __name__ == '__main__':
    unittest.main()
