"""Verified foreground mouse delivery for the PC login workflow."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass


GA_ROOT = 2
GA_ROOTOWNER = 3
SW_RESTORE = 9
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


@dataclass(frozen=True)
class ForegroundResult:
    ready: bool
    reason: str
    target_hwnd: int
    foreground_hwnd: int
    expected_pid: int


@dataclass(frozen=True)
class LoginClickDelivery:
    delivered: bool
    reason: str
    target_hwnd: int
    foreground_hwnd: int
    hit_hwnd: int
    expected_pid: int
    point: tuple[int, int]


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


def _normalize_absolute_point(
    point: tuple[int, int],
    virtual_screen: tuple[int, int, int, int],
) -> tuple[int, int]:
    """Convert a screen point to SendInput's 0..65535 virtual-desktop space."""
    x, y = point
    left, top, width, height = virtual_screen
    if width <= 1 or height <= 1:
        raise ValueError("invalid virtual screen")
    normalized_x = round((x - left) * 65535 / (width - 1))
    normalized_y = round((y - top) * 65535 / (height - 1))
    return normalized_x, normalized_y


class _CtypesWin32Api:
    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.user32.WindowFromPoint.argtypes = [_POINT]
        self.user32.WindowFromPoint.restype = wintypes.HWND
        self.user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetClassNameW.restype = ctypes.c_int
        self.user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
        self.user32.SendInput.restype = wintypes.UINT

    def is_window(self, hwnd):
        return bool(self.user32.IsWindow(int(hwnd)))

    def is_window_visible(self, hwnd):
        return bool(self.user32.IsWindowVisible(int(hwnd)))

    def is_window_enabled(self, hwnd):
        return bool(self.user32.IsWindowEnabled(int(hwnd)))

    def window_thread_process_id(self, hwnd):
        pid = wintypes.DWORD()
        thread_id = self.user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
        return int(thread_id), int(pid.value)

    def root_owner(self, hwnd):
        return int(self.user32.GetAncestor(int(hwnd), GA_ROOTOWNER) or hwnd)

    def root_window(self, hwnd):
        return int(self.user32.GetAncestor(int(hwnd), GA_ROOT) or hwnd)

    def is_child(self, parent, child):
        return bool(self.user32.IsChild(int(parent), int(child)))

    def is_iconic(self, hwnd):
        return bool(self.user32.IsIconic(int(hwnd)))

    def restore_window(self, hwnd):
        return bool(self.user32.ShowWindow(int(hwnd), SW_RESTORE))

    def current_thread_id(self):
        return int(self.kernel32.GetCurrentThreadId())

    def get_foreground_window(self):
        return int(self.user32.GetForegroundWindow() or 0)

    def attach_thread_input(self, source, target, attach):
        return bool(self.user32.AttachThreadInput(int(source), int(target), bool(attach)))

    def bring_window_to_top(self, hwnd):
        return bool(self.user32.BringWindowToTop(int(hwnd)))

    def set_foreground_window(self, hwnd):
        return bool(self.user32.SetForegroundWindow(int(hwnd)))

    def window_rect(self, hwnd):
        rect = wintypes.RECT()
        if not self.user32.GetWindowRect(int(hwnd), ctypes.byref(rect)):
            raise OSError(ctypes.get_last_error(), "GetWindowRect failed")
        return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)

    def virtual_screen(self):
        return (
            int(self.user32.GetSystemMetrics(SM_XVIRTUALSCREEN)),
            int(self.user32.GetSystemMetrics(SM_YVIRTUALSCREEN)),
            int(self.user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
            int(self.user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
        )

    def window_from_point(self, point):
        return int(self.user32.WindowFromPoint(_POINT(int(point[0]), int(point[1]))) or 0)

    def window_class(self, hwnd):
        buffer = ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(int(hwnd), buffer, len(buffer))
        return buffer.value

    def send_mouse_click(self, point, virtual_screen):
        dx, dy = _normalize_absolute_point(point, virtual_screen)
        inputs = (_INPUT * 3)(
            _INPUT(
                type=INPUT_MOUSE,
                mi=_MOUSEINPUT(
                    dx=dx,
                    dy=dy,
                    mouseData=0,
                    dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                    time=0,
                    dwExtraInfo=0,
                ),
            ),
            _INPUT(
                type=INPUT_MOUSE,
                mi=_MOUSEINPUT(
                    dx=0,
                    dy=0,
                    mouseData=0,
                    dwFlags=MOUSEEVENTF_LEFTDOWN,
                    time=0,
                    dwExtraInfo=0,
                ),
            ),
            _INPUT(
                type=INPUT_MOUSE,
                mi=_MOUSEINPUT(
                    dx=0,
                    dy=0,
                    mouseData=0,
                    dwFlags=MOUSEEVENTF_LEFTUP,
                    time=0,
                    dwExtraInfo=0,
                ),
            ),
        )
        return int(self.user32.SendInput(len(inputs), inputs, ctypes.sizeof(_INPUT)))


def _window_reason(api, hwnd: int, expected_pid: int) -> str | None:
    if not hwnd or not api.is_window(hwnd):
        return "target-invalid"
    if not api.is_window_visible(hwnd):
        return "target-not-visible"
    if not api.is_window_enabled(hwnd):
        return "target-disabled"
    _thread_id, pid = api.window_thread_process_id(hwnd)
    if pid != expected_pid:
        return "target-pid-mismatch"
    return None


def _same_window_tree(api, left: int, right: int) -> bool:
    if not left or not right:
        return False
    if left == right or api.is_child(left, right) or api.is_child(right, left):
        return True
    return api.root_owner(left) == api.root_owner(right)


def force_foreground(
    target_hwnd: int,
    expected_pid: int,
    *,
    api=None,
) -> ForegroundResult:
    """Bring the target's own top-level window forward and verify foreground."""
    api = api or _CtypesWin32Api()
    target_hwnd = int(target_hwnd or 0)
    expected_pid = int(expected_pid or 0)
    reason = _window_reason(api, target_hwnd, expected_pid)
    foreground = int(api.get_foreground_window() or 0)
    if reason:
        return ForegroundResult(False, reason, target_hwnd, foreground, expected_pid)

    root = int(api.root_window(target_hwnd) or target_hwnd)
    root_reason = _window_reason(api, root, expected_pid)
    if root_reason:
        return ForegroundResult(False, root_reason, target_hwnd, foreground, expected_pid)
    if foreground and api.is_window(foreground):
        _foreground_thread, foreground_pid = api.window_thread_process_id(foreground)
        if (foreground_pid == expected_pid
                and int(api.root_window(foreground) or foreground) == root):
            return ForegroundResult(True, "foreground-ready", target_hwnd, foreground, expected_pid)
        # Native ComboLBox popups can be owned by the desktop window tree even
        # though their PID is the game's.  Keeping that verified popup in front
        # avoids collapsing the open account list before WindowFromPoint and
        # SendInput validate the intended item.
        if foreground_pid == expected_pid and api.window_class(foreground) == "ComboLBox":
            return ForegroundResult(True, "foreground-combo-popup-ready", target_hwnd,
                                    foreground, expected_pid)

    if api.is_iconic(root):
        api.restore_window(root)

    current_thread = int(api.current_thread_id() or 0)
    target_thread, _target_pid = api.window_thread_process_id(root)
    foreground_thread = 0
    if foreground and api.is_window(foreground):
        foreground_thread, _foreground_pid = api.window_thread_process_id(foreground)

    attached_pairs = []
    for other_thread in dict.fromkeys((target_thread, foreground_thread)):
        if not current_thread or not other_thread or current_thread == other_thread:
            continue
        if api.attach_thread_input(current_thread, other_thread, True):
            attached_pairs.append((current_thread, other_thread))
    try:
        api.bring_window_to_top(root)
        api.set_foreground_window(root)
    finally:
        for source, target in reversed(attached_pairs):
            api.attach_thread_input(source, target, False)

    foreground = int(api.get_foreground_window() or 0)
    if foreground and api.is_window(foreground):
        _thread_id, foreground_pid = api.window_thread_process_id(foreground)
        if (foreground_pid == expected_pid
                and int(api.root_window(foreground) or foreground) == root):
            return ForegroundResult(True, "foreground-ready", target_hwnd, foreground, expected_pid)
    return ForegroundResult(False, "foreground-mismatch", target_hwnd, foreground, expected_pid)


def _contains(rect: tuple[int, int, int, int], point: tuple[int, int]) -> bool:
    left, top, right, bottom = rect
    x, y = point
    return left <= x < right and top <= y < bottom


def _delivery(
    delivered: bool,
    reason: str,
    target_hwnd: int,
    foreground_hwnd: int,
    hit_hwnd: int,
    expected_pid: int,
    point: tuple[int, int],
) -> LoginClickDelivery:
    return LoginClickDelivery(
        delivered,
        reason,
        int(target_hwnd or 0),
        int(foreground_hwnd or 0),
        int(hit_hwnd or 0),
        int(expected_pid or 0),
        (int(point[0]), int(point[1])),
    )


def send_input_click(
    target_hwnd: int,
    expected_pid: int,
    point: tuple[int, int],
    *,
    api=None,
) -> LoginClickDelivery:
    """Validate a login target and deliver one physical left click with SendInput."""
    api = api or _CtypesWin32Api()
    target_hwnd = int(target_hwnd or 0)
    expected_pid = int(expected_pid or 0)
    point = int(point[0]), int(point[1])
    foreground = int(api.get_foreground_window() or 0)
    virtual_screen = api.virtual_screen()
    virtual_rect = (
        virtual_screen[0],
        virtual_screen[1],
        virtual_screen[0] + virtual_screen[2],
        virtual_screen[1] + virtual_screen[3],
    )
    if virtual_screen[2] <= 1 or virtual_screen[3] <= 1 or not _contains(virtual_rect, point):
        return _delivery(False, "point-outside-virtual-screen", target_hwnd, foreground, 0,
                         expected_pid, point)

    front = force_foreground(target_hwnd, expected_pid, api=api)
    if not front.ready:
        return _delivery(False, front.reason, target_hwnd, front.foreground_hwnd, 0,
                         expected_pid, point)

    reason = _window_reason(api, target_hwnd, expected_pid)
    if reason:
        return _delivery(False, reason, target_hwnd, front.foreground_hwnd, 0,
                         expected_pid, point)
    hit_hwnd = int(api.window_from_point(point) or 0)
    if not hit_hwnd or not api.is_window(hit_hwnd):
        return _delivery(False, "point-no-window", target_hwnd, front.foreground_hwnd, hit_hwnd,
                         expected_pid, point)
    _hit_thread, hit_pid = api.window_thread_process_id(hit_hwnd)
    if hit_pid != expected_pid:
        return _delivery(False, "point-pid-mismatch", target_hwnd, front.foreground_hwnd, hit_hwnd,
                         expected_pid, point)
    hit_is_combo_popup = api.window_class(hit_hwnd) == "ComboLBox"
    if not _same_window_tree(api, target_hwnd, hit_hwnd) and not hit_is_combo_popup:
        return _delivery(False, "point-target-mismatch", target_hwnd, front.foreground_hwnd, hit_hwnd,
                         expected_pid, point)

    # A native combo dropdown is a top-level popup.  Its list rows can be
    # outside the selector/#32770 rectangle even though WindowFromPoint has
    # already proved that the point is in the same-process ComboLBox.  Check
    # the parent bounds only for ordinary child controls; otherwise the old
    # ordering rejected every valid row as ``point-outside-target``.
    try:
        target_rect = api.window_rect(target_hwnd)
    except Exception:
        return _delivery(False, "target-rect-unavailable", target_hwnd, front.foreground_hwnd, hit_hwnd,
                         expected_pid, point)
    if not _contains(target_rect, point) and not hit_is_combo_popup:
        return _delivery(False, "point-outside-target", target_hwnd, front.foreground_hwnd, hit_hwnd,
                         expected_pid, point)

    try:
        sent = int(api.send_mouse_click(point, virtual_screen))
    except Exception as error:
        reason = f"sendinput-error-{type(error).__name__}"
        return _delivery(False, reason, target_hwnd, front.foreground_hwnd, hit_hwnd,
                         expected_pid, point)
    if sent != 3:
        return _delivery(False, f"sendinput-partial-{sent}-of-3", target_hwnd,
                         front.foreground_hwnd, hit_hwnd, expected_pid, point)
    return _delivery(True, "delivered", target_hwnd, front.foreground_hwnd, hit_hwnd,
                     expected_pid, point)


__all__ = [
    "ForegroundResult",
    "LoginClickDelivery",
    "force_foreground",
    "send_input_click",
]
