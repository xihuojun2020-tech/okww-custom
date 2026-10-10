"""MuMu native capture and persistent finger contacts via the user's SDK DLL.

Signatures follow external_renderer_ipc.h at MaaXYZ/EmulatorExtras commit
54d3a3ad448f0541df3759ae91b571a6762daaf1. No vendor DLL is bundled.
"""

from __future__ import annotations

import ctypes
import time
from pathlib import Path

import numpy as np

from gameframe.api import Action, Frame


def _load_library(path: Path):
    library = ctypes.CDLL(str(path))
    integer = ctypes.c_int
    library.nemu_connect.argtypes = (ctypes.c_wchar_p, integer)
    library.nemu_connect.restype = integer
    library.nemu_disconnect.argtypes = (integer,)
    library.nemu_disconnect.restype = None
    library.nemu_get_display_id.argtypes = (integer, ctypes.c_char_p, integer)
    library.nemu_get_display_id.restype = integer
    library.nemu_capture_display.argtypes = (integer, ctypes.c_uint, integer,
                                              ctypes.POINTER(integer), ctypes.POINTER(integer),
                                              ctypes.POINTER(ctypes.c_ubyte))
    library.nemu_capture_display.restype = integer
    library.nemu_input_event_finger_touch_down.argtypes = (integer, integer, integer, integer, integer)
    library.nemu_input_event_finger_touch_down.restype = integer
    library.nemu_input_event_finger_touch_up.argtypes = (integer, integer, integer)
    library.nemu_input_event_finger_touch_up.restype = integer
    return library


class MuMuDevice:
    """Action values: touch_down/move {contact: 0..9, x, y}; touch_up {contact}."""

    capabilities = frozenset({"frames", "multitouch"})

    def __init__(self, install_dir: str | Path, instance_index: int, *, dll_path: str | Path | None = None,
                 package_name: str | None = None, app_index: int = 0, library=None):
        self.install_dir = Path(install_dir)
        self.instance_index = instance_index
        self.dll_path = Path(dll_path) if dll_path is not None else None
        self.package_name = package_name
        self.app_index = app_index
        self._library = library
        self._handle = 0
        self._sequence = 0
        self._contacts = set()
        self._closed = False

    def _connect(self):
        if self._closed:
            raise RuntimeError("MuMu device is closed")
        if self._handle:
            return
        if self._library is None:
            if self.dll_path is None:
                raise ValueError("Path to the user's MuMu SDK DLL is required")
            self._library = _load_library(self.dll_path)
        handle = self._library.nemu_connect(str(self.install_dir), self.instance_index)
        if handle <= 0:
            raise OSError("nemu_connect failed")
        self._handle = handle

    def _display_id(self):
        if self.package_name is None:
            return 0
        display_id = self._library.nemu_get_display_id(
            self._handle, self.package_name.encode("utf-8"), self.app_index)
        if display_id < 0:
            raise OSError(f"nemu_get_display_id failed: {display_id}")
        return display_id

    def next_frame(self, timeout: float = 1.0) -> Frame | None:
        # Nemu's synchronous C capture API has no timeout parameter. Its call can
        # exceed timeout; this backend does not pretend to cancel an in-flight call.
        self._connect()
        display_id = self._display_id()
        width, height = ctypes.c_int(), ctypes.c_int()
        result = self._library.nemu_capture_display(
            self._handle, display_id, 0, ctypes.byref(width), ctypes.byref(height), None)
        if result != 0:
            raise OSError(f"nemu_capture_display size query failed: {result}")
        if width.value <= 0 or height.value <= 0:
            raise OSError("nemu_capture_display returned invalid dimensions")
        expected_width, expected_height = width.value, height.value
        size = expected_width * expected_height * 4
        pixels = (ctypes.c_ubyte * size)()
        result = self._library.nemu_capture_display(
            self._handle, display_id, size, ctypes.byref(width), ctypes.byref(height), pixels)
        if result != 0:
            raise OSError(f"nemu_capture_display pixel read failed: {result}")
        if (width.value, height.value) != (expected_width, expected_height):
            raise OSError("MuMu resolution changed during capture")
        # SDK pixels are bottom-up RGBA; Frame owns a top-down BGR copy.
        raw = np.ctypeslib.as_array(pixels).reshape(height.value, width.value, 4)
        image = np.array(raw[::-1, :, 2::-1], copy=True, order="C")
        self._sequence += 1
        return Frame(self._sequence, image, time.monotonic_ns(), "host-received")

    def submit(self, action: Action) -> None:
        self._connect()
        kind, values = action.kind, action.values
        if kind not in ("touch_down", "touch_move", "touch_up"):
            raise ValueError(f"Unsupported MuMu action: {kind}")
        contact = int(values["contact"])
        if not 0 <= contact <= 9:
            raise ValueError("MuMu contact must be 0..9 (SDK finger ID 1..10)")
        if kind == "touch_down" and contact in self._contacts:
            raise ValueError(f"Contact {contact} is already down")
        if kind != "touch_down" and contact not in self._contacts:
            raise ValueError(f"Contact {contact} is not down")
        display_id = self._display_id()
        finger_id = contact + 1
        if kind == "touch_up":
            result = self._library.nemu_input_event_finger_touch_up(self._handle, display_id, finger_id)
        else:
            result = self._library.nemu_input_event_finger_touch_down(
                self._handle, display_id, finger_id, int(values["x"]), int(values["y"]))
        if result != 0:
            raise OSError(f"MuMu {kind} failed: {result}")
        if kind == "touch_up":
            self._contacts.remove(contact)
        else:
            self._contacts.add(contact)

    def release_all(self) -> None:
        if not self._handle:
            return
        errors = []
        for contact in tuple(self._contacts):
            try:
                result = self._library.nemu_input_event_finger_touch_up(
                    self._handle, self._display_id(), contact + 1)
                if result != 0:
                    raise OSError(f"MuMu touch_up failed: {result}")
            except Exception as error:
                errors.append(error)
            else:
                self._contacts.remove(contact)
        if errors:
            raise ExceptionGroup("Failed to release MuMu contacts", errors)

    def close(self) -> None:
        if self._closed:
            return
        errors = []
        try:
            self.release_all()
        except Exception as error:
            errors.append(error)
        if self._handle:
            try:
                self._library.nemu_disconnect(self._handle)
            except Exception as error:
                errors.append(error)
            self._handle = 0
        self._closed = True
        if errors:
            raise ExceptionGroup("Failed to close MuMu device", errors)
