import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.task.AutoCombatTask import AutoCombatTask
from src.char.HavocRover import HavocRover
from src.char.BaseChar import Elements
from ok.task.TaskExecutor import TaskExecutor


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

    def test_first_error_disables_normally_then_manual_restart_arms_protection(self):
        task = self.make_task()
        self.assertFalse(task.handle_execution_error(ValueError('fixture')))
        task.disable()  # Normal executor path.
        self.assertFalse(task.enabled)
        self.assertEqual(task.recovery_status, '异常已关闭')
        with patch('src.task.AutoCombatTask.threading.Thread') as thread:
            task.set_enabled_from_ui(True)
        self.assertTrue(task.manual_keep_enabled)
        self.assertEqual(thread.call_args.kwargs['name'], 'TaskEnable')
        task._enabled = True
        self.assertTrue(task.handle_execution_error(ValueError('fixture')))
        self.assertTrue(task.enabled)
        task.set_enabled_from_ui(False)
        self.assertFalse(task.enabled)
        self.assertFalse(task.manual_keep_enabled)
        self.assertFalse(task._auto_disabled)

    def test_startup_and_normal_manual_enable_do_not_arm_protection(self):
        task = self.make_task()
        self.assertFalse(task.manual_keep_enabled)
        with patch('src.task.AutoCombatTask.threading.Thread'):
            task.set_enabled_from_ui(True)
        self.assertFalse(task.manual_keep_enabled)
        task.manual_keep_enabled = True
        self.assertFalse(self.make_task().manual_keep_enabled)

    def test_repeated_errors_back_off_and_do_not_spam(self):
        task = self.make_task()
        task.manual_keep_enabled = True
        with patch('src.task.AutoCombatTask.time.monotonic', return_value=100), \
                patch('src.task.AutoCombatTask.logger.error') as report:
            for delay in (2, 4, 8, 16, 30, 30):
                self.assertTrue(task.handle_execution_error(ValueError('fixture')))
                self.assertEqual(task.retry_delay, delay)
                self.assertFalse(task.should_trigger())
            self.assertEqual(report.call_count, 1)
            self.assertEqual(task._suppressed_errors, 5)
            self.assertEqual(task.recovery_status, '异常恢复中')
        self.assertTrue(task.enabled)

    def test_recovery_only_clears_after_a_handled_combat(self):
        task = self.make_task()
        task.manual_keep_enabled = True
        task._error_count = 3
        task._run_combat = Mock(return_value=False)
        task.run()
        self.assertEqual(task._error_count, 3)
        task._run_combat.return_value = True
        task.run()
        self.assertEqual(task.recovery_status, '手动保持开启')

    def test_stop_wins_over_error_and_pending_enable_worker(self):
        task = self.make_task()
        task._auto_disabled = True
        with patch('src.task.AutoCombatTask.threading.Thread'):
            task.set_enabled_from_ui(True)
        generation = task._manual_generation
        task.set_enabled_from_ui(False)
        task.enable = Mock()
        task._enable_from_ui(generation)
        task.enable.assert_not_called()
        self.assertTrue(task.handle_execution_error(ValueError('late error')))
        self.assertFalse(task._auto_disabled)
        self.assertFalse(task.enabled)

    def test_stop_during_enable_setup_remains_disabled(self):
        task = self.make_task()
        task._manual_desired = True
        task.enable = Mock(side_effect=lambda: task.set_enabled_from_ui(False))
        task._enable_from_ui(task._manual_generation)
        self.assertFalse(task.enabled)
        self.assertFalse(task.config['_enabled'])

    def test_failed_release_blocks_new_input_and_retries_original_backend(self):
        task = self.make_task()
        backend = Mock()
        backend.send_key_up.side_effect = OSError('window unavailable')
        task._held_keys['w'] = backend
        task._run_combat = Mock()
        with self.assertRaises(RuntimeError):
            task.run()
        task._run_combat.assert_not_called()
        backend.send_key_up.side_effect = None
        task._release_combat_inputs()
        self.assertEqual(task._held_keys, {})
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
            task.manual_keep_enabled = True
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
        task.manual_keep_enabled = True
        event = threading.Event()
        event.set()
        owner = SimpleNamespace(exit_event=event, paused=True, next_task=Mock(), destroy=Mock())
        TaskExecutor.execute(owner)
        owner.next_task.assert_not_called()
        self.assertTrue(task.manual_keep_enabled)


if __name__ == '__main__':
    unittest.main()
