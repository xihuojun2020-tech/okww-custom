"""Explicit, immutable MuMu/ADB device channels.

The host must never infer an ADB serial.  A channel is a deployment binding,
not an account record, and therefore intentionally contains no credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Mapping


class DeviceChannelError(ValueError):
    """Raised when a channel or registry violates a safety invariant."""


_PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")
_CAPTURE_BACKENDS = frozenset({"nemu_ipc", "adb_screencap"})
_CONTROL_BACKENDS = frozenset({"okww_combat_agent", "adb_input"})


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
            raise DeviceChannelError(f"{field} 必须是非空文本")
    return value.strip()


@dataclass(frozen=True, slots=True)
class DeviceChannel:
    """A complete explicit binding to one emulator instance."""

    channel_id: str
    adb_serial: str
    package: str
    resolution: tuple[int, int] | str
    orientation: str
    display_id: int
    emulator: str
    player_id: int | str
    capture_backend: str
    control_backend: str
    density: int = 240
    instance_index: int | None = None
    device_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "channel_id", _text(self.channel_id, "channel_id"))
        object.__setattr__(self, "adb_serial", _text(self.adb_serial, "adb_serial"))
        package = _text(self.package, "package")
        if not _PACKAGE_RE.fullmatch(package):
            raise DeviceChannelError("包名不是有效的 Android 包名")
        object.__setattr__(self, "package", package)

        resolution = self.resolution
        if isinstance(resolution, str):
            match = re.fullmatch(r"(\d+)x(\d+)", resolution.strip().lower())
            if not match:
                raise DeviceChannelError("分辨率必须是 1280x720")
            resolution = (int(match.group(1)), int(match.group(2)))
        elif isinstance(resolution, (tuple, list)) and len(resolution) == 2:
            try:
                resolution = (int(resolution[0]), int(resolution[1]))
            except (TypeError, ValueError) as exc:
                raise DeviceChannelError("分辨率必须是 1280x720") from exc
        else:
            raise DeviceChannelError("分辨率必须是 1280x720")
        if resolution != (1280, 720):
            raise DeviceChannelError("仅支持横屏 1280x720 通道")
        object.__setattr__(self, "resolution", resolution)

        orientation = _text(self.orientation, "orientation").lower()
        if orientation != "landscape":
            raise DeviceChannelError("方向必须是 landscape 横屏")
        object.__setattr__(self, "orientation", orientation)
        if isinstance(self.display_id, bool) or not isinstance(self.display_id, int) or self.display_id < 0:
            raise DeviceChannelError("显示编号必须是非负整数")
        object.__setattr__(self, "emulator", _text(self.emulator, "emulator"))
        player_id = self.player_id
        if isinstance(player_id, bool):
            raise DeviceChannelError("player_id 必须是非负整数")
        if isinstance(player_id, str):
            if not player_id.strip() or not re.fullmatch(r"\+?\d+", player_id.strip()):
                raise DeviceChannelError("player_id 必须是非负整数")
            player_id = int(player_id.strip())
        if not isinstance(player_id, int) or player_id < 0:
            raise DeviceChannelError("player_id 必须是非负整数")
        object.__setattr__(self, "player_id", player_id)
        capture = _text(self.capture_backend, "capture_backend").lower()
        control = _text(self.control_backend, "control_backend").lower()
        if capture not in _CAPTURE_BACKENDS:
            raise DeviceChannelError(f"不支持的截图后端：{capture}")
        if control not in _CONTROL_BACKENDS:
            raise DeviceChannelError(f"不支持的控制后端：{control}")
        object.__setattr__(self, "capture_backend", capture)
        object.__setattr__(self, "control_backend", control)
        if isinstance(self.density, bool) or not isinstance(self.density, int) or self.density != 240:
            raise DeviceChannelError("密度必须是 240ppi")
        if self.instance_index is None:
            instance_index = player_id
        elif isinstance(self.instance_index, bool) or not isinstance(self.instance_index, int) or self.instance_index < 0:
            raise DeviceChannelError("实例编号必须是非负整数")
        else:
            instance_index = self.instance_index
            if instance_index != player_id:
                raise DeviceChannelError("实例编号与旧 player_id 不一致")
        object.__setattr__(self, "density", self.density)
        object.__setattr__(self, "instance_index", instance_index)
        device_id = self.channel_id if self.device_id is None else _text(self.device_id, "device_id")
        if device_id != self.channel_id:
            raise DeviceChannelError("稳定 device_id 与旧 channel_id 不一致")
        object.__setattr__(self, "device_id", device_id)

    @property
    def id(self) -> str:
        """Short alias used by configuration files and log labels."""
        return self.channel_id

    @property
    def stable_device_id(self) -> str:
        return self.device_id

    @property
    def game_package(self) -> str:
        return self.package

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.channel_id,
            "adb_serial": self.adb_serial,
            "package": self.package,
            "resolution": f"{self.resolution[0]}x{self.resolution[1]}",
            "orientation": self.orientation,
            "display_id": self.display_id,
            "emulator": self.emulator,
            "player_id": self.player_id,
            "capture_backend": self.capture_backend,
            "control_backend": self.control_backend,
            "density": self.density,
            "instance_index": self.instance_index,
            "device_id": self.device_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "DeviceChannel":
        if not isinstance(value, Mapping):
            raise DeviceChannelError("通道必须是对象")
        data = dict(value)
        if "id" in data and "channel_id" not in data:
            data["channel_id"] = data.pop("id")
        data.setdefault("density", 240)
        data.setdefault("instance_index", data.get("player_id"))
        data.setdefault("device_id", data.get("channel_id"))
        required = {
            "channel_id", "adb_serial", "package", "resolution", "orientation",
            "display_id", "emulator", "player_id", "capture_backend", "control_backend",
            "density", "instance_index", "device_id",
        }
        missing = required.difference(data)
        if missing:
            raise DeviceChannelError(f"缺少通道字段：{', '.join(sorted(missing))}")
        unknown = set(data).difference(required)
        if unknown:
            raise DeviceChannelError(f"存在未知通道字段：{', '.join(sorted(unknown))}")
        return cls(**data)


class DeviceChannelRegistry:
    """Registry enforcing unique channel IDs and ADB serials."""

    def __init__(self, channels: Iterable[DeviceChannel] = ()) -> None:
        self._channels: dict[str, DeviceChannel] = {}
        self._serials: dict[str, str] = {}
        for channel in channels:
            self.register(channel)

    def register(self, channel: DeviceChannel) -> DeviceChannel:
        if not isinstance(channel, DeviceChannel):
            raise DeviceChannelError("注册表只接受 DeviceChannel 实例")
        if channel.channel_id in self._channels:
            raise DeviceChannelError(f"通道 ID 重复：{channel.channel_id}")
        if channel.adb_serial in self._serials:
            raise DeviceChannelError(f"ADB serial 重复：{channel.adb_serial}")
        self._channels[channel.channel_id] = channel
        self._serials[channel.adb_serial] = channel.channel_id
        return channel

    def get(self, channel_id: str) -> DeviceChannel:
        try:
            return self._channels[channel_id]
        except KeyError as exc:
            raise DeviceChannelError(f"未知通道 ID：{channel_id}") from exc

    def __contains__(self, channel_id: object) -> bool:
        return channel_id in self._channels

    def __len__(self) -> int:
        return len(self._channels)

    def __iter__(self):
        return iter(self._channels.values())

    def as_dict(self) -> dict[str, dict[str, object]]:
        return {channel.channel_id: channel.to_dict() for channel in self}

    @classmethod
    def from_dict(cls, value: Mapping[str, Mapping[str, object]]) -> "DeviceChannelRegistry":
        if not isinstance(value, Mapping):
            raise DeviceChannelError("设备通道必须是对象")
        channels = []
        for channel_id, raw in value.items():
            channel = DeviceChannel.from_dict(raw)
            if channel.channel_id != channel_id:
                raise DeviceChannelError(f"通道键与 ID 不一致：{channel_id}")
            channels.append(channel)
        return cls(channels)


DeviceRegistry = DeviceChannelRegistry
