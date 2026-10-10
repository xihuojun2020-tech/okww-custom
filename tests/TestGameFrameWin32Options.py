"""Production Win32 contracts with injected APIs; no native DLL, capture or input."""

import ctypes
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from gameframe.devices import windows
from gameframe import device_editor as editor
from gameframe.api import Action
from PySide6.QtWidgets import QApplication


def forbid_dll(*args, **kwargs):
    raise AssertionError('Real Win32 DLL access is forbidden in these tests')


class Function:
    """ctypes-like callable with assignable prototypes."""
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


class FakeWin32:
    def __init__(self):
        self.calls, self.messages = [], []
        self.context = 1
        self.width, self.height = 3, 2
        self.minimized, self.print_fail, self.bitblt_fail, self.post_fail = False, False, False, False
        self.selected, self.buffers, self.arrays = {}, {}, {}
        self.next_handle = 100
        names = ('GetDC', 'ReleaseDC', 'PrintWindow', 'GetWindowRect', 'GetClientRect',
                 'ClientToScreen', 'IsIconic', 'SetThreadDpiAwarenessContext',
                 'CreateCompatibleDC', 'DeleteDC', 'CreateDIBSection', 'SelectObject',
                 'DeleteObject', 'BitBlt', 'GdiFlush', 'PostMessageW', 'MapVirtualKeyW',
                 'GetWindowDpiAwarenessContext', 'PhysicalToLogicalPointForPerMonitorDPI',
                 'ScreenToClient', 'GetForegroundWindow', 'SetForegroundWindow')
        for name in names:
            setattr(self, name, Function(lambda *args, name=name: self.call(name, *args)))

    def call(self, name, *args):
        self.calls.append((name, args))
        if name == 'SetThreadDpiAwarenessContext':
            previous = self.context
            self.context = ctypes.c_ssize_t(args[0].value).value if isinstance(args[0], ctypes.c_void_p) else args[0]
            return previous
        if name == 'GetWindowDpiAwarenessContext':
            return 1
        if name in ('GetWindowRect', 'GetClientRect'):
            rect = ctypes.cast(args[1], ctypes.POINTER(windows.wintypes.RECT)).contents
            values = ((-12, -24, self.width - 8, self.height - 18) if name == 'GetWindowRect'
                      else (0, 0, self.width, self.height))
            rect.left, rect.top, rect.right, rect.bottom = values
            return 1
        if name in ('ClientToScreen', 'ScreenToClient', 'PhysicalToLogicalPointForPerMonitorDPI'):
            point = ctypes.cast(args[1], ctypes.POINTER(windows._Point)).contents
            # Target is DPI unaware on a 150% monitor with negative origin.
            if name == 'ClientToScreen':
                point.x += -10 if self.context == -4 else -100
                point.y += -20 if self.context == -4 else -200
            elif name == 'ScreenToClient':
                point.x += 100
                point.y += 200
            else:
                point.x = round((point.x + 10) / 1.5) - 100
                point.y = round((point.y + 20) / 1.5) - 200
            return 1
        if name == 'IsIconic':
            return int(self.minimized)
        if name == 'GetDC':
            return 10
        if name == 'CreateCompatibleDC':
            self.next_handle += 1
            self.selected[self.next_handle] = 99
            return self.next_handle
        if name == 'CreateDIBSection':
            info = ctypes.cast(args[1], ctypes.POINTER(windows._BitmapInfo)).contents
            assert info.height < 0 and info.bits == 32 and info.planes == 1
            buffer = (ctypes.c_ubyte * (info.width * -info.height * 4))()
            self.next_handle += 1
            bitmap = self.next_handle
            self.buffers[bitmap] = buffer
            self.arrays[bitmap] = windows.np.ctypeslib.as_array(buffer).reshape(-info.height, info.width, 4)
            ctypes.cast(args[3], ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.addressof(buffer)
            return bitmap
        if name == 'SelectObject':
            previous = self.selected[args[0]]
            self.selected[args[0]] = args[1]
            return previous
        if name == 'PrintWindow':
            if self.print_fail:
                return 0
            array = self.arrays[self.selected[args[1]]]
            for y in range(array.shape[0]):
                for x in range(array.shape[1]):
                    array[y, x] = (x, y, 33, 255)
            return 1
        if name == 'BitBlt':
            if self.bitblt_fail:
                return 0
            destination, _, _, width, height, source, x, y, operation = args
            assert operation == 0x00CC0020
            self.arrays[self.selected[destination]][:] = self.arrays[self.selected[source]][y:y+height, x:x+width]
            return 1
        if name == 'DeleteObject':
            assert args[0] not in self.selected.values()
            self.arrays[args[0]][:] = 0  # Catch returned views into released memory.
            del self.buffers[args[0]]
            del self.arrays[args[0]]
            return 1
        if name == 'DeleteDC':
            assert self.selected.pop(args[0]) == 99
            return 1
        if name == 'PostMessageW':
            if self.post_fail:
                ctypes.set_last_error(5)
                return 0
            self.messages.append(args)
            return 1
        if name == 'MapVirtualKeyW':
            return 0xE04D if args[0] == 0x27 else 0x1E
        if name == 'GetForegroundWindow':
            return 7  # Deliberately different from selected HWND 42.
        return 1


class FakeWindow:
    def __init__(self):
        self.live, self.process, self.created = True, 123, 12.5
        self.focus = 42
        self.rect = (-1200, 80, 1920, 1080)

    def exists(self, hwnd):
        return self.live

    def pid(self, hwnd):
        return self.process

    def process_created(self, pid):
        return self.created

    def windows(self, pid):
        return [42]

    def foreground(self):
        return self.focus

    def client_screen_rect(self, hwnd):
        return self.rect


class TestGameFrameWin32Options(unittest.TestCase):
    def setUp(self):
        guard = patch.object(ctypes, 'WinDLL', side_effect=forbid_dll)
        guard.start()
        self.addCleanup(guard.stop)

    def capture(self, api, method):
        return windows._GdiCapture(42, method, user32=api, gdi32=api)

    def message_device(self):
        api, platform = FakeWin32(), FakeWindow()
        device = windows.WindowsDevice(42, input_method='PostMessage', window_backend=platform)
        device.window  # Record the selected identity before simulating reuse.
        device._input_backend = windows._PostMessage(42, device._check_target_identity, user32=api)
        return device, api, platform

    def test_printwindow_client_bgr_copy_resize_and_cleanup(self):
        api = FakeWin32()
        capture = self.capture(api, 'PrintWindow')
        image = capture.read()
        self.assertEqual(image.shape, (2, 3, 3))
        self.assertEqual(image[1, 2].tolist(), [2, 1, 33])
        self.assertTrue(image.flags.c_contiguous)
        self.assertEqual([args[2] for name, args in api.calls if name == 'PrintWindow'], [3])
        self.assertEqual(api.context, 1)
        self.assertFalse(api.selected or api.buffers)
        self.assertEqual(sum(name == 'ReleaseDC' for name, _ in api.calls), 1)
        self.assertEqual(sum(name == 'GdiFlush' for name, _ in api.calls), 1)
        api.width, api.height = 4, 3
        self.assertEqual(capture.read().shape, (3, 4, 3))
        self.assertEqual(image[1, 2].tolist(), [2, 1, 33])

    def test_renderfull_renders_memory_dc_and_bitblt_client_crop(self):
        api = FakeWin32()
        image = self.capture(api, 'BitBlt_RenderFull').read()
        self.assertEqual(image[0, 0].tolist(), [2, 4, 33])
        self.assertEqual(image[1, 2].tolist(), [4, 5, 33])
        printed = [args for name, args in api.calls if name == 'PrintWindow']
        self.assertEqual(printed[0][2], 2)
        self.assertNotEqual(printed[0][1], 10)  # Never render to source/window DC.
        self.assertFalse(api.selected or api.buffers)

    def test_capture_failure_releases_resources_and_never_falls_back(self):
        for method, failure in [('PrintWindow', 'print_fail'), ('BitBlt_RenderFull', 'print_fail'),
                                ('BitBlt_RenderFull', 'bitblt_fail')]:
            with self.subTest(method=method, failure=failure):
                api = FakeWin32()
                setattr(api, failure, True)
                with self.assertRaises(OSError):
                    self.capture(api, method).read()
                self.assertFalse(api.selected or api.buffers)
                self.assertEqual(api.context, 1)
                self.assertEqual(sum(name == 'ReleaseDC' for name, _ in api.calls), 1)
                self.assertEqual(sum(name == 'PrintWindow' for name, _ in api.calls), 1)

    def test_minimized_and_empty_client_refused_before_allocation(self):
        for attr, value in [('minimized', True), ('width', 0)]:
            api = FakeWin32()
            setattr(api, attr, value)
            with self.assertRaises((RuntimeError, OSError)):
                self.capture(api, 'PrintWindow').read()
            self.assertFalse(any(name == 'GetDC' for name, _ in api.calls))

    def test_postmessage_dpi_mouse_modifiers_wheel_and_release(self):
        device, api, _ = self.message_device()
        self.assertNotIn('relative-mouse', device.capabilities)
        self.assertIn('desktop-handoff', device.capabilities)
        device.submit(Action('key_down', {'key': 'ctrl'}))
        device.submit(Action('move_client', {'x': 150, 'y': 75}))
        self.assertEqual(api.messages[-1], (42, 0x200, 8, 100 | (50 << 16)))
        device.submit(Action('button_down', {'button': 'left'}))
        self.assertEqual(api.messages[-1][2], 9)
        device.submit(Action('scroll', {'clicks': -2}))
        self.assertEqual(api.messages[-1], (42, 0x20A, 9 | ((-240 & 0xFFFF) << 16), (0 | ((-150 & 0xFFFF) << 16))))
        device.release_all()
        self.assertFalse(device._keys or device._buttons or device._input_backend.keys or device._input_backend.buttons)
        self.assertEqual(api.context, 1)
        self.assertFalse(any(name == 'SetForegroundWindow' for name, _ in api.calls))
        with self.assertRaisesRegex(RuntimeError, 'raw relative'):
            device.submit(Action('move_relative', {'dx': 1, 'dy': 2}))
        with self.assertRaisesRegex(RuntimeError, 'physical desktop'):
            device.set_cursor_pos((1, 2))

    def test_key_extended_repeat_release_alt_and_unicode_units(self):
        device, api, _ = self.message_device()
        for kind in ('key_down', 'key_down', 'key_up'):
            device.submit(Action(kind, {'key': 'right'}))
        self.assertEqual(api.messages[0][3], 1 | (0x4D << 16) | (1 << 24))
        self.assertEqual(api.messages[1][3], api.messages[0][3] | (1 << 30))
        self.assertEqual(api.messages[2][3], api.messages[1][3] | (1 << 31))
        device.submit(Action('key_down', {'key': 'alt'}))
        device.submit(Action('key_down', {'key': 'A'}))
        self.assertEqual(api.messages[-1][1], 0x104)
        self.assertTrue(api.messages[-1][3] & (1 << 29))
        device.release_all()
        device.submit(Action('key_down', {'key': 'rctrl'}))
        self.assertEqual(api.messages[-1][2], 0x11)
        device.release_all()
        device.submit(Action('key_down', {'key': 'f10'}))
        self.assertEqual(api.messages[-1][1:3], (0x104, 0x79))
        device.release_all()
        device.submit(Action('text', {'text': '角😀'}))
        self.assertEqual([(message, value) for _, message, value, _ in api.messages[-3:]],
                         [(0x102, ord('角')), (0x102, 0xD83D), (0x102, 0xDE00)])

    def test_failed_postmessage_up_retains_owned_key_for_cleanup(self):
        device, api, _ = self.message_device()
        device.submit(Action('key_down', {'key': 'A'}))
        api.post_fail = True
        with self.assertRaises(OSError):
            device.submit(Action('key_up', {'key': 'A'}))
        self.assertEqual(device._keys, {65})
        with self.assertRaises(ExceptionGroup):
            device.release_all()
        self.assertEqual(device._input_backend.keys, {65})
        api.post_fail = False
        device.release_all()
        self.assertFalse(device._keys)

    def test_reused_or_missing_identity_refuses_messages_and_activation(self):
        for attr, value in [('live', False), ('process', 124), ('created', 13.0)]:
            device, api, platform = self.message_device()
            setattr(platform, attr, value)
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                device.submit(Action('key_down', {'key': 'A'}))
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                device.submit(Action('activate'))
            self.assertFalse(api.messages or api.calls)

    def test_rebinding_releases_old_target_and_recreates_backend(self):
        device, api, _ = self.message_device()
        device.submit(Action('key_down', {'key': 'A'}))
        device._bind_window(43)
        self.assertEqual(api.messages[-1][0:3], (42, 0x101, 65))
        self.assertEqual(device.hwnd, 43)
        self.assertIsNone(device._input_backend)
        self.assertFalse(device._keys)

    def test_capture_selection_routes_explicitly_and_preserves_frame_contract(self):
        api, platform = FakeWin32(), FakeWindow()
        device = windows.WindowsDevice(42, capture_method='PrintWindow', window_backend=platform,
                                      capture_factory=lambda hwnd, method: self.capture(api, method))
        frame = device.next_frame()
        self.assertEqual(frame.sequence, 1)
        self.assertEqual(frame.image.shape, (2, 3, 3))
        self.assertGreater(frame.captured_ns, 0)
        self.assertEqual(device.next_frame().sequence, 2)
        device.close()
        for kwargs in [{'capture_method': 'auto'}, {'input_method': 'auto'}]:
            with self.assertRaises(ValueError):
                windows.WindowsDevice(42, **kwargs)

    def test_editor_selection_persistence_defaults_and_no_device_access(self):
        application = QApplication.instance() or QApplication([])
        widget = editor.DeviceEditor(window_enumerator=lambda: self.fail('Unexpected enumeration'))
        widget.set_options({'type': 'windows', 'hwnd': 42})
        self.assertEqual(widget.options(), {'type': 'windows', 'hwnd': 42})
        widget.fields['windows']['capture_method'].setCurrentText('PrintWindow')
        widget.fields['windows']['input_method'].setCurrentText('PostMessage')
        self.assertEqual(widget.options()['capture_method'], 'PrintWindow')
        self.assertEqual(widget.options()['input_method'], 'PostMessage')
        self.assertNotIn('relative-mouse', widget.capabilities())
        self.assertNotIn('relative-mouse', widget.capabilities_label.text())
        values = widget.options()
        widget.set_options(values)
        self.assertEqual(widget.fields['windows']['input_method'].currentText(), 'PostMessage')
        self.assertEqual(widget.options(), values)
        widget.set_options({'type': 'windows', 'hwnd': 42, 'capture_method': 'unknown'})
        self.assertEqual(widget.options()['capture_method'], 'unknown')
        self.assertEqual(widget.fields['windows']['capture_method'].currentIndex(), -1)
        widget.close()
        application.processEvents()

    def test_production_factory_json_and_lazy_construction(self):
        from gameframe.worker import create_device
        options = json.loads('{"type":"windows","hwnd":42,"capture_method":"BitBlt_RenderFull","input_method":"PostMessage"}')
        device = create_device(options)
        self.assertEqual(device.capture_method, 'BitBlt_RenderFull')
        self.assertEqual(device.input_method, 'PostMessage')
        self.assertNotIn('relative-mouse', device.capabilities)
        self.assertIn('desktop-handoff', device.capabilities)
        self.assertIsNone(device._input_backend)
        self.assertIsNone(device._capture)
        device.close()
        default = create_device({'type': 'windows', 'hwnd': 42})
        self.assertEqual((default.capture_method, default.input_method), ('WGC', 'SendInput'))
        self.assertIn('relative-mouse', default.capabilities)
        default.close()

    def test_overlay_read_only_physical_owner_contract(self):
        platform = FakeWindow()
        device = windows.WindowsDevice(42, window_backend=platform)
        self.assertEqual(device.overlay_target(), {
            'owner': {'hwnd': 42, 'pid': 123, 'created': 12.5},
            'x': -1200, 'y': 80, 'width': 1920, 'height': 1080})
        self.assertIsNone(device._input_backend)
        self.assertIsNone(device._capture)
        self.assertFalse(device._keys or device._buttons)
        device.close()
        self.assertIsNone(device.overlay_target())
        unbound = windows.WindowsDevice(launch_command=[r'C:\Game\launcher.exe'],
                                       target_executable=r'C:\Game\game.exe')
        self.assertIsNone(unbound.overlay_target())

    def test_overlay_refuses_background_missing_reused_and_geometry_races(self):
        for attr, value in [('focus', 7), ('live', False), ('process', 124),
                            ('created', 13.0), ('rect', (0, 0, 0, 1080))]:
            with self.subTest(attr=attr):
                platform = FakeWindow()
                device = windows.WindowsDevice(42, window_backend=platform)
                device.window
                setattr(platform, attr, value)
                self.assertIsNone(device.overlay_target())
        for attr, value in [('focus', 7), ('live', False), ('process', 124), ('created', 13.0)]:
            with self.subTest(race=attr):
                platform = FakeWindow()
                device = windows.WindowsDevice(42, window_backend=platform)
                def changed_rect(hwnd):
                    setattr(platform, attr, value)
                    return platform.rect
                platform.client_screen_rect = changed_rect
                self.assertIsNone(device.overlay_target())
        import psutil
        platform = FakeWindow()
        device = windows.WindowsDevice(42, window_backend=platform)
        device.window
        with patch.object(platform, 'process_created', side_effect=psutil.NoSuchProcess(123)):
            self.assertIsNone(device.overlay_target())
        platform = FakeWindow()
        device = windows.WindowsDevice(42, window_backend=platform)
        def reselected_rect(hwnd):
            device.hwnd = 43
            return platform.rect
        platform.client_screen_rect = reselected_rect
        self.assertIsNone(device.overlay_target())

    def test_native_client_screen_rect_uses_one_physical_dpi_scope(self):
        api = FakeWin32()
        backend = windows._WindowBackend.__new__(windows._WindowBackend)
        backend.user32 = api
        reads = []
        def client(hwnd):
            reads.append(('client', api.context))
            return (0, 0, 1920, 1080)
        def origin(hwnd, point):
            reads.append(('origin', api.context))
            return (-1200, 80)
        backend.gui = SimpleNamespace(GetClientRect=client, ClientToScreen=origin)
        self.assertEqual(backend.client_screen_rect(42), (-1200, 80, 1920, 1080))
        self.assertEqual(reads, [('client', -4), ('origin', -4)])
        self.assertEqual(api.context, 1)


if __name__ == '__main__':
    unittest.main()
