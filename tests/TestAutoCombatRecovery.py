import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.task.AutoCombatTask import AutoCombatTask
from src.char.HavocRover import HavocRover
from src.char.BaseChar import Elements
from custom_ok.ok.task.TaskExecutor import TaskExecutor


class TestAutoCombatRecovery(unittest.TestCase):
    def make_task(self):
        executor = SimpleNamespace(scene=None, text_fix={}, remove_onetime_task=Mock(), _wake_executor=Mock(),
                                   global_config=SimpleNamespace(get_config=lambda _: {}))
        task = AutoCombatTask(executor=executor, app=None)
        task.config = dict(task.default_config)
        task._enabled = True
        task.info_set = Mock()
        task.do_reset_to_false = Mock()
        return task

    def test_rover_preidentified_wind_initializes_synergy(self):
        rover = HavocRover(task=Mock(), index=0)
        self.assertFalse(rover.use_skyfall_severance)
        rover.ring_index = Elements.WIND
        rover.task.has_char.return_value = True
        rover.init()
        self.assertTrue(rover.use_skyfall_severance)
        rover.task._ensure_ring_index.assert_not_called()
        rover.task.has_char.return_value = False
        rover.init()
        self.assertFalse(rover.use_skyfall_severance)

    def test_rover_display_recognition_before_init(self):
        rover = HavocRover(task=Mock(), index=0)
        rover.is_current_char = True
        rover.task._ensure_ring_index.side_effect = lambda: setattr(rover, 'ring_index', Elements.WIND)
        rover.ensure_display_form()
        rover.task.has_char.return_value = True
        rover.init()
        self.assertTrue(rover.use_skyfall_severance)

    def test_first_error_keeps_startup_enabled_and_only_ui_stop_disables(self):
        task = self.make_task()
        self.assertTrue(task.handle_execution_error(ValueError('fixture')))
        task.disable()  # An internal shutdown request is not a user toggle.
        self.assertTrue(task.enabled)
        self.assertTrue(task.config['_enabled'])
        self.assertEqual(task.recovery_status, '异常恢复中')
        task.set_enabled_from_ui(False)
        self.assertFalse(task.enabled)
        self.assertFalse(task.config['_enabled'])
        self.assertEqual(task.recovery_status, '已手动关闭')

    def test_normal_enable_setup_failure_preserves_preference_and_retries(self):
        task = self.make_task()
        task._enabled = False
        with patch('src.task.AutoCombatTask.threading.Thread'):
            task.set_enabled_from_ui(True)
        task._prepare_combat_input = Mock(side_effect=OSError('window gone'))
        task._enable_from_ui(task._manual_generation)
        self.assertTrue(task.enabled)
        self.assertTrue(task.config['_enabled'])
        self.assertTrue(task._enable_pending)
        task._prepare_combat_input.side_effect = None
        task._run_combat = Mock(return_value=True)
        task.run()
        self.assertEqual(2, task._prepare_combat_input.call_count)
        self.assertEqual(0, task._error_count)

    def test_restart_restores_saved_preference_and_internal_enable_cannot_override_stop(self):
        for enabled in (True, False):
            task = self.make_task()
            task.config['_enabled'] = enabled
            task.on_create()
            self.assertEqual(enabled, task.enabled)
            if enabled:
                self.assertTrue(task.handle_execution_error(ValueError('startup failed')))
                self.assertTrue(task.enabled)
            else:
                task._prepare_combat_input = Mock()
                task.enable()
                task._prepare_combat_input.assert_not_called()
                self.assertFalse(task.config['_enabled'])
        task.set_enabled_from_ui(False)
        task._prepare_combat_input = Mock()
        task.enable()
        task._prepare_combat_input.assert_not_called()
        self.assertFalse(task.enabled)
        self.assertFalse(task.config['_enabled'])

    def test_no_frame_wait_recovers_on_later_frame_without_new_toggle(self):
        task = self.make_task()
        event = threading.Event()
        task.run = Mock(side_effect=lambda: event.set() or True)
        owner = SimpleNamespace(exit_event=event, paused=False, _get_wake_version=lambda: 0,
            next_task=lambda: (task, True, True), _last_frame_time=0, reset_scene=Mock(),
            _frame=None, current_task=None, trigger_tasks=[task], destroy=Mock(),
            next_frame=Mock(side_effect=[None, object()]))
        TaskExecutor.execute(owner)
        self.assertTrue(task.enabled)
        self.assertTrue(task.config['_enabled'])
        self.assertEqual(2, owner.next_frame.call_count)
        task.run.assert_called_once()

    def test_repeated_errors_back_off_and_do_not_spam(self):
        task = self.make_task()
        with patch('src.task.AutoCombatTask.time.monotonic', return_value=100), \
                patch('src.task.BaseCombatTask.logger.error') as report:
            for delay in (2, 4, 8, 16, 30, 30):
                self.assertTrue(task.handle_execution_error(ValueError('fixture')))
                self.assertEqual(task.retry_delay, delay)
                self.assertFalse(task.should_trigger())
            self.assertEqual(report.call_count, 1)
            self.assertEqual(task._suppressed_combat_errors, 5)
            self.assertEqual(task.recovery_status, '异常恢复中')
        self.assertTrue(task.enabled)

    def test_recovery_only_clears_after_a_handled_combat(self):
        task = self.make_task()
        task._error_count = 3
        task._run_combat = Mock(return_value=False)
        task.run()
        self.assertEqual(task._error_count, 3)
        task._run_combat.return_value = True
        task.run()
        self.assertEqual(task.recovery_status, '已开启，等待战斗')

    def test_stop_wins_over_error_and_pending_enable_worker(self):
        task = self.make_task()
        with patch('src.task.AutoCombatTask.threading.Thread'):
            task.set_enabled_from_ui(True)
        generation = task._manual_generation
        task.set_enabled_from_ui(False)
        task._prepare_combat_input = Mock()
        task._enable_from_ui(generation)
        task._prepare_combat_input.assert_not_called()
        self.assertTrue(task.handle_execution_error(ValueError('late error')))
        self.assertFalse(task.enabled)

    def test_stop_during_enable_setup_remains_disabled(self):
        task = self.make_task()
        task._manual_desired = True
        task._prepare_combat_input = Mock(side_effect=lambda: task.set_enabled_from_ui(False))
        task._enable_from_ui(task._manual_generation)
        self.assertFalse(task.enabled)
        self.assertFalse(task.config['_enabled'])

    def test_failed_release_blocks_new_input_and_retries_original_backend(self):
        task = self.make_task()
        backend = Mock()
        backend.send_key_up.side_effect = OSError('window unavailable')
        task._combat_held_keys['w'] = backend
        task._run_combat = Mock()
        with self.assertRaises(RuntimeError):
            task.run()
        task._run_combat.assert_not_called()
        backend.send_key_up.side_effect = None
        task._release_combat_inputs()
        self.assertEqual(task._combat_held_keys, {})
        backend.send_key_up.assert_called_with(key='w')

    def test_executor_wait_includes_recovery_delay(self):
        task = self.make_task()
        task.last_trigger_time = 0
        with patch('src.task.AutoCombatTask.time.monotonic', return_value=100):
            task._retry_at = 130
            self.assertEqual(TaskExecutor.next_trigger_delay(SimpleNamespace(trigger_tasks=[task])), 30)

    def test_executor_hook_handles_capture_and_run_errors_without_disabling(self):
        from ok.task.exceptions import CaptureException
        for capture_error in (False, True):
            task = self.make_task()
            event = threading.Event()
            task.run = Mock(side_effect=ValueError('rotation failed'))
            owner = SimpleNamespace(exit_event=event, paused=False, _get_wake_version=lambda: 0,
                next_task=lambda: (task, False, True), _last_frame_time=0, reset_scene=Mock(),
                _frame=None if capture_error else object(), current_task=None, destroy=Mock())
            original = task.handle_execution_error
            def recover(error):
                result = original(error)
                event.set()
                return result
            task.handle_execution_error = recover
            owner.next_frame = Mock(side_effect=CaptureException('capture failed'))
            TaskExecutor.execute(owner)
            self.assertTrue(task.enabled)
            self.assertIsNone(owner.current_task)
            self.assertFalse(task.running)
            if capture_error:
                task.run.assert_not_called()

    def test_diagnostic_failures_do_not_cancel_recovery(self):
        task = self.make_task()
        task.executor._frame = object()
        task.info_set.side_effect = RuntimeError('status failed')
        task.screenshot = Mock(side_effect=OSError('disk full'))
        with patch('src.task.BaseCombatTask.logger.error', side_effect=RuntimeError('log failed')):
            self.assertTrue(task.handle_execution_error(ValueError('rotation failed')))
        self.assertTrue(task.enabled)
        self.assertTrue(task.config['_enabled'])
        self.assertGreater(task.retry_delay, 0)
        task.screenshot.assert_called_once()

    def test_executor_fallback_survives_recovery_and_signal_errors(self):
        task = self.make_task()
        task.handle_execution_error = Mock(side_effect=RuntimeError('recovery failed'))
        with patch('custom_ok.ok.task.TaskExecutor.communicate') as signals:
            signals.task.emit.side_effect = RuntimeError('UI failed')
            self.assertTrue(TaskExecutor._recover_trigger_error(task, ValueError('rotation failed')))
        self.assertTrue(task.enabled)
        self.assertTrue(task.config['_enabled'])
        self.assertGreater(task.retry_delay, 0)
        task.set_enabled_from_ui(False)
        self.assertTrue(TaskExecutor._recover_trigger_error(task, ValueError('late failure')))
        self.assertFalse(task.enabled)
        self.assertFalse(task.config['_enabled'])

    def test_executor_scene_reset_error_is_recovered_without_running_actions(self):
        task = self.make_task()
        event = threading.Event()
        task.run = Mock()
        owner = SimpleNamespace(exit_event=event, paused=False, _get_wake_version=lambda: 0,
            next_task=lambda: (task, True, True), _last_frame_time=0,
            reset_scene=Mock(side_effect=ValueError('scene failed')), _frame=object(),
            current_task=None, destroy=Mock())
        original = task.handle_execution_error
        def recover(error):
            result = original(error)
            event.set()
            return result
        task.handle_execution_error = recover
        TaskExecutor.execute(owner)
        self.assertTrue(task.enabled)
        task.run.assert_not_called()
        self.assertIsNone(owner.current_task)

    def test_scheduler_failure_does_not_end_executor_or_clear_combat_preference(self):
        task = self.make_task()
        event = threading.Event()
        task.run = Mock(side_effect=lambda: event.set() or True)
        owner = SimpleNamespace(exit_event=event, paused=False, _get_wake_version=lambda: 0,
            next_task=Mock(side_effect=[ValueError('scheduler failed'), (task, False, True)]),
            _last_frame_time=0, reset_scene=Mock(), _frame=object(), current_task=None,
            trigger_tasks=[task], _wait_for_activity=Mock(), destroy=Mock())
        TaskExecutor.execute(owner)
        self.assertTrue(task.enabled)
        self.assertTrue(task.config['_enabled'])
        self.assertEqual(2, owner.next_task.call_count)
        owner._wait_for_activity.assert_called_once_with(1)

    def test_manual_stop_current_task_uses_explicit_toggle(self):
        task = self.make_task()
        task.unpause = Mock()
        TaskExecutor.stop_current_task(SimpleNamespace(current_task=task))
        self.assertFalse(task.enabled)
        self.assertFalse(task.config['_enabled'])

    def test_finished_and_manual_stop_exceptions_bypass_recovery(self):
        from ok.task.exceptions import FinishedException, TaskDisabledException
        for error in (FinishedException(), TaskDisabledException()):
            task = self.make_task()
            task.handle_execution_error = Mock()
            event = threading.Event()
            def fail():
                event.set()
                raise error
            task.run = fail
            owner = SimpleNamespace(exit_event=event, paused=False, _get_wake_version=lambda: 0,
                next_task=lambda: (task, False, True), _last_frame_time=0, reset_scene=Mock(),
                _frame=object(), current_task=None, destroy=Mock())
            TaskExecutor.execute(owner)
            task.handle_execution_error.assert_not_called()
            self.assertIsNone(owner.current_task)

    def test_pause_and_exit_are_not_overridden_by_protection(self):
        task = self.make_task()
        event = threading.Event()
        event.set()
        owner = SimpleNamespace(exit_event=event, paused=True, next_task=Mock(), destroy=Mock())
        TaskExecutor.execute(owner)
        owner.next_task.assert_not_called()
        self.assertTrue(task.enabled)


if __name__ == '__main__':
    unittest.main()
