"""Task-scoped foreground capture used only during PC logout observation."""

from dataclasses import dataclass
import time

from ok.device.capture_methods.bitblt import ForegroundBitBltCaptureMethod
from ok.util.color import is_close_to_pure_color


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


class LogoutCaptureSession:
    def __init__(self, hwnd_window, exit_event, capture_factory=ForegroundBitBltCaptureMethod):
        self.hwnd_window = hwnd_window
        self.exit_event = exit_event
        self.capture = capture_factory(hwnd_window)
        self.capture.exit_event = exit_event
        self.last_reason = ""
        self.closed = False

    def capture_main(self):
        if self.closed:
            self.last_reason = "capture-session-closed"
            return None
        if not self.hwnd_window.is_foreground():
            self.last_reason = "main-window-not-foreground"
            return None
        try:
            frame = self.capture.get_frame()
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
        if not self.hwnd_window.is_foreground():
            self.last_reason = "foreground-changed-after-capture"
            return None
        origin = self.hwnd_window.get_capture_origin()
        if not origin:
            self.last_reason = "missing-capture-origin"
            return None
        self.last_reason = ""
        return CaptureSample(
            frame=frame,
            origin=(int(origin[0]), int(origin[1])),
            hwnd=int(self.hwnd_window.hwnd),
            source="foreground_bitblt",
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
