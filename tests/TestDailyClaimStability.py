import unittest
from types import MethodType
from unittest.mock import Mock
from ok import TaskDisabledException
from src.task.DailyTask import DailyTask, DailyActivityIncomplete


class TestDailyClaimStability(unittest.TestCase):
    def task(self):
        task = Mock(spec=DailyTask)
        task._restore_daily_claim_page = MethodType(DailyTask._restore_daily_claim_page, task)
        task._daily_reward_overlay.return_value = None
        task._daily_objective_claim_buttons.return_value = []
        return task

    def test_transient_missing_frame_recovers_before_scanning_buttons(self):
        task = self.task()
        states = iter([False, True, False, True, True, True])
        task._daily_page_ready.side_effect = lambda _: next(states, True)
        DailyTask._claim_daily_objectives(task)
        self.assertEqual(task._daily_objective_claim_buttons.call_count, 3)
        task.click.assert_not_called()

    def test_persistent_unknown_page_is_bounded_and_never_claims(self):
        task = self.task()
        task._daily_page_ready.return_value = False
        with self.assertRaisesRegex(DailyActivityIncomplete, '未稳定恢复'):
            DailyTask._claim_daily_objectives(task)
        self.assertLessEqual(task.next_frame.call_count, 16)
        task.click.assert_not_called()
        task._daily_objective_claim_buttons.assert_not_called()

    def test_cancellation_is_not_converted_to_page_failure(self):
        task = self.task()
        task.next_frame.side_effect = TaskDisabledException()
        with self.assertRaises(TaskDisabledException):
            DailyTask._claim_daily_objectives(task)
        task.click.assert_not_called()
