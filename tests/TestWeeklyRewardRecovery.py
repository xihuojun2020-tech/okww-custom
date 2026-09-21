import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.task.WeeklyBossTask import WeeklyBossTask, WeeklyPageTimeout


class TestWeeklyRewardRecovery(unittest.TestCase):
    def task(self):
        task = object.__new__(WeeklyBossTask)
        task.logger = Mock()
        task.info = {}
        task._executor = SimpleNamespace(frame=None)
        for name in ('next_frame', 'sleep', '_release_movement', 'send_key', '_stage',
                     'scroll_relative', 'do_walk_to_box', 'log_info'):
            setattr(task, name, Mock())
        task.in_team_and_world = Mock(return_value=True)
        task._reward_available = Mock(return_value=None)
        task._selected_reward_interaction = Mock(return_value=None)
        task.find_f_with_text = Mock(return_value=None)
        task.find_treasure_icon = Mock(return_value=None)
        task._task_hint_phase = Mock(return_value='post')
        task._settlement = Mock(return_value=None)
        task._claim_confirmation = Mock(return_value=None)
        task._text = Mock(return_value='')
        return task

    def test_absorb_then_reward_without_generic_cancel_handler(self):
        task = self.task()
        task._selected_reward_interaction.side_effect = [True]
        task._reward_available.side_effect = [None, True, True]
        task._seek_reward_interaction()
        task.send_key.assert_called_once_with('f')
        task.do_walk_to_box.assert_not_called()

    def test_occluded_marker_causes_bounded_reposition_not_static_wait(self):
        task = self.task()
        task._reward_available.side_effect = [None, None, True, True]
        task._seek_reward_interaction()
        self.assertTrue(any(c.args[0] in ('s', 'a', 'd') for c in task.send_key.call_args_list))
        task.do_walk_to_box.assert_not_called()

    def test_scroll_must_be_followed_by_fresh_selected_reward_verification(self):
        task = self.task()
        task.find_f_with_text.return_value = True
        task._reward_available.side_effect = [None, True, True]
        task._seek_reward_interaction()
        task.send_key.assert_not_called()
        self.assertGreaterEqual(task.next_frame.call_count, 2)

    def test_missing_marker_recovery_has_finite_budget(self):
        task = self.task()
        with patch('src.task.WeeklyBossTask.time.monotonic', side_effect=range(200)):
            with self.assertRaisesRegex(WeeklyPageTimeout, '领取奖励'):
                task._seek_reward_interaction(timeout=10)
        self.assertLessEqual(task.send_key.call_count, 6)

    def test_stop_during_search_releases_movement(self):
        from ok import TaskDisabledException
        task = self.task()
        task.next_frame.side_effect = TaskDisabledException()
        with self.assertRaises(TaskDisabledException):
            task._seek_reward_interaction()
        task._release_movement.assert_called()

    def test_unconfirmed_f_can_retry_only_verified_reward(self):
        task = self.task()
        task._reward_available.return_value = True
        task._wait_for = Mock(side_effect=lambda read, *args: next(v for _ in range(12) if (v := read())))
        task._claim_confirmation.side_effect = lambda: (60, 120, 'confirm') if task.send_key.called else None
        task.click_box = Mock()
        with patch('src.task.WeeklyBossTask.time.monotonic', side_effect=range(100)):
            task._confirm_claim_if_needed(60, retry_interaction=True)
        task.send_key.assert_called_once_with('f')
        task.click_box.assert_called_once_with('confirm')

    def test_visible_but_unreadable_dialog_disables_f_retry(self):
        task = self.task()
        task._reward_available.return_value = True
        task._text.return_value = '领取奖励'
        with patch('src.task.WeeklyBossTask.time.monotonic', side_effect=range(100)):
            with self.assertRaises(WeeklyPageTimeout):
                task._confirm_claim_if_needed(60, retry_interaction=True)
        task.send_key.assert_not_called()

    def test_f_retry_budget_is_two_even_when_interaction_persists(self):
        task = self.task()
        task._reward_available.return_value = True
        with patch('src.task.WeeklyBossTask.time.monotonic', side_effect=range(100)):
            with self.assertRaises(WeeklyPageTimeout):
                task._confirm_claim_if_needed(60, retry_interaction=True)
        self.assertEqual(task.send_key.call_count, 2)

    def test_disappearing_interaction_after_stopping_is_not_pressed(self):
        task = self.task()
        task._reward_available.side_effect = [True, None] * 20
        with patch('src.task.WeeklyBossTask.time.monotonic', side_effect=range(100)):
            with self.assertRaises(WeeklyPageTimeout):
                task._confirm_claim_if_needed(60, retry_interaction=True)
        task.send_key.assert_not_called()

    def test_stop_and_capture_loss_in_retry_propagate(self):
        from ok import TaskDisabledException
        from src.runtime.game_runtime_errors import FrameUnavailable
        for error in (TaskDisabledException(), FrameUnavailable('lost')):
            task = self.task()
            task._claim_confirmation.side_effect = error
            with self.assertRaises(type(error)):
                task._confirm_claim_if_needed(60, retry_interaction=True)
            task.send_key.assert_not_called()

    def test_marker_walk_is_segmented_and_does_not_press_f(self):
        task = self.task()
        task.find_treasure_icon.return_value = object()
        task._reward_available.side_effect = [None, True, True]
        task._seek_reward_interaction()
        self.assertLessEqual(task.do_walk_to_box.call_args.kwargs['time_out'], 1)
        task.send_key.assert_not_called()

    def test_unknown_screen_prevents_search_inputs(self):
        task = self.task()
        task.in_team_and_world.return_value = False
        with patch('src.task.WeeklyBossTask.time.monotonic', side_effect=range(100)):
            with self.assertRaises(WeeklyPageTimeout):
                task._seek_reward_interaction(timeout=5)
        task.send_key.assert_not_called()
        task.find_f_with_text.assert_not_called()
        task.do_walk_to_box.assert_not_called()

    def test_retry_never_sends_f_for_absorb_or_unavailable_world(self):
        for world, reward in ((True, None), (False, True)):
            task = self.task()
            task.in_team_and_world.return_value = world
            task._reward_available.return_value = reward
            with patch('src.task.WeeklyBossTask.time.monotonic', side_effect=range(100)):
                with self.assertRaises(WeeklyPageTimeout):
                    task._confirm_claim_if_needed(60, retry_interaction=True)
            task.send_key.assert_not_called()


if __name__ == '__main__':
    unittest.main()
