import unittest
from unittest.mock import Mock, patch

from ok import TaskDisabledException
from src.task.SkipDialogTask import AutoDialogTask
from src.task.ui_transition import TransitionContextChanged
from tests import TestBackgroundNavigationTasks as background_tests


class TestStorySkipRecovery(unittest.TestCase):
    def task(self):
        harness = background_tests.TestBackgroundNavigationTasks()
        self.addCleanup(harness.doCleanups)
        task = harness.task(AutoDialogTask)
        task.disable = Mock(side_effect=AssertionError('ordinary timeout must not disable watcher'))
        task.find_skip = Mock(return_value=harness.button)
        task._skip_confirmation = Mock(return_value=None)
        task.check_skip = Mock(return_value=False)
        task.skip_message = Mock(return_value=False)
        return task, harness

    def test_entry_timeout_cools_down_then_requires_fresh_verification(self):
        task, harness = self.task()
        for _ in range(3):
            harness.tick(task)
        task.click_box.assert_called_once()
        harness.clock[0] = 61
        self.assertFalse(harness.tick(task))
        self.assertEqual(task._skip_blocked_step, '剧情跳过')
        self.assertIsNone(task._ui_tick_navigation)
        self.assertEqual(task.trigger_interval, .5)
        for second in (62, 70, 75):
            harness.clock[0] = second
            harness.tick(task)
        task.click_box.assert_called_once()
        harness.clock[0] = 76
        harness.tick(task)
        task.run()  # Same capture cannot advance the new verification.
        task.click_box.assert_called_once()
        harness.tick(task)
        task.click_box.assert_called_once()
        harness.tick(task)
        self.assertEqual(task.click_box.call_count, 2)
        task.disable.assert_not_called()
        task.check_skip.assert_not_called()

    def test_ignored_entry_click_retries_with_spacing_and_bounded_burst(self):
        task, harness = self.task()
        times = []
        task.click_box.side_effect = lambda *a, **kw: times.append(harness.clock[0])
        for _ in range(24):
            harness.tick(task)
        self.assertEqual(times, [1, 4, 7])
        self.assertEqual(task._skip_blocked_step, '剧情跳过')
        self.assertGreaterEqual(task._skip_retry_at, 25)

    def test_unknown_page_after_cooldown_never_receives_input(self):
        task, harness = self.task()
        for _ in range(3):
            harness.tick(task)
        task.find_skip.return_value = None
        harness.clock[0] = 61
        harness.tick(task)
        for second in (80, 120, 180):
            harness.clock[0] = second
            harness.tick(task)
        task.click_box.assert_called_once()

    def test_ignored_entry_then_late_confirmation_stops_entry_retries(self):
        task, harness = self.task()
        for _ in range(10):
            harness.tick(task)
        self.assertEqual(task.click_box.call_count, 2)
        task._skip_confirmation.return_value = harness.button
        for _ in range(4):
            harness.tick(task)
        self.assertEqual(task.click_box.call_count, 3)
        self.assertEqual(task._ui_tick_navigation['step'], '剧情跳过确认')

    def test_late_confirmation_resumes_after_entry_timeout(self):
        task, harness = self.task()
        for _ in range(3):
            harness.tick(task)
        task.find_skip.return_value = None
        harness.clock[0] = 61
        harness.tick(task)
        for _ in range(4):
            harness.tick(task)
        task.click_box.assert_called_once()
        task._skip_confirmation.return_value = harness.button
        for _ in range(2):
            harness.tick(task)
        task.click_box.assert_called_once()
        harness.tick(task)
        self.assertEqual(task.click_box.call_count, 2)
        self.assertIsNone(task._skip_blocked_step)

    def test_confirmation_retry_exhaustion_keeps_watcher_without_more_clicks(self):
        task, harness = self.task()
        task._skip_confirmation.return_value = harness.button
        for _ in range(40):
            harness.tick(task)
        self.assertEqual(task.click_box.call_count, 3)
        self.assertEqual(task._skip_blocked_step, '剧情跳过确认')
        task.disable.assert_not_called()

    def test_world_return_rearms_next_dialogue(self):
        task, harness = self.task()
        for _ in range(3):
            harness.tick(task)
        harness.clock[0] = 61
        harness.tick(task)
        task.in_team_and_world.return_value = True
        harness.tick(task)
        self.assertIsNone(task._skip_blocked_step)
        task.in_team_and_world.return_value = False
        for _ in range(3):
            harness.tick(task)
        self.assertEqual(task.click_box.call_count, 2)

    def test_slow_loading_and_flickering_confirmation_never_click_early(self):
        task, harness = self.task()
        for _ in range(3):
            harness.tick(task)
        task.find_skip.return_value = None
        for _ in range(10):
            harness.tick(task)
        task.click_box.assert_called_once()
        task._skip_confirmation.return_value = harness.button
        harness.tick(task)  # Finish the old entry stage, no confirmation input.
        harness.tick(task)  # First confirmation sample.
        task._skip_confirmation.return_value = None
        harness.tick(task)  # Loading resumes: stable evidence is invalidated.
        task._skip_confirmation.return_value = harness.button
        harness.tick(task)
        harness.tick(task)
        task.click_box.assert_called_once()
        harness.tick(task)
        self.assertEqual(task.click_box.call_count, 2)

    def test_confirmation_has_minimum_settle_time_even_with_fast_distinct_frames(self):
        task, harness = self.task()
        task._skip_confirmation.return_value = harness.button
        for now in (0, .01, .02):
            harness.clock[0] = now
            task.executor._last_frame_time += 1
            task.run()
        task.click_box.assert_not_called()
        harness.clock[0] = .3
        task.executor._last_frame_time += 1
        task.run()
        task.click_box.assert_called_once()

    def test_checked_circle_is_not_toggled_after_timeout(self):
        task, harness = self.task()
        harness.button.name = 'skip_story_checkbox'
        task._skip_confirmation.return_value = harness.button
        for _ in range(3):
            harness.tick(task)
        harness.clock[0] = 61
        harness.tick(task)
        for _ in range(4):
            harness.tick(task)
        task.click_box.assert_called_once()
        harness.button.name = 'skip_story_warning_confirm'
        for _ in range(3):
            harness.tick(task)
        self.assertEqual(task.click_box.call_count, 2)

    def test_context_change_discards_old_operation_and_reverifies(self):
        task, harness = self.task()
        with patch('src.task.SkipDialogTask.advance', side_effect=TransitionContextChanged('window changed')):
            self.assertFalse(harness.tick(task))
        self.assertIsNone(task._ui_tick_navigation)
        self.assertIsNone(task._skip_blocked_step)
        task.click_box.assert_not_called()
        for _ in range(3):
            harness.tick(task)
        task.click_box.assert_called_once()

    def test_cancel_and_input_errors_still_propagate(self):
        for error in (TaskDisabledException(), OSError('input failed')):
            task, harness = self.task()
            with patch('src.task.SkipDialogTask.advance', side_effect=error):
                with self.assertRaises(type(error)):
                    harness.tick(task)


if __name__ == '__main__':
    unittest.main()
