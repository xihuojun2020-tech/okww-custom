"""Task-scoped foreground capture used during one PC account transition."""

from dataclasses import dataclass
import threading
import time

import numpy as np
import win32api
import win32con
import win32gui
import win32process
import win32ui

from ok.util.color import is_close_to_pure_color

CAPTUREBLT = 0x40000000


def _as_bgr(frame):
    """Detach desktop BGRA pixels and remove alpha for OCR/feature consumers."""
    if getattr(frame, "ndim", 0) == 3 and frame.shape[2] == 4:
        return np.ascontiguousarray(frame[:, :, :3])
    return frame


@dataclass(frozen=True)
class CaptureSample:
    frame: object
    origin: tuple[int, int]
    hwnd: int
    source: str
    captured_at: float


@dataclass(frozen=True)
class ObservedBox:
    box: object
    sample: CaptureSample


class MonitorBitBltCapture:
    """Capture the final desktop pixels of the monitor containing the game."""

    def __init__(self, hwnd_window):
        self.hwnd_window = hwnd_window
        self.exit_event = None
        self.lock = threading.Lock()
        self.window_dc = None
        self.dc_object = None
        self.compatible_dc = None
        self.bitmap = None
        self.size = None

    def _close_unlocked(self):
        if self.compatible_dc is not None:
            try:
                self.compatible_dc.DeleteDC()
            except Exception:
                pass
        if self.dc_object is not None:
            try:
                self.dc_object.DeleteDC()
            except Exception:
                pass
        if self.window_dc is not None:
            try:
                win32gui.ReleaseDC(0, self.window_dc)
            except Exception:
                pass
        if self.bitmap is not None:
            try:
                win32gui.DeleteObject(self.bitmap.GetHandle())
            except Exception:
                pass
        self.window_dc = self.dc_object = self.compatible_dc = self.bitmap = None
        self.size = None

    def get_frame(self):
        monitor = win32api.MonitorFromWindow(
            int(self.hwnd_window.hwnd), win32con.MONITOR_DEFAULTTONEAREST,
        )
        left, top, right, bottom = win32api.GetMonitorInfo(monitor)['Monitor']
        width, height = right - left, bottom - top
        if width <= 10 or height <= 10:
            return None, (left, top, right, bottom)
        with self.lock:
            if self.size != (width, height):
                self._close_unlocked()
                self.window_dc = win32gui.GetDC(0)
                self.dc_object = win32ui.CreateDCFromHandle(self.window_dc)
                self.compatible_dc = self.dc_object.CreateCompatibleDC()
                self.bitmap = win32ui.CreateBitmap()
                self.bitmap.CreateCompatibleBitmap(self.dc_object, width, height)
                self.size = (width, height)
            self.compatible_dc.SelectObject(self.bitmap)
            self.compatible_dc.BitBlt(
                (0, 0), (width, height), self.dc_object, (left, top),
                win32con.SRCCOPY | CAPTUREBLT,
            )
            image = np.frombuffer(self.bitmap.GetBitmapBits(True), dtype=np.uint8)
            image.shape = (height, width, 4)
            return _as_bgr(image), (left, top, right, bottom)

    def close(self):
        with self.lock:
            self._close_unlocked()


class AccountSwitchCaptureSession:
    def __init__(self, hwnd_window, exit_event, capture_factory=MonitorBitBltCapture,
                 foreground_hwnd=win32gui.GetForegroundWindow,
                 window_pid=lambda hwnd: win32process.GetWindowThreadProcessId(hwnd)[1]):
        self.hwnd_window = hwnd_window
        self.exit_event = exit_event
        self.capture = capture_factory(hwnd_window)
        self.capture.exit_event = exit_event
        self.foreground_hwnd = foreground_hwnd
        self.window_pid = window_pid
        self.last_reason = ""
        self.closed = False
        self.trusted_pids = set()

    def _window_handles(self):
        """Return the current trusted game/login window handles."""
        handles = [
            getattr(self.hwnd_window, "top_hwnd", 0),
            getattr(self.hwnd_window, "hwnd", 0),
        ]
        for item in getattr(self.hwnd_window, "hwnds", None) or []:
            handles.append(item[0] if isinstance(item, (tuple, list)) else item)
        return tuple(dict.fromkeys(int(hwnd or 0) for hwnd in handles if hwnd))

    def _refresh_trusted_pids(self):
        for hwnd in self._window_handles():
            try:
                pid = int(self.window_pid(hwnd) or 0)
            except Exception:
                pid = 0
            if pid:
                self.trusted_pids.add(pid)
        return self.trusted_pids

    def _refresh_window_snapshot(self):
        """Refresh handles when the loginer replaced its top-level window.

        The PC login flow can swap the game surface for an independent login
        dialog without changing the capture session object.  HwndWindow polls
        this transition in its own thread, but BitBlt may sample in the small
        interval before that poll.  Refresh only on an untrusted foreground so
        the normal capture path keeps its low overhead.
        """
        refresh = getattr(self.hwnd_window, "do_update_window_size", None)
        if not callable(refresh):
            return False
        try:
            refresh()
            self._refresh_trusted_pids()
            return True
        except Exception:
            return False

    def pid_for(self, hwnd):
        try:
            return int(self.window_pid(int(hwnd or 0)) or 0)
        except Exception:
            return 0

    def is_trusted_hwnd(self, hwnd):
        pid = self.pid_for(hwnd)
        return bool(pid and pid in self._refresh_trusted_pids())

    def preferred_hwnd(self):
        self._refresh_trusted_pids()
        foreground = int(self.foreground_hwnd() or 0)
        if self.is_trusted_hwnd(foreground):
            return foreground
        for hwnd in self._window_handles():
            if self.is_trusted_hwnd(hwnd):
                return hwnd
        return 0

    def capture_main(self):
        if self.closed:
            self.last_reason = "capture-session-closed"
            return None
        foreground = int(self.foreground_hwnd() or 0)
        if not foreground or not self.is_trusted_hwnd(foreground):
            # A newly-created login dialog may not be present in HwndWindow's
            # handle snapshot yet.  One bounded refresh closes that race while
            # retaining the same-process PID allow-list safety check.
            self._refresh_window_snapshot()
            foreground = int(self.foreground_hwnd() or 0)
            if not foreground or not self.is_trusted_hwnd(foreground):
                self.last_reason = "foreground-process-mismatch"
                return None
        try:
            frame, monitor_rect = self.capture.get_frame()
        except Exception as error:
            self.last_reason = f"capture-error-{type(error).__name__}"
            return None
        if frame is None:
            self.last_reason = "empty-frame"
            return None
        if getattr(frame, "ndim", 0) < 2 or frame.shape[0] <= 10 or frame.shape[1] <= 10:
            self.last_reason = "invalid-frame-size"
            return None
        if is_close_to_pure_color(frame):
            self.last_reason = "pure-color-frame"
            return None
        if len(monitor_rect) == 4:
            left, top, right, bottom = monitor_rect
            if frame.shape[:2] != (bottom - top, right - left):
                self.last_reason = "invalid-monitor-frame-size"
                return None
            origin = left, top
        else:
            origin = monitor_rect
        foreground = int(self.foreground_hwnd() or 0)
        if not foreground or not self.is_trusted_hwnd(foreground):
            self._refresh_window_snapshot()
            foreground = int(self.foreground_hwnd() or 0)
            if not foreground or not self.is_trusted_hwnd(foreground):
                self.last_reason = "foreground-process-changed-after-capture"
                return None
        if not origin:
            self.last_reason = "missing-capture-origin"
            return None
        self.last_reason = ""
        return CaptureSample(
            frame=frame,
            origin=(int(origin[0]), int(origin[1])),
            hwnd=foreground,
            source="foreground_monitor_bitblt",
            captured_at=time.monotonic(),
        )

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.capture.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False


# Compatibility for the already released logout-only callers and tests.
LogoutCaptureSession = AccountSwitchCaptureSession
