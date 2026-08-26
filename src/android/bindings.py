"""Persistent, fail-closed MuMu device bindings."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Iterable, Mapping

_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")

class DeviceBindingError(ValueError):
    pass

def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise DeviceBindingError(f"{field}必须是明确的非空文本")
    return value.strip()

def _unsafe(path: Path) -> bool:
    if path.is_symlink(): return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except OSError:
        return False

@dataclass(frozen=True, slots=True)
class DeviceBinding:
    device_id: str
    emulator: str
    instance_index: int
    adb_serial: str
    game_package: str
    resolution: tuple[int, int] | str
    density: int
    orientation: str
    bound_profiles: tuple[str, ...]
    revision: int = 0

    def __post_init__(self):
        for name in ("device_id", "emulator", "adb_serial"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if isinstance(self.instance_index, bool) or not isinstance(self.instance_index, int) or self.instance_index < 0:
            raise DeviceBindingError("实例编号必须是非负整数")
        package = _text(self.game_package, "game_package")
        if not _PACKAGE.fullmatch(package):
            raise DeviceBindingError("游戏包名无效")
        object.__setattr__(self, "game_package", package)
        resolution = self.resolution
        if isinstance(resolution, str):
            m = re.fullmatch(r"(\d+)x(\d+)", resolution.strip())
            resolution = (int(m.group(1)), int(m.group(2))) if m else None
        if resolution != (1280, 720):
            raise DeviceBindingError("分辨率必须是 1280x720")
        object.__setattr__(self, "resolution", (1280, 720))
        if self.density != 240 or isinstance(self.density, bool):
            raise DeviceBindingError("密度必须是 240ppi")
        if _text(self.orientation, "orientation").lower() != "landscape":
            raise DeviceBindingError("方向必须是 landscape 横屏")
        object.__setattr__(self, "orientation", "landscape")
        if not isinstance(self.bound_profiles, (list, tuple)):
            raise DeviceBindingError("bound_profiles 必须是列表")
        profiles = tuple(_text(p, "bound_profiles") for p in self.bound_profiles)
        if len(set(profiles)) != len(profiles):
            raise DeviceBindingError("绑定账号不能重复")
        object.__setattr__(self, "bound_profiles", profiles)
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise DeviceBindingError("修订号必须是非负整数")

    def to_dict(self):
        return {"device_id": self.device_id, "emulator": self.emulator, "instance_index": self.instance_index,
                "adb_serial": self.adb_serial, "game_package": self.game_package,
                "resolution": "1280x720", "density": self.density, "orientation": self.orientation,
                "bound_profiles": list(self.bound_profiles), "revision": self.revision}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]):
        if not isinstance(value, Mapping): raise DeviceBindingError("设备绑定必须是对象")
        required = {"device_id","emulator","instance_index","adb_serial","game_package","resolution","density","orientation","bound_profiles","revision"}
        unknown = set(value) - required
        if unknown: raise DeviceBindingError("存在未知设备绑定字段")
        missing = required - set(value)
        if missing: raise DeviceBindingError("缺少设备绑定字段")
        try:
            return cls(**dict(value))
        except DeviceBindingError:
            raise
        except (TypeError, ValueError) as exc:
            raise DeviceBindingError("设备绑定字段类型无效") from exc

@dataclass(frozen=True, slots=True)
class BindingSnapshot:
    revision: int
    bindings: tuple[DeviceBinding, ...]

class DeviceBindingRepository:
    def __init__(self, user_data: str | os.PathLike[str]):
        root = Path(user_data)
        from src.installer.migrations import read_only_reason
        self.read_only_reason = read_only_reason(root)
        self.path = root / "配置" / "设备绑定.json"
        self._validate_path()

    def _validate_path(self):
        root = self.path.parent.parent
        for part in (root, self.path.parent):
            if part.exists() and (_unsafe(part) or not part.is_dir()):
                raise DeviceBindingError("设备绑定目录不安全")
        if self.path.exists() and _unsafe(self.path): raise DeviceBindingError("设备绑定文件不能是符号链接或重解析点")

    def snapshot(self) -> BindingSnapshot:
        self._validate_path()
        if not self.path.exists(): return BindingSnapshot(0, ())
        try: raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc: raise DeviceBindingError("设备绑定文件无法读取") from exc
        if not isinstance(raw, dict) or set(raw) != {"revision", "bindings"}:
            raise DeviceBindingError("设备绑定文件结构无效")
        rev, items = raw["revision"], raw["bindings"]
        if isinstance(rev, bool) or not isinstance(rev, int) or rev < 0 or not isinstance(items, list): raise DeviceBindingError("设备绑定修订号无效")
        bindings = tuple(DeviceBinding.from_dict(item) for item in items)
        if any(b.revision != rev for b in bindings): raise DeviceBindingError("设备绑定修订号不一致")
        ids, instances, serials, profiles = set(), set(), set(), set()
        for b in bindings:
            if b.device_id in ids or (b.emulator, b.instance_index) in instances or b.adb_serial in serials: raise DeviceBindingError("设备绑定存在重复身份")
            if profiles.intersection(b.bound_profiles): raise DeviceBindingError("账号绑定到多个设备")
            ids.add(b.device_id); instances.add((b.emulator, b.instance_index)); serials.add(b.adb_serial); profiles.update(b.bound_profiles)
        return BindingSnapshot(rev, bindings)

    def load(self): return self.snapshot().bindings

    def publish(self, bindings: Iterable[DeviceBinding], expected_revision: int | None = None) -> int:
        if self.read_only_reason: raise DeviceBindingError(self.read_only_reason)
        current = self.snapshot()
        if expected_revision is not None and expected_revision != current.revision: raise DeviceBindingError("设备绑定修订号冲突")
        items = tuple(bindings)
        if any(not isinstance(b, DeviceBinding) for b in items): raise DeviceBindingError("发布内容必须是 DeviceBinding")
        new_revision = current.revision + 1
        items = tuple(DeviceBinding(**{**b.to_dict(), "revision": new_revision}) if b.revision != new_revision else b for b in items)
        ids, instances, serials, profiles = set(), set(), set(), set()
        for b in items:
            DeviceBinding.from_dict(b.to_dict())
            if b.device_id in ids or (b.emulator, b.instance_index) in instances or b.adb_serial in serials or profiles.intersection(b.bound_profiles):
                raise DeviceBindingError("设备绑定存在重复身份")
            ids.add(b.device_id); instances.add((b.emulator, b.instance_index)); serials.add(b.adb_serial); profiles.update(b.bound_profiles)
        self._validate_path(); self.path.parent.mkdir(parents=True, exist_ok=True); self._validate_path()
        fd, tmp = tempfile.mkstemp(prefix=".设备绑定-", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump({"revision": new_revision, "bindings": [b.to_dict() for b in items]}, stream, ensure_ascii=False, separators=(",", ":")); stream.flush(); os.fsync(stream.fileno())
            os.replace(tmp, self.path)
            try:
                fd_dir = os.open(str(self.path.parent), getattr(os, "O_DIRECTORY", 0))
                try: os.fsync(fd_dir)
                finally: os.close(fd_dir)
            except OSError:
                pass
            return new_revision
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    def remove(self, device_id: str, expected_revision: int | None = None) -> int:
        snap = self.snapshot(); remaining = tuple(b for b in snap.bindings if b.device_id != device_id)
        if len(remaining) == len(snap.bindings): raise DeviceBindingError("未找到设备绑定")
        return self.publish(remaining, expected_revision if expected_revision is not None else snap.revision)
