"""Lazy, read-only Nemu IPC frame provider for MuMu 12/15 runtimes."""
from __future__ import annotations

from pathlib import Path
import logging
import threading
from types import SimpleNamespace


class NemuIpcError(RuntimeError):
    """Nemu IPC is unavailable or returned an invalid frame."""


class NemuIpcFrameProvider:
    """Capture one frame through MuMu's renderer IPC without ADB input."""

    def __init__(self, install_root: str | Path, *, instance_name: str,
                 instance_index: int, display_id: int = 0) -> None:
        self.install_root = Path(install_root).resolve()
        self.instance_name = str(instance_name).strip()
        self.instance_index = int(instance_index)
        self.display_id = int(display_id)
        self._method = None
        self._exit_event = threading.Event()

    def _ensure_method(self):
        if self._method is not None:
            return self._method
        if not self.instance_name or any(part in self.instance_name for part in ("..", "/", "\\")):
            raise NemuIpcError("MuMu 实例名不安全")
        try:
            from custom_ok.ok.device.capture_methods.nemu_ipc import NemuIpcCaptureMethod
            emulator = SimpleNamespace(
                # The compatibility shim derives install_root as dirname(dirname(path)).
                path=str(self.install_root / "nx_main" / "MuMuPlayer.exe"),
                player_id=self.instance_index,
                name=self.instance_name,
            )
            method = NemuIpcCaptureMethod(None, self._exit_event)
            method.update_emulator(emulator)
            self._method = method
            return method
        except Exception as exc:
            raise NemuIpcError(f"Nemu IPC 适配器加载失败：{exc}") from exc

    def __call__(self, channel: object = None):
        method = self._ensure_method()
        try:
            previous_disable = logging.root.manager.disable
            logging.disable(logging.CRITICAL)
            try:
                frame = method.do_get_frame()
            finally:
                logging.disable(previous_disable)
        except Exception as exc:
            message = str(exc).strip() or "实例未运行或渲染器不可用"
            raise NemuIpcError(f"Nemu IPC 连接失败：{message}") from exc
        shape = getattr(frame, "shape", ())
        if frame is None or len(shape) < 2:
            raise NemuIpcError("Nemu IPC 未返回图像帧")
        if tuple(shape[:2]) != (720, 1280):
            raise NemuIpcError(f"Nemu IPC 帧尺寸为 {tuple(shape[:2])}，要求 (720, 1280)")
        return frame

    def close(self) -> None:
        self._exit_event.set()
        method, self._method = self._method, None
        if method is not None:
            try:
                method.close()
            except Exception:
                pass


__all__ = ["NemuIpcError", "NemuIpcFrameProvider"]
