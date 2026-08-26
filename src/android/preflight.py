"""Read-only MuMu/ADB/Nemu/Agent preflight for phase 01."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Callable, Mapping

from .deployment import AdbError, AdbRunner


class PreflightError(RuntimeError):
    """Raised when a required device fact is missing or ambiguous."""


@dataclass(frozen=True, slots=True)
class PackageCandidate:
    package: str
    version_name: str | None = None
    label: str | None = None


@dataclass(frozen=True, slots=True)
class PreflightReport:
    emulator_version: str | None
    emulator_root: str | None
    instance_name: str | None
    instance_index: int | None
    adb_serial: str
    adb_state: str | None
    game_package: str | None
    game_installed: bool
    game_foreground: bool | None
    android_sdk: int | None
    abi: str | None
    display_id: int | None
    physical_resolution: tuple[int, int] | None
    logical_resolution: tuple[int, int] | None
    density: int | None
    orientation: str | None
    black_bars: bool | None
    screenshot_size: tuple[int, int] | None
    nemu_ipc_ready: bool
    agent_jar_present: bool
    agent_hash_valid: bool
    agent_heartbeat: bool
    errors: tuple[str, ...]
    serial_unique: bool = True

    @classmethod
    def minimal(cls, serial: str) -> "PreflightReport":
        return cls(None, None, None, None, serial, None, None, False, None, None, None, None,
                   None, None, None, None, None, None, False, False, False, False, (), False)

    @property
    def ready(self) -> bool:
        return not self.errors and self.serial_unique and all((
            self.emulator_version == "6.5.5",
            bool(self.adb_serial), self.adb_state == "device", bool(self.game_package), self.game_installed,
            self.game_foreground is True, isinstance(self.android_sdk, int) and self.android_sdk >= 26,
            bool(self.abi), isinstance(self.display_id, int) and self.display_id >= 0,
            self.physical_resolution == (1280, 720), self.logical_resolution == (1280, 720),
            self.density == 240, self.orientation == "landscape", self.black_bars is False,
            self.screenshot_size == (1280, 720), self.nemu_ipc_ready,
            self.agent_jar_present, self.agent_hash_valid, self.agent_heartbeat,
        ))


class PackageDetector:
    _PATTERN = re.compile(r"(?:mingchao|wuthering|kurogame)", re.IGNORECASE)

    def candidates(self, raw: str) -> tuple[str, ...]:
        values = []
        for line in str(raw or "").splitlines():
            value = line.strip()
            if value.startswith("package:"):
                value = value[8:].strip()
            if value and self._PATTERN.search(value) and value not in values:
                values.append(value)
        return tuple(values)

    def require_unique(self, candidates: tuple[str, ...] | list[str]) -> str:
        values = tuple(dict.fromkeys(str(item).strip() for item in candidates if str(item).strip()))
        if len(values) != 1:
            raise PreflightError(f"鸣潮包名不唯一：{', '.join(values) if values else '未检测到'}")
        return values[0]

    @staticmethod
    def foreground_package(raw: str) -> str | None:
        patterns = (r"mCurrentFocus=Window\{[^ ]+ ([A-Za-z0-9_.]+)/", r"mFocusedApp=.*? ([A-Za-z0-9_.]+)/")
        for pattern in patterns:
            match = re.search(pattern, str(raw or ""))
            if match:
                return match.group(1)
        return None


class DevicePreflightService:
    """Collects facts without submitting game actions."""

    def __init__(
        self,
        *,
        adb: AdbRunner | None = None,
        frame_capture: Callable[[object], object] | None = None,
        agent_probe: Callable[[object], Mapping[str, Any]] | None = None,
        black_bar_probe: Callable[[object], bool] | None = None,
        emulator_version: str | None = None,
        emulator_root: str | None = None,
    ) -> None:
        self.adb = adb or AdbRunner()
        self.frame_capture = frame_capture
        self.agent_probe = agent_probe
        self.black_bar_probe = black_bar_probe
        self.emulator_version = emulator_version
        self.emulator_root = emulator_root
        self.packages = PackageDetector()

    def collect(self, channel: object) -> PreflightReport:
        serial = self._channel_value(channel, "adb_serial", "serial")
        if not serial:
            raise PreflightError("设备缺少明确 ADB serial")
        errors: list[str] = []
        values: dict[str, Any] = {
            "emulator_version": self._channel_value(channel, "emulator_version", "version") or self.emulator_version,
            "emulator_root": self.emulator_root,
            "instance_name": self._channel_value(channel, "emulator", "instance_name"),
            "instance_index": self._channel_value(channel, "instance_index", "player_id"),
            "adb_serial": serial,
            "adb_state": None,
            "game_package": None,
            "game_installed": False,
            "game_foreground": None,
            "android_sdk": None,
            "abi": None,
            "display_id": None,
            "physical_resolution": None,
            "logical_resolution": None,
            "density": None,
            "orientation": None,
            "black_bars": None,
            "screenshot_size": None,
            "nemu_ipc_ready": False,
            "agent_jar_present": False,
            "agent_hash_valid": False,
            "agent_heartbeat": False,
            "serial_unique": bool(self._channel_value(channel, "serial_unique") is not False),
        }
        if not values["serial_unique"]:
            errors.append("ADB serial 不唯一")
        try:
            values["adb_state"] = self.adb.command(serial, "get-state").stdout.strip()
            values["android_sdk"] = self._int(self.adb.shell(serial, ("getprop", "ro.build.version.sdk")).stdout)
            values["abi"] = self.adb.shell(serial, ("getprop", "ro.product.cpu.abi")).stdout.strip() or None
            values["physical_resolution"], values["logical_resolution"] = self._sizes(
                self.adb.shell(serial, ("wm", "size")).stdout
            )
            values["density"] = self._density(self.adb.shell(serial, ("wm", "density")).stdout)
            display = self.adb.shell(serial, ("dumpsys", "display")).stdout
            values["display_id"] = self._display_id(display)
            values["orientation"] = self._orientation(display)
            packages = self.packages.candidates(self.adb.shell(serial, ("pm", "list", "packages")).stdout)
            values["game_package"] = self.packages.require_unique(packages)
            values["game_installed"] = True
            focused = self.packages.foreground_package(self.adb.shell(serial, ("dumpsys", "window")).stdout)
            values["game_foreground"] = focused == values["game_package"]
        except (AdbError, PreflightError, ValueError) as exc:
            errors.append(str(exc))

        if self.frame_capture is not None:
            try:
                frame = self.frame_capture(channel)
                shape = getattr(frame, "shape", ())
                if len(shape) < 2 or tuple(shape[:2]) != (720, 1280):
                    errors.append("Nemu IPC 截图尺寸不是 1280x720")
                else:
                    values["screenshot_size"] = (1280, 720)
                    values["nemu_ipc_ready"] = True
                    values["black_bars"] = bool(self.black_bar_probe(frame)) if self.black_bar_probe else False
            except Exception as exc:
                errors.append(f"Nemu IPC 截图失败：{exc}")
        else:
            errors.append("未配置 Nemu IPC 截图提供者")

        if self.agent_probe is not None:
            try:
                agent = dict(self.agent_probe(channel))
                values["agent_jar_present"] = bool(agent.get("jar_present"))
                values["agent_hash_valid"] = bool(agent.get("hash_valid"))
                values["agent_heartbeat"] = bool(agent.get("heartbeat"))
                if agent.get("error"):
                    errors.append(str(agent["error"]))
                if not values["agent_jar_present"]:
                    errors.append("Combat Agent JAR 不存在")
                if not values["agent_hash_valid"]:
                    errors.append("Combat Agent 哈希校验失败")
                if not values["agent_heartbeat"]:
                    errors.append("Combat Agent 心跳失败")
            except Exception as exc:
                errors.append(f"Combat Agent 检查失败：{exc}")
        else:
            errors.append("未配置 Combat Agent 检查器")

        if values["emulator_version"] != "6.5.5":
            errors.append("MuMu 版本不是 6.5.5")
        if values["adb_state"] != "device":
            errors.append("ADB 设备状态不是 device")
        if values["physical_resolution"] != (1280, 720) or values["logical_resolution"] != (1280, 720):
            errors.append("设备逻辑或物理分辨率不是 1280x720")
        if values["density"] != 240:
            errors.append("设备 DPI 不是 240")
        if values["orientation"] != "landscape":
            errors.append("设备不是横屏")
        return PreflightReport(errors=tuple(dict.fromkeys(errors)), **values)

    @staticmethod
    def _channel_value(channel: object, *names: str) -> Any:
        if isinstance(channel, Mapping):
            for name in names:
                if name in channel:
                    return channel[name]
        for name in names:
            if hasattr(channel, name):
                return getattr(channel, name)
        return None

    @staticmethod
    def _int(text: str) -> int | None:
        match = re.search(r"\b(\d+)\b", str(text or ""))
        return int(match.group(1)) if match else None

    @staticmethod
    def _sizes(text: str) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
        values = [tuple(map(int, match)) for match in re.findall(r"(?:size|Size|Override size|Physical size)\s*[:=]?\s*(\d+)x(\d+)", text)]
        if not values:
            values = [tuple(map(int, match)) for match in re.findall(r"(\d+)x(\d+)", text)]
        return (values[0] if values else None, values[-1] if values else None)

    @staticmethod
    def _density(text: str) -> int | None:
        match = re.search(r"(?:Override|Physical)?\s*density\s*[:=]\s*(\d+)", text, re.IGNORECASE)
        return int(match.group(1)) if match else None

    @staticmethod
    def _display_id(text: str) -> int | None:
        match = re.search(r"(?:mDisplayId|displayId)\s*[=:]\s*(\d+)", text, re.IGNORECASE)
        return int(match.group(1)) if match else (0 if "display" in text.lower() else None)

    @staticmethod
    def _orientation(text: str) -> str | None:
        match = re.search(r"\b(landscape|portrait)\b", text, re.IGNORECASE)
        if match:
            return match.group(1).lower()
        match = re.search(r"(?:rotation|SurfaceOrientation)\s*[=:]?\s*(\d+)", text, re.IGNORECASE)
        if match:
            return "landscape" if int(match.group(1)) % 4 in (1, 3) else "portrait"
        return None
