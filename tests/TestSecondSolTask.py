import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ok import TaskDisabledException
from config import config
from src.task.SecondSolTask import SecondSolTask


class TestSecondSolTask(unittest.TestCase):
    def task(self):
        task = object.__new__(SecondSolTask)
        task._executor = SimpleNamespace(
            reset_scene=Mock(), sleep=Mock(side_effect=TaskDisabledException()),
            interaction=Mock(), device_manager=SimpleNamespace(
                hwnd_window=SimpleNamespace(exists=True, hwnd=100, top_hwnd=101)))
        task.info_set = Mock()
        return task

    def test_registration(self):
        self.assertEqual(config['onetime_tasks'].count(['src.task.SecondSolTask', 'SecondSolTask']), 1)
        task = SecondSolTask(executor=Mock(scene=None), app=None)
        self.assertFalse(task.support_schedule_task)
        self.assertEqual(task.name, '第二索拉·诡影迷踪')

    def test_timing_includes_hold_and_always_releases(self):
        task = self.task()
        with patch('src.task.SecondSolTask.win32gui.GetForegroundWindow', return_value=100), \
                patch('src.task.SecondSolTask.random.uniform', side_effect=[1.0, 0.07]) as jitter, \
                patch('src.task.SecondSolTask.time.monotonic', side_effect=[10.0, 10.07]):
            with self.assertRaises(TaskDisabledException):
                task.run()
        self.assertEqual(jitter.call_args_list[0].args, (0.85, 1.15))
        self.assertEqual(jitter.call_args_list[1].args, (0.05, 0.10))
        task.executor.interaction.send_key.assert_called_once_with('f', down_time=0.07)
        task.executor.interaction.send_key_up.assert_called_once_with('f')
        self.assertAlmostEqual(task.executor.sleep.call_args.args[0], 0.93)

    def test_background_does_not_press_or_activate(self):
        task = self.task()
        with patch('src.task.SecondSolTask.win32gui.GetForegroundWindow', return_value=999):
            with self.assertRaises(TaskDisabledException):
                task.run()
        self.assertEqual(task.executor.interaction.mock_calls, [])
        task.executor.sleep.assert_called_once_with(0.2)

    def test_stop_before_press_does_not_send_input(self):
        task = self.task()
        task.executor.reset_scene.side_effect = TaskDisabledException()
        with self.assertRaises(TaskDisabledException):
            task.run()
        self.assertEqual(task.executor.interaction.mock_calls, [])

    def test_failed_press_still_releases_and_does_not_repeat(self):
        task = self.task()
        task.executor.interaction.send_key.side_effect = RuntimeError('input failed')
        with patch('src.task.SecondSolTask.win32gui.GetForegroundWindow', return_value=100):
            with self.assertRaisesRegex(RuntimeError, 'input failed'):
                task.run()
        task.executor.interaction.send_key_up.assert_called_once_with('f')
        task.executor.sleep.assert_not_called()

    def test_missing_window_stops(self):
        task = self.task()
        task.executor.device_manager.hwnd_window.exists = False
        with self.assertRaisesRegex(RuntimeError, '游戏窗口已断开'):
            task.run()
        self.assertEqual(task.executor.interaction.mock_calls, [])

    def test_focus_rechecked_after_pause_boundary(self):
        task = self.task()
        foreground = [100]
        task.executor.reset_scene.side_effect = lambda: foreground.__setitem__(0, 999)
        with patch('src.task.SecondSolTask.win32gui.GetForegroundWindow', side_effect=lambda: foreground[0]):
            with self.assertRaises(TaskDisabledException):
                task.run()
        self.assertEqual(task.executor.interaction.mock_calls, [])

    def test_background_then_foreground_continues_without_burst(self):
        task = self.task()
        task.executor.sleep.side_effect = [None, TaskDisabledException()]
        with patch('src.task.SecondSolTask.win32gui.GetForegroundWindow', side_effect=[999, 101]):
            with self.assertRaises(TaskDisabledException):
                task.run()
        self.assertEqual(task.executor.interaction.send_key.call_count, 1)
        self.assertEqual(task.executor.interaction.send_key_up.call_count, 1)


if __name__ == '__main__':
    unittest.main()
