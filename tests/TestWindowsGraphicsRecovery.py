import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from custom_ok.ok.task.TaskExecutor import TaskExecutor
from custom_ok.ok.device.capture_methods.windows_graphics import WindowsGraphicsCaptureMethod


class TestWindowsGraphicsRecovery(unittest.TestCase):
    def capture(self):
        capture = object.__new__(WindowsGraphicsCaptureMethod)
        capture._hwnd_window = SimpleNamespace(exists=True, hwnd=123)
        capture.exit_event = threading.Event()
        capture.frame_pool = None
        capture.get_capture_hwnd = Mock(return_value=123)
        return capture

    def test_empty_pool_does_not_block_executor_recovery(self):
        capture = self.capture()
        frame = np.zeros((20, 20, 3), dtype=np.uint8)
        capture.get_frame = Mock(side_effect=[None, frame])
        executor = SimpleNamespace(
            device_manager=SimpleNamespace(get_preferred_device=lambda: object()),
            method=capture, interaction=SimpleNamespace(should_capture=lambda: True),
            exit_event=threading.Event(), reset_scene=Mock(), check_enabled=Mock(),
            sleep=Mock(), blur_overlay_processor=None)
        executor.can_capture = lambda: TaskExecutor.can_capture(executor)
        self.assertIs(TaskExecutor.next_frame(executor, time_out=0.1), frame)
        self.assertEqual(capture.get_frame.call_count, 2)
        capture.exit_event.set()
        self.assertFalse(capture.connected())
        capture.exit_event.clear()
        capture.get_capture_hwnd.return_value = 0
        self.assertFalse(capture.connected())

    def test_retired_callback_cannot_read_new_pool(self):
        capture = self.capture()
        capture.lock = threading.RLock()
        capture._capture_generation = 2
        capture.frame_pool = Mock()
        capture.frame_arrived_callback(generation=1)
        capture.frame_pool.TryGetNextFrame.assert_not_called()
        capture.close = Mock()
        capture._close_generation(1)
        capture.close.assert_not_called()
        capture._close_generation(2)
        capture.close.assert_called_once()

    def test_failed_start_is_throttled(self):
        capture = self.capture()
        capture.lock = threading.RLock()
        capture._hwnd_window.capture_target_signature = (123,)
        capture.last_start_failure_key = 123
        capture.last_start_failure_time = 100
        with patch('custom_ok.ok.device.capture_methods.windows_graphics.time.monotonic', return_value=102):
            self.assertFalse(capture.start_or_stop())


if __name__ == '__main__':
    unittest.main()
