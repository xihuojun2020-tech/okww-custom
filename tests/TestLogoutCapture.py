import threading
import unittest

import numpy as np

from src.logout_capture import LogoutCaptureSession


class FakeHwndWindow:
    hwnd = 77
    exists = True

    def is_foreground(self):
        return True

    def get_capture_origin(self):
        return 100, 200


class FakeCapture:
    def __init__(self, hwnd_window, frame):
        self.hwnd_window = hwnd_window
        self.frame = frame
        self.exit_event = None
        self.closed = 0

    def get_frame(self):
        return self.frame

    def close(self):
        self.closed += 1


class TestLogoutCapture(unittest.TestCase):
    def test_valid_foreground_frame_returns_live_origin(self):
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        frame[20:40, 30:60] = 255
        created = []

        def factory(hwnd_window):
            capture = FakeCapture(hwnd_window, frame)
            created.append(capture)
            return capture

        session = LogoutCaptureSession(
            FakeHwndWindow(), threading.Event(), capture_factory=factory,
        )
        sample = session.capture_main()

        self.assertIs(frame, sample.frame)
        self.assertEqual((100, 200), sample.origin)
        self.assertEqual(77, sample.hwnd)
        self.assertEqual("foreground_bitblt", sample.source)
        session.close()
        session.close()
        self.assertEqual(1, created[0].closed)

    def test_pure_color_frame_is_rejected(self):
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        session = LogoutCaptureSession(
            FakeHwndWindow(), threading.Event(),
            capture_factory=lambda hwnd: FakeCapture(hwnd, frame),
        )
        self.assertIsNone(session.capture_main())
        self.assertEqual("pure-color-frame", session.last_reason)


if __name__ == "__main__":
    unittest.main()
