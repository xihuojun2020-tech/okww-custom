import unittest
from unittest.mock import Mock, patch

import numpy as np
from ok import Box, TaskDisabledException
from src.task.SkipDialogTask import AutoDialogTask
from src.task.ui_transition import TransitionContextChanged
from tests import TestBackgroundNavigationTasks as background_tests


class TestStorySkipRecovery(unittest.TestCase):
    def task(self):
        harness = background_tests.TestBackgroundNavigationTasks()
        self.addCleanup(harness.doCleanups)
        task = harness.task(AutoDialogTask)
        harness.button = Box(80, 50, 40, 30, name='skip_dialog_hex', confidence=.9)
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

    def test_timeout_requests_verified_source_and_current_frame_with_signals(self):
        task, harness = self.task()
        frame = task.require_game_frame.return_value
        frame.fill(41)
        for _ in range(3):
            harness.tick(task)
        operation = task._ui_tick_navigation['operation']
        frame.fill(91)
        harness.clock[0] = 61
        self.assertFalse(harness.tick(task))
        self.assertEqual(task.screenshot.call_count, 2)
        source, current = task.screenshot.call_args_list
        self.assertEqual(source.args[0], f'story_skip_{operation}_source')
        self.assertEqual(current.args[0], f'story_skip_{operation}_timeout')
        self.assertTrue(np.all(source.kwargs['frame'][100] == 41))
        self.assertTrue(np.all(current.kwargs['frame'][100] == 91))
        self.assertTrue(np.all(source.kwargs['frame'][:27] == 0))
        self.assertTrue(np.all(current.kwargs['frame'][-27:] == 0))
        self.assertTrue(np.all(frame == 91))
        detail = next(call.args[0] for call in task.log_warning.call_args_list
                      if 'timeout_evidence id=' in call.args[0])
        for text in (operation, 'attempts=1', "'box': (80, 50, 40, 30)",
                     "'world': False", "'confirm': False", "'skip': True"):
            self.assertIn(text, detail)
        task.disable.assert_not_called()

    def test_cooldown_retries_merge_evidence_until_world_recovery(self):
        task, harness = self.task()
        for _ in range(3):
            harness.tick(task)
        first_operation = task._ui_tick_navigation['operation']
        harness.clock[0] = 61
        harness.tick(task)
        harness.clock[0] = 76
        for _ in range(3):
            harness.tick(task)
        harness.clock[0] = 137
        harness.tick(task)
        self.assertEqual(task.screenshot.call_count, 2)
        self.assertTrue(any(f'merged_into={first_operation}' in call.args[0]
                            for call in task.log_warning.call_args_list))
        task.in_team_and_world.return_value = True
        harness.tick(task)
        task.in_team_and_world.return_value = False
        for _ in range(3):
            harness.tick(task)
        harness.clock[0] = 201
        harness.tick(task)
        self.assertEqual(task.screenshot.call_count, 4)
        task.disable.assert_not_called()

    def test_confirmation_timeout_retains_source_after_button_disappears(self):
        task, harness = self.task()
        harness.button.name = 'skip_story_summary'
        task._skip_confirmation.return_value = harness.button
        task.find_skip.return_value = None
        for _ in range(3):
            harness.tick(task)
        task._skip_confirmation.return_value = None
        harness.clock[0] = 61
        self.assertFalse(harness.tick(task))
        self.assertEqual(task._skip_blocked_step, '剧情跳过确认')
        self.assertEqual(task.screenshot.call_count, 2)
        detail = next(call.args[0] for call in task.log_warning.call_args_list
                      if 'timeout_evidence id=' in call.args[0])
        self.assertIn("'name': 'skip_story_summary'", detail)
        self.assertIn("'confirm': False", detail)
        self.assertIn("'skip': False", detail)
        task.disable.assert_not_called()

    def test_evidence_failure_is_reported_without_disabling_or_replaying_input(self):
        task, harness = self.task()
        task.screenshot.side_effect = OSError('evidence disk unavailable')
        for _ in range(3):
            harness.tick(task)
        harness.clock[0] = 61
        with patch('src.task.SkipDialogTask.logger.warning') as warning:
            self.assertFalse(harness.tick(task))
        self.assertEqual(warning.call_count, 2)
        self.assertIn('evidence disk unavailable', warning.call_args.args[0])
        task.click_box.assert_called_once()
        task.disable.assert_not_called()
        self.assertIsNone(task._ui_tick_navigation)
        self.assertEqual(task.trigger_interval, .5)

    def test_stop_during_evidence_request_propagates(self):
        task, harness = self.task()
        task.screenshot.side_effect = TaskDisabledException()
        for _ in range(3):
            harness.tick(task)
        harness.clock[0] = 61
        with self.assertRaises(TaskDisabledException):
            harness.tick(task)
        task.screenshot.assert_called_once()
        task.click_box.assert_called_once()

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
