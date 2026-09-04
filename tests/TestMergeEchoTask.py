import unittest
from datetime import datetime
from unittest.mock import Mock, call, patch

from config import key_config_option
from src.Labels import Labels
from src.task.DailyTask import (
    ADDITIONAL_TASKS,
    AUTO_FARM_NIGHTMARE_NEST,
    MERGE_ECHO_ON_SUNDAY,
    DailyTask,
    weekly_garden_check_due,
)
from src.task.FarmEchoTask import FarmEchoTask
from src.task.MergeEchoTask import FULL_BATCH_PATTERN, MergeEchoTask


class TestMergeEchoTask(unittest.TestCase):

    def test_ungrouped_tasks_and_global_bag_hotkey_metadata(self):
        executor = Mock()
        executor.scene = None
        executor.global_config.get_config.return_value = {}
        app = Mock()

        merge_task = MergeEchoTask(executor, app)
        farm_task = FarmEchoTask(executor, app)

        self.assertIsNone(merge_task.group_name)
        self.assertIsNone(farm_task.group_name)
        self.assertNotIn("Bag Key", merge_task.default_config)
        self.assertEqual(key_config_option.default_config["Bag Key"], "b")
        self.assertIn("Bag Key", key_config_option.config_description)

    def setUp(self):
        self.task = MergeEchoTask.__new__(MergeEchoTask)
        self.task.key_config = {"Bag Key": "v"}
        self.task.ensure_main = Mock()
        self.task.send_key = Mock()
        self.task.in_team_and_world = Mock(return_value=False)
        self.task.wait_until = Mock(
            side_effect=lambda predicate, **kwargs: predicate()
        )
        self.task.sleep = Mock()
        self.task.wait_click_skip_dialog_confirm = Mock(return_value=True)
        self.task.wait_click_feature = Mock(return_value=True)
        self.task.click_relative = Mock()
        self.task.ocr = Mock(return_value=[])
        self.task.log_info = Mock()
        self.task.log_error = Mock()
        self.task.notify_if_not_enough = True

    def test_stops_when_selected_echoes_do_not_fill_a_batch(self):
        self.task.run()

        self.assertEqual(self.task.ensure_main.call_count, 2)
        self.task.send_key.assert_called_once_with("v")
        predicate = self.task.wait_until.call_args.args[0]
        self.assertTrue(predicate())
        self.assertEqual(
            self.task.wait_until.call_args.kwargs,
            {"time_out": 5, "raise_if_not_found": False},
        )
        self.task.ocr.assert_called_once_with(
            0.670,
            0.660,
            0.895,
            0.958,
            match=FULL_BATCH_PATTERN,
        )
        self.task.wait_click_feature.assert_called_once_with(
            Labels.echo_select_all,
            horizontal_variance=0.3,
            after_sleep=1,
        )
        self.assertEqual(
            self.task.click_relative.call_args_list,
            [
                call(0.602, 0.124, after_sleep=0.5, hcenter=True),
                call(0.520, 0.904, after_sleep=2, hcenter=True),
                call(0.041, 0.918, after_sleep=1),
                call(0.826, 0.840, after_sleep=0.5),
                call(0.717, 0.204, after_sleep=0.5),
                call(0.041, 0.918, after_sleep=0.5),
                call(0.310, 0.915, after_sleep=0.5),
            ],
        )

    def test_merges_full_batches_until_less_than_100_remain(self):
        self.task.wait_click_skip_dialog_confirm.side_effect = [
            True,
            False,
        ]
        self.task.ocr.side_effect = [[object()], []]

        self.task.run()

        self.assertEqual(
            self.task.wait_click_skip_dialog_confirm.call_args_list,
            [call(), call()],
        )
        self.assertEqual(self.task.sleep.call_args_list, [call(1), call(2), call(3)])
        self.assertEqual(
            self.task.wait_click_feature.call_args_list,
            [
                call(Labels.echo_select_all, horizontal_variance=0.3, after_sleep=1),
                call(Labels.echo_select_all, horizontal_variance=0.3, after_sleep=1),
            ],
        )
        self.assertEqual(
            self.task.click_relative.call_args_list[-4:],
            [
                call(0.310, 0.915, after_sleep=0.5),
                call(0.782, 0.910),
                call(0.496, 0.972, after_sleep=1, hcenter=True),
                call(0.310, 0.915, after_sleep=0.5),
            ],
        )
        self.assertEqual(self.task.ocr.call_count, 2)
        self.assertEqual(self.task.ensure_main.call_count, 2)

    def test_alerts_and_stops_when_bag_hotkey_fails(self):
        self.task.wait_until = Mock(return_value=False)

        self.task.run()

        self.task.log_error.assert_called_once_with(
            "can not open bag with hotkey v",
            notify=True,
        )
        self.task.sleep.assert_not_called()
        self.task.wait_click_skip_dialog_confirm.assert_not_called()
        self.task.click_relative.assert_not_called()
        self.assertEqual(self.task.ensure_main.call_count, 1)

    def test_alerts_and_returns_to_main_when_1000_echo_dialog_is_absent(self):
        self.task.wait_click_skip_dialog_confirm.return_value = False

        self.task.run()

        self.task.log_error.assert_called_once_with(
            "Must have 1000 discarded Echo to Run",
            notify=True,
        )
        self.assertEqual(self.task.ensure_main.call_count, 2)
        self.task.click_relative.assert_not_called()
        self.task.ocr.assert_not_called()

    def test_quietly_returns_when_not_enough_notification_is_disabled(self):
        self.task.wait_click_skip_dialog_confirm.return_value = False
        self.task.notify_if_not_enough = False

        self.task.run()

        self.task.log_error.assert_not_called()
        self.assertEqual(self.task.ensure_main.call_count, 2)
        self.task.click_relative.assert_not_called()
        self.task.ocr.assert_not_called()


class TestDailyMergeEchoTask(unittest.TestCase):

    def test_weekly_garden_retries_after_selected_day_until_recorded(self):
        monday = datetime(2026, 8, 31, 12, 0, 0)
        wednesday = datetime(2026, 9, 2, 12, 0, 0)

        self.assertTrue(weekly_garden_check_due('Monday', None, monday))
        self.assertTrue(weekly_garden_check_due('Monday', None, wednesday))
        self.assertFalse(weekly_garden_check_due(
            'Monday', '2026-09-01 20:00:00', wednesday))
        self.assertTrue(weekly_garden_check_due(
            'Monday', '2026-08-30 20:00:00', wednesday))

    def test_weekly_garden_without_selected_day_starts_on_sunday(self):
        saturday = datetime(2026, 9, 5, 12, 0, 0)
        sunday = datetime(2026, 9, 6, 12, 0, 0)

        self.assertFalse(weekly_garden_check_due('无', None, saturday))
        self.assertTrue(weekly_garden_check_due('无', None, sunday))

    def test_weekly_garden_current_week_record_skips_opening_page(self):
        daily_task = DailyTask.__new__(DailyTask)
        daily_task._profile_get = Mock(return_value='Monday')
        daily_task.get_last_completed = Mock(return_value='2026-09-01 20:00:00')
        daily_task.get_task_by_class = Mock()
        daily_task.info_set = Mock()
        daily_task.log_info = Mock()

        with patch('src.task.DailyTask.datetime') as fake_datetime:
            fake_datetime.now.return_value = datetime(2026, 9, 2, 12, 0, 0)
            fake_datetime.fromisoformat.side_effect = datetime.fromisoformat
            daily_task.check_weekly_garden()

        daily_task.get_task_by_class.assert_not_called()

    def test_weekly_garden_late_check_records_confirmed_completion(self):
        daily_task = DailyTask.__new__(DailyTask)
        daily_task._verified_profile_id = 'profile-a3'
        daily_task._profile_get = Mock(return_value='Monday')
        daily_task.get_last_completed = Mock(return_value=None)
        garden_task = Mock()
        garden_task.is_weekly_garden_completed.return_value = True
        daily_task.get_task_by_class = Mock(return_value=garden_task)
        daily_task.record_last_completed = Mock()
        daily_task.info_set = Mock()
        daily_task.log_info = Mock()

        with patch('src.task.DailyTask.datetime') as fake_datetime:
            fake_datetime.now.return_value = datetime(2026, 9, 2, 12, 0, 0)
            daily_task.check_weekly_garden()

        garden_task.open_garden_weekly_page.assert_called_once_with()
        daily_task.record_last_completed.assert_called_once_with(
            'Weekly Garden', profile_id='profile-a3')

    def test_weekly_garden_failure_keeps_the_account_due_for_next_run(self):
        daily_task = DailyTask.__new__(DailyTask)
        daily_task._verified_profile_id = 'profile-a3'
        daily_task._profile_get = Mock(return_value='Monday')
        daily_task.get_last_completed = Mock(return_value=None)
        garden_task = Mock()
        garden_task.is_weekly_garden_completed.return_value = False
        daily_task.get_task_by_class = Mock(return_value=garden_task)
        daily_task.run_task_by_class = Mock(side_effect=RuntimeError('failed'))
        daily_task.record_last_completed = Mock()
        daily_task.info_set = Mock()
        daily_task.log_info = Mock()
        daily_task.log_error = Mock()
        daily_task.screenshot = Mock()
        daily_task.ensure_main = Mock()

        with patch('src.task.DailyTask.datetime') as fake_datetime:
            fake_datetime.now.return_value = datetime(2026, 9, 2, 12, 0, 0)
            daily_task.check_weekly_garden()

        daily_task.record_last_completed.assert_not_called()
        self.assertTrue(weekly_garden_check_due(
            'Monday', None, datetime(2026, 9, 3, 12, 0, 0)))

    def test_daily_uses_current_weekly_and_nightmare_metadata(self):
        executor = Mock()
        executor.scene = None
        executor.global_config.get_config.return_value = {}

        daily_task = DailyTask(executor, Mock())

        self.assertNotIn(ADDITIONAL_TASKS, daily_task.default_config)
        self.assertFalse(daily_task.default_config[AUTO_FARM_NIGHTMARE_NEST])
        self.assertFalse(daily_task.default_config[MERGE_ECHO_ON_SUNDAY])
        self.assertIn('Nightmare Which to Farm', daily_task.default_config)
        self.assertIn('Tacet Discord Nests to Farm', daily_task.default_config)

    def test_daily_runs_selected_merge_echo_on_sunday(self):
        daily_task = DailyTask.__new__(DailyTask)
        daily_task.config = {MERGE_ECHO_ON_SUNDAY: True}
        daily_task.check_weekly_garden = Mock()
        daily_task.check_discarded_echo = Mock()

        with patch('src.task.DailyTask.datetime') as fake_datetime:
            fake_datetime.now.return_value.weekday.return_value = 6
            daily_task.run_weekly_tasks()

        daily_task.check_weekly_garden.assert_called_once_with()
        daily_task.check_discarded_echo.assert_called_once_with()

    def test_daily_skips_merge_echo_when_option_is_disabled(self):
        daily_task = DailyTask.__new__(DailyTask)
        daily_task.config = {MERGE_ECHO_ON_SUNDAY: False}
        daily_task.check_weekly_garden = Mock()
        daily_task.check_discarded_echo = Mock()

        with patch('src.task.DailyTask.datetime') as fake_datetime:
            fake_datetime.now.return_value.weekday.return_value = 6
            daily_task.run_weekly_tasks()

        daily_task.check_weekly_garden.assert_called_once_with()
        daily_task.check_discarded_echo.assert_not_called()

    def test_daily_suppresses_and_restores_not_enough_echo_notification(self):
        daily_task = DailyTask.__new__(DailyTask)
        daily_task.info_set = Mock()
        daily_task.log_info = Mock()
        daily_task.record_last_completed = Mock()
        merge_echo_task = Mock()
        merge_echo_task.notify_if_not_enough = True
        daily_task.get_task_by_class = Mock(return_value=merge_echo_task)

        def assert_notification_suppressed(task_class):
            self.assertIs(task_class, MergeEchoTask)
            self.assertFalse(merge_echo_task.notify_if_not_enough)

        daily_task.run_task_by_class = Mock(side_effect=assert_notification_suppressed)

        daily_task.check_discarded_echo()

        daily_task.run_task_by_class.assert_called_once_with(MergeEchoTask)
        self.assertTrue(merge_echo_task.notify_if_not_enough)

    def test_daily_rejects_nightmare_without_selection(self):
        daily_task = DailyTask.__new__(DailyTask)
        daily_task.config = {
            AUTO_FARM_NIGHTMARE_NEST: True,
            'Nightmare Which to Farm': [],
        }
        daily_task.tr = lambda message: message

        message = 'Auto Farm all Nightmare Nest requires at least one "Which to Farm" option.'
        with self.assertRaisesRegex(Exception, message):
            daily_task.validate_daily_tasks()

    def test_daily_accepts_valid_nightmare_config(self):
        daily_task = DailyTask.__new__(DailyTask)
        daily_task.config = {
            AUTO_FARM_NIGHTMARE_NEST: True,
            'Nightmare Which to Farm': ['Nightmare Purification'],
        }

        self.assertTrue(daily_task.validate_daily_tasks())

    def test_daily_stops_before_initialization_when_additional_config_is_invalid(self):
        daily_task = DailyTask.__new__(DailyTask)
        daily_task.validate_daily_tasks = Mock(side_effect=Exception('invalid daily task config'))
        daily_task.ensure_main = Mock()

        with self.assertRaisesRegex(Exception, 'invalid daily task config'):
            daily_task.run()

        daily_task.ensure_main.assert_not_called()


if __name__ == "__main__":
    unittest.main()
