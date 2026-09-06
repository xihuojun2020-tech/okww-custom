import threading
import unittest

import numpy as np

from src.logout_capture import AccountSwitchCaptureSession, LogoutCaptureSession, _as_bgr


class FakeHwndWindow:
    hwnd = 77
    exists = True

    def is_foreground(self):
        return True


class CompositeHwndWindow(FakeHwndWindow):
    top_hwnd = 88
    hwnds = [(88,), (77,)]


class RefreshingHwndWindow(FakeHwndWindow):
    """Simulate the login dialog receiving a new top-level HWND/PID."""
    top_hwnd = 77
    hwnds = [(77,)]

    def __init__(self):
        self.refreshed = 0

    def do_update_window_size(self):
        self.refreshed += 1
        self.top_hwnd = 99
        self.hwnds = [(99,), (77,)]

class FakeCapture:
    def __init__(self, hwnd_window, frame, origin=(-1920, 0)):
        self.hwnd_window = hwnd_window
        self.frame = frame
        self.origin = origin
        self.exit_event = None
        self.closed = 0

    def get_frame(self):
        return self.frame, self.origin

    def close(self):
        self.closed += 1


class TestLogoutCapture(unittest.TestCase):
    def test_monitor_bitmap_drops_alpha_before_ocr(self):
        bgra = np.array([[[1, 2, 3, 4], [5, 6, 7, 8]]], dtype=np.uint8)

        bgr = _as_bgr(bgra)

        self.assertEqual((1, 2, 3), bgr.shape)
        np.testing.assert_array_equal(bgr, bgra[:, :, :3])
        self.assertTrue(bgr.flags.c_contiguous)
        self.assertFalse(np.shares_memory(bgr, bgra))

    def test_logout_name_remains_a_compatibility_alias(self):
        self.assertIs(AccountSwitchCaptureSession, LogoutCaptureSession)

    def test_valid_foreground_monitor_frame_returns_monitor_origin(self):
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        frame[20:40, 30:60] = 255
        created = []

        def factory(hwnd_window):
            capture = FakeCapture(hwnd_window, frame)
            created.append(capture)
            return capture

        session = LogoutCaptureSession(
            FakeHwndWindow(), threading.Event(), capture_factory=factory,
            foreground_hwnd=lambda: 88,
            window_pid=lambda hwnd: 900 if hwnd in (77, 88) else 0,
        )
        sample = session.capture_main()

        self.assertIs(frame, sample.frame)
        self.assertEqual((-1920, 0), sample.origin)
        self.assertEqual(88, sample.hwnd)
        self.assertEqual("foreground_monitor_bitblt", sample.source)
        session.close()
        session.close()
        self.assertEqual(1, created[0].closed)

    def test_pure_color_frame_is_rejected(self):
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        session = LogoutCaptureSession(
            FakeHwndWindow(), threading.Event(),
            capture_factory=lambda hwnd: FakeCapture(hwnd, frame),
            foreground_hwnd=lambda: 88,
            window_pid=lambda hwnd: 900 if hwnd in (77, 88) else 0,
        )
        self.assertIsNone(session.capture_main())
        self.assertEqual("pure-color-frame", session.last_reason)

    def test_foreground_popup_from_another_process_is_rejected(self):
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        frame[20:40, 30:60] = 255
        session = LogoutCaptureSession(
            FakeHwndWindow(), threading.Event(),
            capture_factory=lambda hwnd: FakeCapture(hwnd, frame),
            foreground_hwnd=lambda: 88,
            window_pid=lambda hwnd: 900 if hwnd == 77 else 901,
        )

        self.assertIsNone(session.capture_main())
        self.assertEqual("foreground-process-mismatch", session.last_reason)

    def test_untrusted_foreground_refreshes_replaced_login_handle_once(self):
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        frame[20:40, 30:60] = 255
        window = RefreshingHwndWindow()
        session = LogoutCaptureSession(
            window, threading.Event(),
            capture_factory=lambda hwnd: FakeCapture(hwnd, frame),
            foreground_hwnd=lambda: 99,
            window_pid=lambda hwnd: {77: 900, 99: 901}.get(hwnd, 0),
        )

        sample = session.capture_main()

        self.assertIsNotNone(sample)
        self.assertEqual(99, sample.hwnd)
        self.assertEqual(1, window.refreshed)
        self.assertIn(901, session.trusted_pids)

    def test_trusted_composite_login_process_is_accepted(self):
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        frame[20:40, 30:60] = 255
        session = LogoutCaptureSession(
            CompositeHwndWindow(), threading.Event(),
            capture_factory=lambda hwnd: FakeCapture(hwnd, frame),
            foreground_hwnd=lambda: 88,
            window_pid=lambda hwnd: {77: 900, 88: 901}.get(hwnd, 0),
        )

        sample = session.capture_main()

        self.assertIsNotNone(sample)
        self.assertEqual(88, sample.hwnd)

    def test_recently_trusted_composite_process_survives_handle_refresh(self):
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        frame[20:40, 30:60] = 255
        window = CompositeHwndWindow()
        session = LogoutCaptureSession(
            window, threading.Event(),
            capture_factory=lambda hwnd: FakeCapture(hwnd, frame),
            foreground_hwnd=lambda: 88,
            window_pid=lambda hwnd: {77: 900, 88: 901}.get(hwnd, 0),
        )

        self.assertIsNotNone(session.capture_main())
        window.top_hwnd = 77
        window.hwnds = [(77,)]

        self.assertIsNotNone(session.capture_main())
        self.assertEqual(88, session.capture_main().hwnd)

    def test_monitor_frame_must_match_reported_monitor_size(self):
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        frame[20:40, 30:60] = 255
        session = LogoutCaptureSession(
            FakeHwndWindow(), threading.Event(),
            capture_factory=lambda hwnd: FakeCapture(hwnd, frame, (-1920, 0, 1920, 1080)),
            foreground_hwnd=lambda: 77,
            window_pid=lambda hwnd: 900,
        )

        self.assertIsNone(session.capture_main())
        self.assertEqual("invalid-monitor-frame-size", session.last_reason)


if __name__ == "__main__":
    unittest.main()
