"""Generic Android ADB screenshot and discrete input; no persistent multitouch.

Works with a user-installed ADB and an explicit serial (including MuMu/LDPlayer
instances). `exec-out screencap -p` is PNG transfer, not a low-latency stream.
"""

from __future__ import annotations

import subprocess
import time

import cv2
import numpy as np

from gameframe.api import Action, Frame


class AdbDevice:
    """Actions: tap/click {x,y}, swipe {x1,y1,x2,y2,duration_ms}, keyevent {keycode}."""

    capabilities = frozenset({"frames", "tap", "swipe", "keyevent"})

    def __init__(self, serial: str, *, adb_path: str = "adb", runner=None):
        if not serial:
            raise ValueError("ADB serial is required to select one device")
        self.serial = serial
        self.adb_path = adb_path
        self._runner = runner if runner is not None else subprocess.run
        self._sequence = 0
        self._closed = False

    def _run(self, *args: str, timeout: float):
        if self._closed:
            raise RuntimeError("ADB device is closed")
        return self._runner([self.adb_path, "-s", self.serial, *args],
                            capture_output=True, check=True, timeout=timeout)

    def next_frame(self, timeout: float = 1.0) -> Frame | None:
        result = self._run("exec-out", "screencap", "-p", timeout=timeout)
        image = cv2.imdecode(np.frombuffer(result.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise OSError("ADB screencap returned no decodable PNG")
        self._sequence += 1
        return Frame(self._sequence, image, time.monotonic_ns(), "host-received")

    def submit(self, action: Action) -> None:
        kind, values = action.kind, action.values
        if kind in ("tap", "click"):
            command = ("tap", str(int(values["x"])), str(int(values["y"])))
        elif kind == "swipe":
            command = ("swipe", *(str(int(values[name])) for name in
                                  ("x1", "y1", "x2", "y2", "duration_ms")))
        elif kind == "keyevent":
            command = ("keyevent", str(int(values["keycode"])))
        else:
            raise ValueError(f"Unsupported ADB action: {kind}")
        self._run("shell", "input", *command, timeout=5)

    def release_all(self) -> None:
        # ADB's input tap/swipe/keyevent commands finish before returning and
        # expose no persistent contact to release.
        pass

    def close(self) -> None:
        self._closed = True
