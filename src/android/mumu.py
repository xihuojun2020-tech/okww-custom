"""Read-only MuMu instance discovery; it never starts or edits an emulator."""
from __future__ import annotations
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import re
import subprocess
from typing import Callable, Iterable

@dataclass(frozen=True, slots=True)
class MuMuCandidate:
    emulator: str
    instance_index: int
    adb_serial: str
    game_package: str | None = None
    resolution: tuple[int, int] | None = None
    density: int | None = None
    orientation: str | None = None
    error: str | None = None
    version: str | None = None
    adb_serial_inferred: bool = False


class MuMuVersionProbe:
    _VERSION = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?:\.\d+)?(?!\d)")

    @classmethod
    def parse_file_version(cls, text: str) -> str | None:
        match = cls._VERSION.search(str(text or ""))
        return ".".join(match.groups()) if match else None

    @classmethod
    def require(cls, text: str, expected: str = "6.5.5") -> str:
        version = cls.parse_file_version(text)
        if version != expected:
            raise ValueError(f"MuMu 版本不匹配：检测到 {version or '未知'}，需要 {expected}")
        return version

    @classmethod
    def from_manager(cls, executable: str, *, runner: Callable | None = None,
                     timeout: float = 5.0) -> str:
        """Read the MuMu application version without starting an instance."""
        run = runner or subprocess.run
        result = run((executable, "version"), shell=False, capture_output=True,
                     timeout=timeout, check=False)
        if getattr(result, "returncode", 1) != 0:
            raise ValueError("MuMu version 查询失败")
        raw = getattr(result, "stdout", "")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
            raw = payload.get("version", raw) if isinstance(payload, dict) else raw
        except (TypeError, json.JSONDecodeError):
            pass
        return cls.parse_file_version(str(raw)) or ""

class MuMuDiscovery:
    COMMAND = ("MuMuManager.exe", "info", "--vmindex", "all")
    DEFAULT_MANAGER_PATHS = (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Netease/MuMu/nx_main/MuMuManager.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Netease/MuMu/nx_main/MuMuManager.exe",
    )
    DEFAULT_ADB_PATHS = (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Netease/MuMu/nx_main/adb.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Netease/MuMu/nx_device/15.0/shell/adb.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Netease/MuMu/nx_main/adb.exe",
    )

    @classmethod
    def find_manager(cls, explicit: str | None = None) -> str:
        value = str(explicit or "").strip()
        if value and value.lower() != "mumuManager.exe".lower():
            return value
        found = shutil.which("MuMuManager.exe")
        if found:
            return found
        for path in cls._process_manager_paths():
            if path.is_file():
                return str(path)
        for path in cls._registry_manager_paths():
            if path.is_file():
                return str(path)
        for path in cls.DEFAULT_MANAGER_PATHS:
            if path.is_file():
                return str(path)
        return value or "MuMuManager.exe"

    @classmethod
    def find_adb(cls, explicit: str | None = None) -> str:
        value = str(explicit or "").strip()
        if value and value.lower() != "adb":
            return value
        found = shutil.which("adb")
        if found:
            return found
        for path in cls.DEFAULT_ADB_PATHS:
            if path.is_file():
                return str(path)
        for manager in cls._process_manager_paths():
            root = manager.parent
            candidates = (root / "adb.exe", *root.glob("../nx_device/*/shell/adb.exe"))
            for path in candidates:
                if path.is_file():
                    return str(path.resolve())
        return value or "adb"

    @staticmethod
    def _process_manager_paths() -> tuple[Path, ...]:
        try:
            import psutil
            paths = []
            for process in psutil.process_iter(("name", "exe")):
                name = str(process.info.get("name") or "").lower()
                if name not in {"mumu nx main.exe", "mumunxmain.exe", "mumuplayer.exe", "mumumanager.exe"}:
                    continue
                executable = process.info.get("exe")
                if executable:
                    paths.append(Path(executable).resolve().parent / "MuMuManager.exe")
            return tuple(dict.fromkeys(paths))
        except Exception:
            return ()

    @staticmethod
    def _registry_manager_paths() -> tuple[Path, ...]:
        if os.name != "nt":
            return ()
        try:
            import winreg
            paths = []
            for root, key_name in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Netease\MuMu"),
                                   (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Netease\MuMu")):
                try:
                    with winreg.OpenKey(root, key_name) as key:
                        for value_name in ("InstallLocation", "Path", "InstallPath"):
                            try:
                                value, _ = winreg.QueryValueEx(key, value_name)
                            except OSError:
                                continue
                            paths.append(Path(str(value)) / "nx_main/MuMuManager.exe")
                except OSError:
                    continue
            return tuple(dict.fromkeys(paths))
        except Exception:
            return ()

    def __init__(self, executable: str = "MuMuManager.exe", *, runner: Callable | None = None,
                 candidate_probe: Callable[[MuMuCandidate], MuMuCandidate] | None = None,
                 timeout: float = 5.0, output_limit: int = 1_048_576):
        if timeout <= 0 or output_limit <= 0: raise ValueError("超时和输出上限必须为正数")
        self.runner = runner or self._run
        self.executable = executable if runner is not None else self.find_manager(executable)
        self.candidate_probe = candidate_probe
        self.timeout, self.output_limit = timeout, output_limit

    def _run(self, args, **kwargs):
        return subprocess.run(args, shell=False, capture_output=True, timeout=kwargs["timeout"], check=False)

    def discover(self) -> tuple[MuMuCandidate, ...]:
        args = (self.executable,) + self.COMMAND[1:]
        try:
            result = self.runner(args, timeout=self.timeout, shell=False)
            if hasattr(result, "returncode") and result.returncode != 0:
                raise ValueError("MuMu 查询命令失败")
            if hasattr(result, "stderr") and result.stderr:
                raise ValueError("MuMu 查询返回错误")
            raw = result.stdout if hasattr(result, "stdout") else result
            if isinstance(raw, bytes):
                if len(raw) > self.output_limit: raise ValueError("输出超限")
                raw = raw.decode("utf-8", "replace")
            if not isinstance(raw, str) or len(raw.encode()) > self.output_limit: raise ValueError("输出超限")
            data = json.loads(raw)
            items = data if isinstance(data, list) else self._manager_items(data)
            candidates = tuple(self._candidate(item) for item in items)
            if self.candidate_probe is not None:
                candidates = tuple(self._probe(candidate) for candidate in candidates)
            return candidates
        except Exception as exc:
            return (MuMuCandidate("MuMu", -1, "", error=f"发现失败：{exc}"),)

    @staticmethod
    def _manager_items(data):
        if not isinstance(data, dict): raise ValueError("实例信息格式无效")
        items = []
        for key, value in data.items():
            if not isinstance(value, dict): raise ValueError("实例信息格式无效")
            raw_index = value.get("index", key)
            if isinstance(raw_index, bool) or not str(raw_index).isdigit(): raise ValueError("实例编号无效")
            index = int(raw_index)
            host, port = value.get("adb_host_ip"), value.get("adb_port")
            version = value.get("android_version") or value.get("version")
            if not isinstance(version, str) or not version.strip(): raise ValueError("MuMu/Android 版本无效")
            inferred = False
            if host is None and port is None:
                # MuMu 6.5.5/12+ uses the stable 16384 base for instance 0.
                # This is only a displayed candidate; no connection is attempted.
                host, port, inferred = "127.0.0.1", 16384 + index, True
            if host not in {"127.0.0.1", "localhost"} or isinstance(port, bool) or not isinstance(port, int) or not 0 < port <= 65535:
                raise ValueError("ADB 地址无效")
            items.append({"emulator": str(value.get("name") or f"MuMuPlayer-{version.strip()}-{index}"), "instance_index": index,
                          "adb_serial": f"{host}:{port}", "version": value.get("mumu_version") or value.get("version"),
                          "adb_serial_inferred": inferred})
        return items

    def _probe(self, candidate):
        try:
            result = self.candidate_probe(candidate)
            if not isinstance(result, MuMuCandidate): raise ValueError("候选检查结果无效")
            return result
        except Exception as exc:
            return MuMuCandidate(candidate.emulator, candidate.instance_index, candidate.adb_serial,
                                 error=f"只读预检失败：{exc}", version=candidate.version,
                                 adb_serial_inferred=candidate.adb_serial_inferred)

    @staticmethod
    def _candidate(item):
        if not isinstance(item, dict): raise ValueError("候选格式无效")
        emulator, index, serial = item["emulator"], item["instance_index"], item["adb_serial"]
        if not isinstance(emulator, str) or not emulator or isinstance(index, bool) or not isinstance(index, int) or index < 0 or not isinstance(serial, str) or not serial:
            raise ValueError("候选身份字段无效")
        package = item.get("game_package")
        if package is not None and (not isinstance(package, str) or not package): raise ValueError("候选包名无效")
        resolution = item.get("resolution")
        if resolution is not None and (not isinstance(resolution, (list, tuple)) or len(resolution) != 2 or any(not isinstance(v, int) for v in resolution)): raise ValueError("候选分辨率无效")
        density, orientation = item.get("density"), item.get("orientation")
        if density is not None and (isinstance(density, bool) or not isinstance(density, int) or density != 240): raise ValueError("候选密度无效")
        if orientation is not None and (not isinstance(orientation, str) or orientation != "landscape"): raise ValueError("候选方向无效")
        return MuMuCandidate(emulator, index, serial, package, tuple(resolution) if resolution else None, density, orientation,
                              None, MuMuVersionProbe.parse_file_version(item.get("version", "")),
                              bool(item.get("adb_serial_inferred", False)))

    @staticmethod
    def resolve_binding(candidates: Iterable[MuMuCandidate], binding) -> MuMuCandidate | None:
        matches = [c for c in candidates if c.error is None and c.emulator == binding.emulator and
                   c.instance_index == binding.instance_index and c.adb_serial == binding.adb_serial and
                   c.game_package == binding.game_package and c.resolution == binding.resolution and
                   c.density == binding.density and c.orientation == binding.orientation]
        return matches[0] if len(matches) == 1 else None


class MuMuController:
    """Explicit single-instance mutation adapter; discovery remains read-only."""

    def __init__(self, executable: str = "MuMuManager.exe", *, runner: Callable | None = None,
                 timeout: float = 15.0, output_limit: int = 65_536):
        if timeout <= 0 or output_limit <= 0:
            raise ValueError("超时和输出上限必须为正数")
        self.executable = executable if runner is not None else MuMuDiscovery.find_manager(executable)
        self.runner = runner or subprocess.run
        self.timeout = timeout
        self.output_limit = output_limit

    def start(self, binding) -> bool:
        index = getattr(binding, "instance_index", None)
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("启动目标缺少明确实例编号")
        result = self.runner(
            (self.executable, "control", "--vmindex", str(index), "launch"),
            shell=False,
            capture_output=True,
            timeout=self.timeout,
            check=False,
        )
        output = b"".join(value for value in (getattr(result, "stdout", b""), getattr(result, "stderr", b""))
                          if isinstance(value, bytes))
        if len(output) > self.output_limit:
            raise RuntimeError("MuMu 启动命令输出超限")
        if getattr(result, "returncode", 1) != 0:
            raise RuntimeError("MuMu 明确实例启动失败")
        return True
