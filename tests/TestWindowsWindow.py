"""Windows task metadata contracts, entirely mocked off the desktop."""

import unittest
from unittest.mock import Mock
from gameframe.devices.windows import WindowsDevice


class Platform:
    def __init__(self):
        self.foreground_hwnd = 100
        self.handles = {100: 7, 101: 7, 200: 8}
        self.position = (400, 500)
        self.origin = (-1200, 40)

    def exists(self, hwnd):
        return hwnd in self.handles

    def pid(self, hwnd):
        return self.handles[hwnd]

    def process_created(self, pid):
        return 1000

    def foreground(self):
        return self.foreground_hwnd

    def title(self, hwnd):
        return f'window {hwnd}'

    def is_visible(self, hwnd):
        return True

    def root(self, hwnd):
        return hwnd

    def windows(self, pid):
        return [hwnd for hwnd, owner in self.handles.items() if owner == pid]

    def client_to_screen(self, hwnd, x, y):
        if not self.exists(hwnd):
            raise OSError('destroyed HWND')
        return self.origin[0] + x, self.origin[1] + y

    def cursor(self):
        return self.position

    def set_cursor(self, position):
        self.position = position

    def hotkey_pressed(self, vk):
        return vk == 0xBF


class Input:
    def __init__(self):
        self.foreground = False
        self.activations = 0

    def is_foreground(self, hwnd):
        return self.foreground

    def activate(self, hwnd):
        self.activations += 1
        self.foreground = True


class TestWindowsWindow(unittest.TestCase):
    def setUp(self):
        self.platform, self.input = Platform(), Input()
        self.device = WindowsDevice(100, window_backend=self.platform,
                                    input_backend=self.input)

    def test_metadata_is_live_and_login_dialog_stays_in_same_process(self):
        window = self.device.window
        self.assertTrue(window.exists)
        self.assertTrue(window.visible)
        self.assertEqual(window.hwnd_title, 'window 100')
        self.assertEqual(window.hwnds, [100, 101])
        self.platform.foreground_hwnd = 101
        self.assertEqual(window.top_hwnd, 101)
        self.assertTrue(window.visible)
        self.platform.foreground_hwnd = 200
        self.assertEqual(window.top_hwnd, 100)
        self.assertFalse(window.visible)
        del self.platform.handles[100]
        window.do_update_window_size()
        self.assertEqual(window.hwnds, [101])
        self.assertFalse(window.exists)
        with self.assertRaisesRegex(OSError, 'destroyed HWND'):
            window.get_capture_origin()

    def test_coordinates_cursor_and_foreground_probe_do_not_activate(self):
        self.assertEqual(self.device.window.get_capture_origin(), (-1200, 40))
        self.assertEqual(self.device.client_to_screen(30, 20), (-1170, 60))
        self.platform.origin = (80, 90)
        self.assertEqual(self.device.window.get_capture_origin(), (80, 90))
        self.assertEqual(self.device.get_cursor_pos(), (400, 500))
        self.device.set_cursor_pos((30, 40))
        self.assertEqual(self.device.get_cursor_pos(), (30, 40))
        self.assertFalse(self.device.is_foreground())
        self.assertEqual(self.input.activations, 0)
        self.assertTrue(self.device.hotkey_pressed(0xBF))
        self.assertEqual(self.device.foreground_pid(), 7)
        self.assertTrue(self.device.window.bring_to_front())
        self.assertEqual(self.input.activations, 1)

    def test_stop_target_terminates_only_verified_selected_process_and_waits(self):
        process = Mock(pid=7)
        process.create_time.return_value = 1000
        factory = Mock(return_value=process)
        self.device._process_factory = factory
        self.device.stop_target()
        factory.assert_called_once_with(7)
        process.kill.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=10)

    def test_stop_target_refuses_destroyed_or_reassigned_window(self):
        self.device.window
        factory = Mock()
        self.device._process_factory = factory
        self.platform.handles[100] = 8
        with self.assertRaisesRegex(RuntimeError, 'trusted game process'):
            self.device.stop_target()
        factory.assert_not_called()
        del self.platform.handles[100]
        with self.assertRaisesRegex(RuntimeError, 'trusted game process'):
            self.device.stop_target()
        factory.assert_not_called()

    def test_stop_target_failure_to_confirm_exit_propagates(self):
        process = Mock(pid=7)
        process.create_time.return_value = 1000
        process.wait.side_effect = TimeoutError('process still alive')
        self.device._process_factory = Mock(return_value=process)
        with self.assertRaisesRegex(TimeoutError, 'process still alive'):
            self.device.stop_target()

    def test_stop_target_refuses_reused_process_identity(self):
        self.device.window
        process = Mock(pid=7)
        process.create_time.return_value = 2000
        self.device._process_factory = Mock(return_value=process)
        with self.assertRaisesRegex(RuntimeError, 'identity has been reused'):
            self.device.stop_target()
        process.kill.assert_not_called()


if __name__ == '__main__':
    unittest.main()
