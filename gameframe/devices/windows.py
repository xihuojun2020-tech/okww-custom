"""HWND WGC capture and same-session Windows SendInput delivery."""

from __future__ import annotations

import ctypes
import os
import struct
import subprocess
import threading
import time
from contextlib import contextmanager
from ctypes import wintypes

import numpy as np

from gameframe.api import Action, Cancelled, Frame
from gameframe.process_ownership import register_device_process


INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_WHEEL = 0x0800
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
DWMWA_EXTENDED_FRAME_BOUNDS = 9
BUTTON_FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}
NAMED_KEYS = {
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "backspace": 0x08, "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
    "lshift": 0xA0, "rshift": 0xA1, "lctrl": 0xA2, "rctrl": 0xA3,
    "lalt": 0xA4, "ralt": 0xA5, "left": 0x25, "up": 0x26,
    "right": 0x27, "down": 0x28,
    **{f"f{number}": 0x6F + number for number in range(1, 25)},
}


def virtual_key(key):
    if isinstance(key, str):
        name = key.lower()
        if name in NAMED_KEYS:
            return NAMED_KEYS[name]
        if len(key) == 1 and key.isascii() and key.isalnum():
            return ord(key.upper())
        raise ValueError(f"Unsupported key name: {key}")
    return int(key)


class _Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


def enumerate_windows():
    """Read visible top-level HWND metadata only when explicitly requested."""
    import win32gui
    import win32process

    windows = []

    def collect(hwnd, _):
        title = win32gui.GetWindowText(hwnd)
        if win32gui.IsWindowVisible(hwnd) and title:
            windows.append({'hwnd': hwnd, 'title': title,
                            'pid': win32process.GetWindowThreadProcessId(hwnd)[1]})
        return True

    win32gui.EnumWindows(collect, None)
    return windows


class _WindowBackend:
    def __init__(self):
        import win32api
        import win32gui
        import win32process
        self.api, self.gui, self.process = win32api, win32gui, win32process
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.user32.SetThreadDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
        self.user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p

    def exists(self, hwnd):
        return bool(self.gui.IsWindow(hwnd))

    def pid(self, hwnd):
        return self.process.GetWindowThreadProcessId(hwnd)[1]

    def process_created(self, pid):
        import psutil
        return psutil.Process(pid).create_time()

    def foreground(self):
        return self.gui.GetForegroundWindow()

    def title(self, hwnd):
        return self.gui.GetWindowText(hwnd)

    def is_visible(self, hwnd):
        return bool(self.gui.IsWindowVisible(hwnd))

    def windows(self, pid):
        windows = []
        def collect(hwnd, _):
            if self.pid(hwnd) == pid:
                windows.append(hwnd)
            return True
        self.gui.EnumWindows(collect, None)
        return windows

    def root(self, hwnd):
        return self.gui.GetAncestor(hwnd, 2)  # GA_ROOT

    def client_to_screen(self, hwnd, x, y):
        with _physical_coordinates(self.user32):
            return self.gui.ClientToScreen(hwnd, (int(x), int(y)))

    def cursor(self):
        with _physical_coordinates(self.user32):
            return self.gui.GetCursorPos()

    def set_cursor(self, position):
        with _physical_coordinates(self.user32):
            self.api.SetCursorPos(position)

    def hotkey_pressed(self, vk):
        return bool(self.api.GetAsyncKeyState(vk) & 0x8000)


class WindowsWindow:
    """Live metadata for the selected HWND and its process's login dialogs."""

    def __init__(self, device, backend):
        self.device, self.backend = device, backend
        self._pid = backend.pid(device.hwnd)
        self._process_created = backend.process_created(self._pid)
        self.hwnds = []
        self.do_update_window_size()

    @property
    def hwnd(self):
        return self.device.hwnd

    @property
    def exists(self):
        return self.backend.exists(self.hwnd)

    @property
    def visible(self):
        return self.exists and self.backend.foreground() in (self.hwnd, self.top_hwnd)

    @property
    def hwnd_title(self):
        return self.backend.title(self.hwnd)

    @property
    def top_hwnd(self):
        foreground = self.backend.foreground()
        if foreground and self.backend.pid(foreground) == self._pid:
            return foreground
        return self.backend.root(self.hwnd)

    def get_capture_origin(self):
        return self.backend.client_to_screen(self.hwnd, 0, 0)

    def do_update_window_size(self):
        self.hwnds = self.backend.windows(self._pid)

    def bind(self, hwnd):
        self.device.hwnd = hwnd
        self._pid = self.backend.pid(hwnd)
        self._process_created = self.backend.process_created(self._pid)
        self.do_update_window_size()

    def bring_to_front(self):
        self.device.submit(Action('activate', {}))
        return self.device.is_foreground()


def _client_roi(bounds, client, origin, frame_width, frame_height):
    if (bounds.right - bounds.left, bounds.bottom - bounds.top) != (frame_width, frame_height):
        raise OSError("WGC frame size does not match physical DWM window bounds")
    left, top = origin.x - bounds.left, origin.y - bounds.top
    right, bottom = left + client.right - client.left, top + client.bottom - client.top
    if not (0 <= left < right <= frame_width and 0 <= top < bottom <= frame_height):
        raise OSError("Client area falls outside WGC window frame")
    return left, top, right, bottom


@contextmanager
def _physical_coordinates(user32):
    # DWM bounds are physical pixels. Match ClientToScreen/GetClientRect to them
    # without changing the whole process's DPI awareness.
    previous = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    if not previous:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        if not user32.SetThreadDpiAwarenessContext(previous):
            raise ctypes.WinError(ctypes.get_last_error())


class _Win32Geometry:
    def __init__(self):
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
        self._user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        self._user32.GetClientRect.restype = wintypes.BOOL
        self._user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(_Point))
        self._user32.ClientToScreen.restype = wintypes.BOOL
        self._user32.SetThreadDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
        self._user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        self._dwm.DwmGetWindowAttribute.argtypes = (wintypes.HWND, wintypes.DWORD,
                                                  ctypes.c_void_p, wintypes.DWORD)
        self._dwm.DwmGetWindowAttribute.restype = ctypes.c_long

    def client_rect_in_frame(self, hwnd: int, frame_width: int, frame_height: int):
        bounds, client, origin = wintypes.RECT(), wintypes.RECT(), _Point(0, 0)
        with _physical_coordinates(self._user32):
            result = self._dwm.DwmGetWindowAttribute(
                hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(bounds), ctypes.sizeof(bounds))
            if result != 0:
                raise OSError(f"DwmGetWindowAttribute failed: HRESULT {result:#x}")
            if not self._user32.GetClientRect(hwnd, ctypes.byref(client)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not self._user32.ClientToScreen(hwnd, ctypes.byref(origin)):
                raise ctypes.WinError(ctypes.get_last_error())
        return _client_roi(bounds, client, origin, frame_width, frame_height)


class _MouseInput(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _KeyboardInput(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _InputUnion(ctypes.Union):
    _fields_ = [("mi", _MouseInput), ("ki", _KeyboardInput)]


class _Input(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("type", wintypes.DWORD), ("value", _InputUnion)]


class _SendInput:
    """SendInput targets the foreground desktop session, never an isolated HWND."""

    def __init__(self):
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int)
        self._user32.SendInput.restype = wintypes.UINT
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
        self._user32.SetForegroundWindow.restype = wintypes.BOOL
        self._user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(_Point))
        self._user32.ClientToScreen.restype = wintypes.BOOL
        self._user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
        self._user32.GetSystemMetrics.restype = ctypes.c_int
        self._user32.SetThreadDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
        self._user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p

    def is_foreground(self, hwnd: int) -> bool:
        return int(self._user32.GetForegroundWindow() or 0) == hwnd

    def activate(self, hwnd: int) -> None:
        # Windows may reject activation under its foreground-lock rules.
        if not self._user32.SetForegroundWindow(hwnd):
            raise RuntimeError('Windows rejected SetForegroundWindow for target HWND')

    def _send(self, item: _Input) -> None:
        if self._user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(_Input)) != 1:
            raise ctypes.WinError(ctypes.get_last_error())

    def key(self, vk: int, down: bool) -> None:
        self._send(_Input(type=INPUT_KEYBOARD, ki=_KeyboardInput(vk, 0, 0 if down else KEYEVENTF_KEYUP, 0, 0)))

    def unicode_key(self, scan: int, down: bool) -> None:
        flags = KEYEVENTF_UNICODE | (0 if down else KEYEVENTF_KEYUP)
        self._send(_Input(type=INPUT_KEYBOARD, ki=_KeyboardInput(0, scan, flags, 0, 0)))

    def scroll(self, clicks: int) -> None:
        self._send(_Input(type=INPUT_MOUSE, mi=_MouseInput(0, 0, clicks * 120, MOUSEEVENTF_WHEEL, 0, 0)))

    def button(self, button: str, down: bool) -> None:
        flag = BUTTON_FLAGS[button][0 if down else 1]
        self._send(_Input(type=INPUT_MOUSE, mi=_MouseInput(0, 0, 0, flag, 0, 0)))

    def move_relative(self, dx: int, dy: int) -> None:
        self._send(_Input(type=INPUT_MOUSE, mi=_MouseInput(dx, dy, 0, MOUSEEVENTF_MOVE, 0, 0)))

    def move_client(self, hwnd: int, x: int, y: int) -> None:
        point = _Point(x, y)
        with _physical_coordinates(self._user32):
            if not self._user32.ClientToScreen(hwnd, ctypes.byref(point)):
                raise ctypes.WinError(ctypes.get_last_error())
            left = self._user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            top = self._user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            width = self._user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            height = self._user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        if width <= 1 or height <= 1:
            raise OSError("Invalid virtual desktop dimensions")
        dx = round((point.x - left) * 65535 / (width - 1))
        dy = round((point.y - top) * 65535 / (height - 1))
        if not (0 <= dx <= 65535 and 0 <= dy <= 65535):
            raise ValueError("Client point is outside the virtual desktop")
        self._send(_Input(type=INPUT_MOUSE, mi=_MouseInput(
            dx, dy, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, 0, 0)))


class WindowsDevice:
    """Owns the latest HWND frame and held same-session keys/buttons.

    Action values: key_down/up {key: virtual-key int, ASCII letter/digit or named key},
    button_down/up {button: left|right|middle}, move_relative {dx, dy},
    move_client {x, y} in HWND client coordinates,
    scroll {clicks} in signed wheel detents, text {text} as UTF-16 Unicode input,
    click {x, y, button?: left|right|middle} in HWND client coordinates,
    activate {} requests foreground ownership under Windows activation rules.
    SendInput requires the target to be foreground.
    """

    capabilities = frozenset({"frames", "keyboard", "mouse", "relative-mouse", "scroll", "text", "activate",
                              'foreground-query', 'hotkey-query'})

    def __init__(self, hwnd: int = 0, *, capture_factory=None, input_backend=None, geometry=None,
                 window_backend=None, process_factory=None, launch_factory=None,
                 launch_command=None, target_executable=None):
        if hwnd < 0:
            raise ValueError("HWND cannot be negative")
        self.hwnd = hwnd
        self._capture_factory = capture_factory
        self._input_backend = input_backend
        self._geometry = geometry
        self._window_backend = window_backend
        self._window = None
        self._process_factory = process_factory
        self._launch_factory = launch_factory
        if launch_command is not None or target_executable is not None:
            if (not isinstance(launch_command, (list, tuple)) or not launch_command or
                    not all(isinstance(item, str) and item for item in launch_command) or
                    not os.path.isabs(launch_command[0]) or
                    not isinstance(target_executable, str) or not os.path.isabs(target_executable)):
                raise ValueError('Windows launch requires an absolute launch_command and target_executable')
        self.launch_command = list(launch_command) if launch_command is not None else None
        self.target_executable = os.path.normcase(os.path.abspath(target_executable)) if target_executable else None
        if not hwnd and self.launch_command is None:
            raise ValueError('Windows requires a positive HWND or complete launch configuration')
        self._condition = threading.Condition()
        self._capture = None
        self._control = None
        self._capture_closed = False
        self._closed = False
        self._latest = None
        self._sequence = 0
        self._delivered = 0
        self._keys = set()
        self._unicode_keys = set()
        self._buttons = set()

    def _platform(self):
        if self._window_backend is None:
            self._window_backend = _WindowBackend()
        return self._window_backend

    @property
    def window(self):
        if self._window is None:
            self._window = WindowsWindow(self, self._platform())
        return self._window

    def is_foreground(self):
        if self._input_backend is None:
            self._input_backend = _SendInput()
        return self._input_backend.is_foreground(self.hwnd)

    def get_cursor_pos(self):
        return self._platform().cursor()

    def set_cursor_pos(self, position):
        self._platform().set_cursor(position)

    def client_to_screen(self, x, y):
        return self._platform().client_to_screen(self.hwnd, x, y)

    def hotkey_pressed(self, vk):
        return self._platform().hotkey_pressed(vk)

    def foreground_pid(self):
        platform = self._platform()
        hwnd = platform.foreground()
        return platform.pid(hwnd) if hwnd else 0

    def stop_target(self):
        """End only the live process owning the selected trusted HWND."""
        window = self.window
        platform = self._platform()
        if not window.exists or platform.pid(self.hwnd) != window._pid:
            raise RuntimeError('Selected HWND no longer belongs to the trusted game process')
        if self._process_factory is None:
            import psutil
            self._process_factory = psutil.Process
        process = self._process_factory(window._pid)
        if process.create_time() != window._process_created:
            raise RuntimeError('Selected game process identity has been reused')
        # Check again after acquiring psutil's process identity. Its kill method
        # additionally checks PID reuse before delivering the termination.
        if not window.exists or platform.pid(self.hwnd) != process.pid:
            raise RuntimeError('Selected HWND process changed before termination')
        self.release_all()
        process.kill()
        process.wait(timeout=10)

    def _discard_capture(self):
        try:
            if self._control is not None:
                self._control.stop()
                self._control.wait()
        finally:
            with self._condition:
                self._capture = self._control = self._latest = None
                self._capture_closed = False
                self._delivered = self._sequence

    def _bind_window(self, hwnd):
        self._discard_capture()
        self.release_all()
        if self._window is None:
            self.hwnd = hwnd
            self._window = WindowsWindow(self, self._platform())
        else:
            self._window.bind(hwnd)

    def prepare(self, stop):
        if not self.hwnd:
            self.start_target(stop)

    def refresh_target(self):
        window = self.window
        window.do_update_window_size()
        if window.exists:
            if (self._platform().pid(window.hwnd) != window._pid or
                    self._platform().process_created(window._pid) != window._process_created):
                raise RuntimeError('Selected game window or process identity has been reused')
            return True
        self._discard_capture()
        candidates = [hwnd for hwnd in window.hwnds if self._platform().is_visible(hwnd)]
        if len(candidates) > 1:
            raise RuntimeError('Multiple replacement windows belong to the selected process')
        if not candidates:
            return False
        if self._platform().process_created(window._pid) != window._process_created:
            raise RuntimeError('Selected game process identity has been reused')
        self._bind_window(candidates[0])
        return True

    def start_capture(self):
        if not self.window.exists:
            raise RuntimeError('Selected HWND does not exist; configure a launch command to start the game')
        self._start()
        return True

    def start_target(self, stop, timeout=30):
        if self.launch_command is None:
            raise RuntimeError('Starting the game requires launch_command and target_executable device configuration')
        if stop.is_set():
            raise Cancelled('Game launch stopped')
        if self._process_factory is None:
            import psutil
            self._process_factory = psutil.Process
        if self._launch_factory is None:
            options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
            launched = subprocess.Popen(self.launch_command, shell=False, **options)
        else:
            launched = self._launch_factory(self.launch_command)
        import psutil
        try:
            launcher = self._process_factory(launched.pid)
        except psutil.NoSuchProcess as error:
            raise RuntimeError('Launcher exited before its process family could be recorded') from error
        register_device_process(launcher)
        # Retain process objects once observed; a launcher may exit before its
        # child creates the actual game window.
        processes = {launcher.pid: launcher}
        deadline = time.monotonic() + timeout
        while True:
            if stop.is_set():
                raise Cancelled('Game launch stopped while waiting for its window')
            for process in tuple(processes.values()):
                try:
                    children = process.children(recursive=True)
                except psutil.NoSuchProcess:
                    if process is launcher and len(processes) == 1:
                        raise RuntimeError('Launcher exited before its process family could be recorded')
                    children = []
                for child in children:
                    register_device_process(child)
                    processes[child.pid] = child
            candidates = []
            for process in processes.values():
                try:
                    if not process.is_running() or os.path.normcase(os.path.abspath(process.exe())) != self.target_executable:
                        continue
                except psutil.NoSuchProcess:
                    continue
                candidates.extend(hwnd for hwnd in self._platform().windows(process.pid)
                                  if self._platform().is_visible(hwnd))
            if len(candidates) > 1:
                raise RuntimeError('Multiple windows match the launched target executable')
            if candidates:
                self._bind_window(candidates[0])
                return True
            if time.monotonic() >= deadline:
                raise TimeoutError('Launched process family did not create a unique target window')
            stop.wait(min(.1, max(0, deadline - time.monotonic())))

    def _start(self) -> None:
        if self._capture is not None:
            return
        if self._capture_factory is None:
            from windows_capture import WindowsCapture  # Optional dependency, loaded only when capturing.
            factory = WindowsCapture
        else:
            factory = self._capture_factory
        capture = factory(window_hwnd=self.hwnd, cursor_capture=False)

        @capture.event
        def on_frame_arrived(frame, capture_control):
            # WGC's BGRA array may be recycled when this callback returns.
            if self._geometry is None:
                self._geometry = _Win32Geometry()
            raw = frame.frame_buffer
            left, top, right, bottom = self._geometry.client_rect_in_frame(
                self.hwnd, raw.shape[1], raw.shape[0])
            image = np.array(raw[top:bottom, left:right, :3], copy=True, order="C")
            with self._condition:
                self._sequence += 1
                self._latest = Frame(self._sequence, image, time.monotonic_ns(), "host-received")
                self._condition.notify_all()

        @capture.event
        def on_closed():
            with self._condition:
                self._capture_closed = True
                self._condition.notify_all()

        control = capture.start_free_threaded()
        self._capture = capture
        self._control = control

    def next_frame(self, timeout: float = 1.0) -> Frame | None:
        if self._closed:
            raise RuntimeError("Windows device is closed")
        self._start()
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._sequence == self._delivered and not self._capture_closed:
                if self._control.is_finished():
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(min(remaining, 0.05))
            if self._sequence != self._delivered:
                self._delivered = self._sequence
                return self._latest
        # wait() consumes the completed native control and reports its callback
        # error. Release it on either path so the next service attempt can
        # capture again after a temporary window/geometry failure.
        try:
            self._control.wait()
        finally:
            with self._condition:
                self._capture = None
                self._control = None
                self._capture_closed = False
                self._latest = None
                self._delivered = self._sequence
        raise RuntimeError("WGC capture ended")

    def submit(self, action: Action) -> None:
        if self._closed:
            raise RuntimeError("Windows device is closed")
        if self._input_backend is None:
            self._input_backend = _SendInput()
        kind, values = action.kind, action.values
        if kind == 'activate':
            if not self._input_backend.is_foreground(self.hwnd):
                self._input_backend.activate(self.hwnd)
            if not self._input_backend.is_foreground(self.hwnd):
                raise RuntimeError('Target HWND did not become foreground after activation')
            return
        if not self._input_backend.is_foreground(self.hwnd):
            raise RuntimeError("Target HWND is not foreground; SendInput would reach another window")
        if kind in ("key_down", "key_up"):
            vk = virtual_key(values["key"])
            self._input_backend.key(vk, kind == "key_down")
            (self._keys.add if kind == "key_down" else self._keys.discard)(vk)
        elif kind in ("button_down", "button_up"):
            button = values["button"]
            if button not in BUTTON_FLAGS:
                raise ValueError(f"Unsupported mouse button: {button}")
            self._input_backend.button(button, kind == "button_down")
            (self._buttons.add if kind == "button_down" else self._buttons.discard)(button)
        elif kind == "move_relative":
            self._input_backend.move_relative(int(values["dx"]), int(values["dy"]))
        elif kind == "move_client":
            self._input_backend.move_client(self.hwnd, int(values["x"]), int(values["y"]))
        elif kind == "scroll":
            self._input_backend.scroll(int(values["clicks"]))
        elif kind == "text":
            for (scan,) in struct.iter_unpack('<H', values['text'].encode('utf-16-le')):
                self._input_backend.unicode_key(scan, True)
                self._unicode_keys.add(scan)
                self._input_backend.unicode_key(scan, False)
                self._unicode_keys.remove(scan)
        elif kind == "click":
            button = values.get("button", "left")
            if button not in BUTTON_FLAGS:
                raise ValueError(f"Unsupported mouse button: {button}")
            if button in self._buttons:
                raise ValueError(f"Mouse button is already down: {button}")
            self._input_backend.move_client(self.hwnd, int(values["x"]), int(values["y"]))
            try:
                self._input_backend.button(button, True)
                self._buttons.add(button)
            finally:
                if button in self._buttons:
                    self._input_backend.button(button, False)
                    self._buttons.remove(button)
        else:
            raise ValueError(f"Unsupported Windows action: {kind}")

    def release_all(self) -> None:
        if self._input_backend is None:
            return
        errors = []
        for vk in tuple(self._keys):
            try:
                self._input_backend.key(vk, False)
            except Exception as error:
                errors.append(error)
            else:
                self._keys.remove(vk)
        for button in tuple(self._buttons):
            try:
                self._input_backend.button(button, False)
            except Exception as error:
                errors.append(error)
            else:
                self._buttons.remove(button)
        for scan in tuple(self._unicode_keys):
            try:
                self._input_backend.unicode_key(scan, False)
            except Exception as error:
                errors.append(error)
            else:
                self._unicode_keys.remove(scan)
        if errors:
            raise ExceptionGroup("Failed to release Windows input", errors)

    def close(self) -> None:
        if self._closed:
            return
        errors = []
        try:
            self.release_all()
        except Exception as error:
            errors.append(error)
        if self._control is not None:
            try:
                self._control.stop()
            except Exception as error:
                errors.append(error)
        self._closed = True
        if errors:
            raise ExceptionGroup("Failed to close Windows device", errors)
