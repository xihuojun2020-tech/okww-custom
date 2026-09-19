import unittest
from types import SimpleNamespace, MethodType
from unittest.mock import Mock, patch
import numpy as np

from src.task.DailyTask import (
    DailyActivityDetectionError,
    DailyActivityIncomplete,
    DailyTask,
)


class TestDailyActivityFlow(unittest.TestCase):
    def test_daily_points_ocr_miss_is_unknown_instead_of_zero(self):
        class FakeTask:
            def __init__(self):
                self.frames = 0
                self.info = {}

            def ocr(self, *_args, **_kwargs):
                return []

            def next_frame(self):
                self.frames += 1

            def log_info(self, *_args, **_kwargs):
                pass

            def info_set(self, key, value):
                self.info[key] = value

        task = FakeTask()

        self.assertIsNone(DailyTask.get_total_daily_points(task))
        self.assertEqual(2, task.frames)
        self.assertIsNone(task.info['total daily points'])

    def test_daily_points_use_highest_valid_value_from_retries(self):
        responses = iter([
            [SimpleNamespace(name='70', confidence=0.9)],
            [SimpleNamespace(name='领取', confidence=0.9)],
            [SimpleNamespace(name='100', confidence=0.8)],
        ])

        class FakeTask:
            def ocr(self, *_args, **_kwargs):
                return next(responses)

            def next_frame(self):
                pass

            def log_info(self, *_args, **_kwargs):
                pass

            def info_set(self, key, value):
                self.info = (key, value)

        task = FakeTask()

        self.assertEqual(100, DailyTask.get_total_daily_points(task))
        self.assertEqual(('total daily points', 100), task.info)

    def test_daily_points_accept_completed_values_up_to_180(self):
        responses = iter([
            [SimpleNamespace(name='110', confidence=0.9)],
            [SimpleNamespace(name='120', confidence=0.9)],
            [SimpleNamespace(name='180', confidence=0.9),
             SimpleNamespace(name='181', confidence=0.9)],
        ])

        class FakeTask:
            def ocr(self, *_args, **_kwargs):
                return next(responses)

            def next_frame(self):
                pass

            def log_info(self, *_args, **_kwargs):
                pass

            def info_set(self, key, value):
                self.info = (key, value)

        task = FakeTask()

        self.assertEqual(180, DailyTask.get_total_daily_points(task))
        self.assertEqual(('total daily points', 180), task.info)

    def test_unknown_activity_disables_backup_for_stamina_policy(self):
        policy = DailyTask._stamina_policy_activity_ready

        self.assertTrue(policy(None))
        self.assertTrue(policy(True))
        self.assertFalse(policy(False))

    def test_unknown_activity_claims_before_recheck(self):
        task = self._finish_task(True)

        self.assertEqual((180, True), DailyTask._claim_and_recheck_daily_activity(task))
        self.assertLess(task.events.index('claim'), task.events.index('verify'))

    @staticmethod
    def _finish_task(verified_ready):
        class FakeTask:
            def __init__(self):
                self.events = []

            def _publish_daily_stage(self, *_args):
                self.events.append('publish')

            def log_info(self, *_args, **_kwargs):
                self.events.append('log')

            def claim_daily(self):
                self.events.append('claim')

            def open_daily(self):
                self.events.append('verify')
                return 180, verified_ready

            def _notify_incomplete_daily_activity(self, _message):
                self.events.append('notify')

        return FakeTask()

    def test_claim_happens_before_retrying_unknown_activity(self):
        task = self._finish_task(True)

        self.assertTrue(DailyTask._finish_daily_rewards(task, None))
        self.assertLess(task.events.index('claim'), task.events.index('verify'))

    def test_confirmed_incomplete_claims_before_raising(self):
        task = self._finish_task(False)

        with self.assertRaises(DailyActivityIncomplete):
            DailyTask._finish_daily_rewards(task, False)

        self.assertLess(task.events.index('claim'), task.events.index('notify'))

    def test_unknown_after_claim_raises_detection_error(self):
        task = self._finish_task(None)

        with self.assertRaises(DailyActivityDetectionError):
            DailyTask._finish_daily_rewards(task, None)

        self.assertLess(task.events.index('claim'), task.events.index('notify'))

    def claim_task(self):
        task = Mock(spec=DailyTask)
        task.require_game_frame.return_value = np.zeros((90,160,3),np.uint8)
        task._daily_page_ready.return_value = True
        task._restore_daily_claim_page.return_value = task.require_game_frame.return_value
        return task

    def test_claim_lost_first_click_retries_same_chest_only(self):
        task = self.claim_task()
        with patch('src.task.daily_observation.claimable_tiers',
                   side_effect=lambda f:[20] if task.click_relative.call_count<2 else []):
            DailyTask.claim_daily(task)
        self.assertEqual(task.click_relative.call_count,2)
        self.assertTrue(all(c.args==(.392,.887) for c in task.click_relative.call_args_list))
        task.ensure_main.assert_called_once()

    def test_unchanged_chest_never_reports_success(self):
        task = self.claim_task()
        with patch('src.task.daily_observation.claimable_tiers',return_value=[20]):
            with self.assertRaises(DailyActivityIncomplete):DailyTask.claim_daily(task)
        self.assertEqual(task.click_relative.call_count,2)
        task.ensure_main.assert_not_called()

    def test_already_claimed_does_not_click_locked_tier(self):
        task = self.claim_task()
        with patch('src.task.daily_observation.claimable_tiers',return_value=[]):
            DailyTask.claim_daily(task)
        task.click_relative.assert_not_called()

    def test_reward_overlay_is_closed_before_verification(self):
        task = self.claim_task()
        task._restore_daily_claim_page = MethodType(DailyTask._restore_daily_claim_page, task)
        task._daily_reward_overlay.side_effect = lambda f: (
            'ready' if task.click_relative.call_count == 1 else None)
        with patch('src.task.daily_observation.claimable_tiers',
                   side_effect=lambda f:[20] if not task.click_relative.called else []):
            DailyTask.claim_daily(task)
        self.assertEqual([c.args for c in task.click_relative.call_args_list],[(.392,.887),(.50,.78)])
        task._open_daily_page.assert_called_once()

    def test_delayed_animation_takes_priority_over_background_anchors(self):
        task = self.claim_task()
        task._daily_reward_overlay.side_effect = [None, 'opening', 'ready', None, None, None]
        result = DailyTask._restore_daily_claim_page(task)
        self.assertIs(result, task.require_game_frame.return_value)
        task.click_relative.assert_called_once_with(.50, .78, after_sleep=.5)
        self.assertEqual(task.next_frame.call_count, 6)
        task._open_daily_page.assert_not_called()

    def test_stuck_overlay_is_bounded_and_cannot_become_success(self):
        task = self.claim_task()
        task._daily_reward_overlay.return_value = 'ready'
        with self.assertRaises(DailyActivityIncomplete):
            DailyTask._restore_daily_claim_page(task)
        self.assertEqual(task.click_relative.call_count, 3)
        self.assertLessEqual(task.next_frame.call_count, 16)
        task._open_daily_page.assert_not_called()

    def test_animation_without_continue_prompt_gets_bounded_blank_click(self):
        task = self.claim_task()
        task._daily_reward_overlay.side_effect = lambda f: None if task.click_relative.called else 'opening'
        DailyTask._restore_daily_claim_page(task)
        task.click_relative.assert_called_once()

    def test_unknown_page_never_counts_as_claimed(self):
        task = self.claim_task()
        task._daily_reward_overlay.return_value = None
        task._daily_page_ready.return_value = False
        with self.assertRaises(DailyActivityIncomplete):
            DailyTask._restore_daily_claim_page(task)
        task.click_relative.assert_not_called()

    def test_one_click_awarding_all_tiers_does_not_click_stale_chests(self):
        task = self.claim_task()
        with patch('src.task.daily_observation.claimable_tiers',
                   side_effect=lambda f: [] if task.click_relative.called else [20,40,60,80,100]):
            DailyTask.claim_daily(task)
        task.click_relative.assert_called_once_with(.392, .887, after_sleep=.7)
        task.ensure_main.assert_called_once()


if __name__ == '__main__':
    unittest.main()
