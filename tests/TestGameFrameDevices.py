"""Offline device contract checks: no real HWND, SDK, capture, or input calls."""

import ctypes
import subprocess
import unittest
from ctypes import wintypes

import cv2
import numpy as np

from gameframe.api import Action
from gameframe.devices.adb import AdbDevice
from gameframe.devices.mumu import MuMuDevice
from gameframe.devices.windows import WindowsDevice, _Point, _client_roi


class FakeControl:
    def __init__(self):
        self.finished = False
        self.failure = None
        self.stopped = False

    def is_finished(self):
        return self.finished

    def wait(self):
        if self.failure:
            raise self.failure

    def stop(self):
        self.stopped = True


class FakeCapture:
    def __init__(self):
        self.handlers = {}
        self.control = FakeControl()
        self.started = False

    def event(self, handler):
        self.handlers[handler.__name__] = handler
        return handler

    def start_free_threaded(self):
        self.started = True
        return self.control

    def emit(self, pixels):
        self.handlers["on_frame_arrived"](type("WgcFrame", (), {"frame_buffer": pixels})(), None)


class FakeInput:
    def __init__(self):
        self.foreground = True
        self.calls = []
        self.fail_up = False
        self.fail_button_up = False
        self.activation_changes_foreground = True

    def is_foreground(self, hwnd):
        return self.foreground

    def activate(self, hwnd):
        self.calls.append(('activate', hwnd))
        self.foreground = self.activation_changes_foreground

    def key(self, vk, down):
        self.calls.append(("key", vk, down))
        if not down and self.fail_up:
            raise OSError("key release failed")

    def button(self, button, down):
        self.calls.append(("button", button, down))
        if not down and self.fail_button_up:
            raise OSError("button release failed")

    def move_relative(self, dx, dy):
        self.calls.append(("move", dx, dy))

    def move_client(self, hwnd, x, y):
        self.calls.append(("client", hwnd, x, y))

    def unicode_key(self, scan, down):
        self.calls.append(('unicode', scan, down))
        if not down and self.fail_up:
            raise OSError('unicode release failed')

    def scroll(self, clicks):
        self.calls.append(('scroll', clicks))


class FakeGeometry:
    def __init__(self, inset=None):
        self.inset = inset

    def client_rect_in_frame(self, hwnd, width, height):
        if self.inset is None:
            return 0, 0, width, height
        left, top, right, bottom = self.inset
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise OSError("Client area falls outside WGC window frame")
        return self.inset


class FakeMuMuLibrary:
    def __init__(self):
        self.calls = []
        self.capture_error = 0
        self.touch_error = 0
        self.pixel = 10

    def nemu_connect(self, path, index):
        self.calls.append(("connect", path, index))
        return 7

    def nemu_disconnect(self, handle):
        self.calls.append(("disconnect", handle))

    def nemu_get_display_id(self, handle, package, app_index):
        self.calls.append(("display", package, app_index))
        return 2

    def nemu_capture_display(self, handle, display, size, width, height, pixels):
        if self.capture_error:
            return self.capture_error
        ctypes.cast(width, ctypes.POINTER(ctypes.c_int))[0] = 2
        ctypes.cast(height, ctypes.POINTER(ctypes.c_int))[0] = 2
        if size:
            for i in range(size):
                pixels[i] = self.pixel if i % 4 == 0 else (20 if i % 4 == 1 else (30 if i % 4 == 2 else 255))
        return 0

    def nemu_input_event_finger_touch_down(self, handle, display, finger, x, y):
        self.calls.append(("down", finger, x, y))
        return self.touch_error

    def nemu_input_event_finger_touch_up(self, handle, display, finger):
        self.calls.append(("up", finger))
        return self.touch_error


class FakeAdbRunner:
    def __init__(self):
        self.calls = []
        self.png = cv2.imencode(".png", np.array([[[1, 2, 3]]], dtype=np.uint8))[1].tobytes()
        self.fail = False

    def __call__(self, argv, *, capture_output, check, timeout):
        self.calls.append((argv, timeout))
        if self.fail:
            raise subprocess.CalledProcessError(1, argv, b"", b"adb failure")
        stdout = self.png if "exec-out" in argv else b""
        return subprocess.CompletedProcess(argv, 0, stdout, b"")


class TestGameFrameDevices(unittest.TestCase):
    def test_windows_activation_precedes_input_gate_and_verifies_foreground(self):
        backend = FakeInput()
        device = WindowsDevice(42, input_backend=backend)
        backend.foreground = False
        device.submit(Action('activate'))
        device.submit(Action('key_down', {'key': 'W'}))
        self.assertEqual(backend.calls, [('activate', 42), ('key', ord('W'), True)])
        device.release_all()
        backend.foreground = False
        backend.activation_changes_foreground = False
        with self.assertRaisesRegex(RuntimeError, 'did not become foreground'):
            device.submit(Action('activate'))
        with self.assertRaisesRegex(RuntimeError, 'not foreground'):
            device.submit(Action('key_down', {'key': 'E'}))
        self.assertEqual(backend.calls[-1], ('activate', 42))
        device.close()

    def test_windows_scroll_and_unicode_text_use_device_input(self):
        backend = FakeInput()
        device = WindowsDevice(42, input_backend=backend)
        device.submit(Action('scroll', {'clicks': -4}))
        device.submit(Action('text', {'text': '角\U0001f600'}))
        self.assertEqual(backend.calls, [('scroll', -4),
                                        ('unicode', ord('角'), True), ('unicode', ord('角'), False),
                                        ('unicode', 0xd83d, True), ('unicode', 0xd83d, False),
                                        ('unicode', 0xde00, True), ('unicode', 0xde00, False)])
        self.assertFalse(device._unicode_keys)
        backend.foreground = False
        with self.assertRaisesRegex(RuntimeError, 'not foreground'):
            device.submit(Action('text', {'text': 'Z'}))
        self.assertEqual(len(backend.calls), 7)
        device.close()

    def test_windows_failed_unicode_up_stays_owned_for_cleanup(self):
        backend = FakeInput()
        device = WindowsDevice(42, input_backend=backend)
        backend.fail_up = True
        with self.assertRaisesRegex(OSError, 'unicode release failed'):
            device.submit(Action('text', {'text': '角'}))
        self.assertEqual(device._unicode_keys, {ord('角')})
        backend.fail_up = False
        device.release_all()
        self.assertFalse(device._unicode_keys)
        device.close()

    def test_windows_named_combat_keys_share_held_input_release(self):
        inputs = FakeInput()
        device = WindowsDevice(42, input_backend=inputs)
        for name in ('space', 'lshift', 'tab', 'esc', 'f6'):
            device.submit(Action('key_down', {'key': name}))
        device.release_all()
        self.assertEqual({call[1] for call in inputs.calls if call[2]}, {0x20, 0xA0, 0x09, 0x1B, 0x75})
        self.assertEqual({call[1] for call in inputs.calls if not call[2]}, {0x20, 0xA0, 0x09, 0x1B, 0x75})
        with self.assertRaisesRegex(ValueError, 'Unsupported key name'):
            device.submit(Action('key_down', {'key': 'unknown'}))

    def test_windows_finished_capture_failure_is_reported_then_recreated(self):
        first, second = FakeCapture(), FakeCapture()
        captures = iter((first, second))
        device = WindowsDevice(42, capture_factory=lambda **kwargs: next(captures),
                               input_backend=FakeInput(), geometry=FakeGeometry())
        self.assertIsNone(device.next_frame(0))
        first.control.finished = True
        first.control.failure = OSError('synthetic temporary resize failure')
        with self.assertRaisesRegex(OSError, 'temporary resize'):
            device.next_frame(0)
        self.assertIsNone(device.next_frame(0))
        self.assertTrue(second.started)
        second.emit(np.zeros((3, 4, 4), dtype=np.uint8))
        self.assertEqual(device.next_frame(0).sequence, 1)
        device.close()

    def test_windows_copies_callback_pixels_and_only_delivers_new_frames(self):
        capture = FakeCapture()
        device = WindowsDevice(42, capture_factory=lambda **kwargs: capture,
                               input_backend=FakeInput(), geometry=FakeGeometry())
        self.assertFalse(capture.started)
        self.assertIsNone(device.next_frame(0))
        self.assertTrue(capture.started)
        pixels = np.zeros((2, 3, 4), dtype=np.uint8)[:, :2, :]
        pixels[0, 0] = [1, 2, 3, 255]
        capture.emit(pixels)
        frame = device.next_frame(0)
        pixels[:] = 99
        self.assertEqual(frame.image[0, 0].tolist(), [1, 2, 3])
        self.assertEqual(frame.sequence, 1)
        self.assertEqual(frame.timestamp_source, "host-received")
        self.assertIsNone(device.next_frame(0))
        device.close()
        self.assertTrue(capture.control.stopped)

    def test_windows_surfaces_capture_and_input_failures(self):
        capture, input_backend = FakeCapture(), FakeInput()
        device = WindowsDevice(42, capture_factory=lambda **kwargs: capture,
                               input_backend=input_backend, geometry=FakeGeometry())
        input_backend.foreground = False
        with self.assertRaises(RuntimeError):
            device.submit(Action("key_down", {"key": "W"}))
        self.assertEqual(input_backend.calls, [])
        input_backend.foreground = True
        device.submit(Action("key_down", {"key": "W"}))
        input_backend.fail_up = True
        with self.assertRaises(ExceptionGroup):
            device.release_all()
        input_backend.fail_up = False
        device.release_all()
        self.assertIsNone(device.next_frame(0))
        capture.control.failure = RuntimeError("WGC callback failed")
        capture.control.finished = True
        with self.assertRaisesRegex(RuntimeError, "WGC callback failed"):
            device.next_frame(0)
        device.close()

    def test_windows_client_click_releases_button_and_reports_failed_up(self):
        backend = FakeInput()
        device = WindowsDevice(42, capture_factory=lambda **kwargs: FakeCapture(),
                               input_backend=backend, geometry=FakeGeometry())
        device.submit(Action("click", {"x": 12, "y": 34}))
        self.assertEqual(backend.calls, [("client", 42, 12, 34),
                                         ("button", "left", True), ("button", "left", False)])
        self.assertEqual(device._buttons, set())
        backend.fail_button_up = True
        with self.assertRaisesRegex(OSError, "button release failed"):
            device.submit(Action("click", {"x": 1, "y": 2}))
        self.assertEqual(device._buttons, {"left"})
        backend.fail_button_up = False
        device.release_all()
        self.assertEqual(device._buttons, set())
        device.close()

    def test_windows_client_move_does_not_press_mouse_button(self):
        backend = FakeInput()
        device = WindowsDevice(42, input_backend=backend)
        device.submit(Action("move_client", {"x": 120, "y": 340}))
        self.assertEqual(backend.calls, [("client", 42, 120, 340)])
        self.assertEqual(device._buttons, set())
        device.close()

    def test_windows_crops_title_and_border_so_frame_clicks_are_client_coordinates(self):
        capture, backend = FakeCapture(), FakeInput()
        device = WindowsDevice(42, capture_factory=lambda **kwargs: capture,
                               input_backend=backend, geometry=FakeGeometry((1, 2, 4, 4)))
        self.assertIsNone(device.next_frame(0))
        pixels = np.zeros((5, 5, 4), dtype=np.uint8)
        pixels[2, 1, :3] = [4, 5, 6]
        capture.emit(pixels)
        frame = device.next_frame(0)
        self.assertEqual(frame.image.shape, (2, 3, 3))
        self.assertEqual(frame.image[0, 0].tolist(), [4, 5, 6])
        device.submit(Action("click", {"x": 0, "y": 0}))
        self.assertEqual(backend.calls[0], ("client", 42, 0, 0))
        device.close()

    def test_windows_rejects_unmappable_client_region(self):
        capture = FakeCapture()
        device = WindowsDevice(42, capture_factory=lambda **kwargs: capture,
                               input_backend=FakeInput(), geometry=FakeGeometry((2, 3, 8, 9)))
        self.assertIsNone(device.next_frame(0))
        with self.assertRaises(OSError):
            capture.emit(np.zeros((5, 5, 4), dtype=np.uint8))
        device.close()

    def test_windows_dwm_geometry_maps_window_frame_and_rejects_size_mismatch(self):
        bounds = wintypes.RECT(100, 200, 105, 205)
        client = wintypes.RECT(0, 0, 3, 2)
        origin = _Point(101, 202)
        self.assertEqual(_client_roi(bounds, client, origin, 5, 5), (1, 2, 4, 4))
        with self.assertRaisesRegex(OSError, "does not match"):
            _client_roi(bounds, client, origin, 6, 5)

    def test_mumu_owns_pixels_and_contacts_are_independent(self):
        library = FakeMuMuLibrary()
        device = MuMuDevice("C:/fake/MuMu", 3, package_name="game.example", library=library)
        first = device.next_frame()
        library.pixel = 99
        second = device.next_frame()
        self.assertEqual(first.image[0, 0].tolist(), [30, 20, 10])
        self.assertEqual(second.image[0, 0].tolist(), [30, 20, 99])
        self.assertEqual(first.sequence, 1)
        device.submit(Action("touch_down", {"contact": 0, "x": 10, "y": 20}))
        device.submit(Action("touch_down", {"contact": 4, "x": 30, "y": 40}))
        device.submit(Action("touch_move", {"contact": 0, "x": 11, "y": 21}))
        device.submit(Action("touch_up", {"contact": 4}))
        device.release_all()
        self.assertEqual([call for call in library.calls if call[0] in ("down", "up")],
                         [("down", 1, 10, 20), ("down", 5, 30, 40),
                          ("down", 1, 11, 21), ("up", 5), ("up", 1)])
        device.close()
        self.assertIn(("disconnect", 7), library.calls)

    def test_mumu_failed_capture_and_release_do_not_claim_success(self):
        library = FakeMuMuLibrary()
        device = MuMuDevice("C:/fake/MuMu", 0, library=library)
        library.capture_error = 4
        with self.assertRaisesRegex(OSError, "size query failed: 4"):
            device.next_frame()
        library.capture_error = 0
        device.submit(Action("touch_down", {"contact": 1, "x": 1, "y": 2}))
        library.touch_error = 3
        with self.assertRaises(ExceptionGroup):
            device.release_all()
        self.assertIn(1, device._contacts)
        library.touch_error = 0
        device.close()
        self.assertIn(("up", 2), library.calls)

    def test_adb_screenshot_and_discrete_input_use_only_selected_serial(self):
        runner = FakeAdbRunner()
        device = AdbDevice("127.0.0.1:5555", adb_path="C:/fake/adb.exe", runner=runner)
        self.assertEqual(runner.calls, [])
        frame = device.next_frame(0.25)
        self.assertEqual(frame.image[0, 0].tolist(), [1, 2, 3])
        self.assertEqual(frame.sequence, 1)
        device.submit(Action("tap", {"x": 3, "y": 4}))
        device.submit(Action("swipe", {"x1": 1, "y1": 2, "x2": 5, "y2": 6,
                                       "duration_ms": 100}))
        device.submit(Action("keyevent", {"keycode": 4}))
        self.assertEqual(runner.calls[0],
                         (["C:/fake/adb.exe", "-s", "127.0.0.1:5555", "exec-out", "screencap", "-p"], 0.25))
        self.assertEqual(runner.calls[1][0][-5:], ["shell", "input", "tap", "3", "4"])
        self.assertNotIn("multitouch", device.capabilities)
        with self.assertRaises(ValueError):
            device.submit(Action("touch_down", {"contact": 0, "x": 1, "y": 2}))
        device.close()

    def test_adb_capture_failures_do_not_create_frames(self):
        runner = FakeAdbRunner()
        device = AdbDevice("serial", runner=runner)
        runner.png = b"not a PNG"
        with self.assertRaisesRegex(OSError, "no decodable PNG"):
            device.next_frame()
        self.assertEqual(device._sequence, 0)
        runner.fail = True
        with self.assertRaises(subprocess.CalledProcessError):
            device.next_frame()


if __name__ == "__main__":
    unittest.main()
