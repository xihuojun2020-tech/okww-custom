"""Safe, explicit host-side deployment of the MuMu Combat Agent.

The deployment boundary intentionally knows nothing about accounts.  Every
ADB command is bound to the caller supplied serial and the lifecycle only
owns the two forwards it created.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Any, Callable, Iterable, Sequence

from .control import ControlBoundary, ControlMode
from .device import DeviceChannel
from .protocol import AgentIdentityInfo, CombatMessage, CommandKind, MessageStatus, ProtocolError
from .transport import SocketCombatAgentTransport


MAX_COMMAND_OUTPUT = 64 * 1024
MIN_ANDROID_SDK = 26
REMOTE_AGENT_JAR = "/data/local/tmp/okww-combat-agent.jar"
DEFAULT_AGENT_CLASS = "com.okww.combatagent.Main"
_REMOTE_PATH_RE = re.compile(r"^/(?:[A-Za-z0-9._-]+)(?:/[A-Za-z0-9._-]+)*$")
_JAVA_FQCN_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)+$")


class AdbError(RuntimeError):
    """An ADB operation failed or timed out."""

    def __init__(self, message: str, *, argv: Sequence[str], result: object = None) -> None:
        super().__init__(message)
        self.argv = tuple(str(item) for item in argv)
        self.result = result


class DeploymentError(RuntimeError):
    """The agent could not be deployed or safely cleaned up."""

@dataclass(frozen=True, slots=True)
class AgentIdentity:
    local_sha256: str
    remote_sha256: str | None
    build_version: str | None
    protocol_version: int | None

class PortLeasePool:
    def __init__(self, start=29101, end=29999):
        if not (1 <= start <= end <= 65535): raise ValueError('端口范围无效')
        self._free=set(range(start,end+1)); self._leases={}; self._lock=threading.RLock()
    def acquire(self, device_id):
        with self._lock:
            if device_id in self._leases:return self._leases[device_id]
            if len(self._free)<2:raise DeploymentError('没有可用的 Agent 端口')
            p=tuple(sorted((self._free.pop(),self._free.pop())));self._leases[device_id]=p;return p
    def release(self, device_id):
        with self._lock:self._free.update(self._leases.pop(device_id,()))


@dataclass(frozen=True, slots=True)
class AdbResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class DevicePreflight:
    """Immutable diagnostics for one explicit device channel."""

    serial: str
    package: str
    state: str | None
    resolution: tuple[int, int] | None
    orientation: str | None
    package_installed: bool
    abi: str | None
    sdk: int | None
    errors: tuple[str, ...]
    density: int | None = None
    display_id: int | None = None
    logical_resolution: tuple[int, int] | None = None
    black_bars: bool | None = None
    time_offset: float | None = None
    process_lock: bool | None = None
    device_id: str | None = None
    instance_index: int | None = None
    serial_unique: bool | None = None
    screenshot_size: tuple[int, int] | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def ready(self) -> bool:
        return self.ok


Runner = Callable[[Sequence[str], float], object]
PopenFactory = Callable[..., Any]
Probe = Callable[..., object]


def _timeout(value: float, name: str = "timeout") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite positive number")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


def _session_token(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("session_token must be a non-empty string")
    value = value.strip()
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("session_token must be valid UTF-8") from exc
    if len(value) > 256 or len(encoded) > 256:
        raise ValueError("session_token must be at most 256 characters and UTF-8 bytes")
    return value


def _bounded_text(value: object, limit: int = MAX_COMMAND_OUTPUT) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = "" if value is None else str(value)
    if len(text) > limit:
        marker = "...[truncated]"
        return marker[:limit] if limit <= len(marker) else text[:limit - len(marker)] + marker
    return text


class AdbRunner:
    """Small injectable wrapper around ``subprocess.run``.

    No command is inferred, shell-expanded, retried, or sent to a discovered
    device.  Callers construct every argument, including ``-s serial``.
    """

    def __init__(
        self,
        executable: str | Path = "adb",
        *,
        runner: Runner | None = None,
        max_output: int = MAX_COMMAND_OUTPUT,
    ) -> None:
        executable = str(executable).strip()
        if not executable:
            raise ValueError("adb executable must be explicit")
        if isinstance(max_output, bool) or not isinstance(max_output, int) or max_output <= 0:
            raise ValueError("max_output must be a positive integer")
        self.executable = executable
        self._runner = runner
        self.max_output = max_output

    def run(self, argv: Sequence[str], timeout: float) -> AdbResult:
        timeout = _timeout(timeout)
        args = tuple(str(item) for item in argv)
        if not args or args[0] != self.executable:
            raise ValueError("ADB argv must begin with the configured executable")
        if any("\x00" in item for item in args):
            raise ValueError("ADB argv cannot contain NUL bytes")
        try:
            if self._runner is not None:
                raw = self._runner(args, timeout)
            else:
                raw = subprocess.run(
                    list(args),
                    shell=False,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )
        except subprocess.TimeoutExpired as exc:
            raise AdbError("ADB command timed out", argv=args) from exc
        except OSError as exc:
            raise AdbError(f"ADB could not be started: {exc}", argv=args) from exc
        result = self._coerce_result(args, raw)
        if result.returncode != 0:
            raise AdbError(
                f"ADB command failed with exit code {result.returncode}: "
                f"{_bounded_text(result.stderr, self.max_output)}",
                argv=args,
                result=result,
            )
        return result

    def _coerce_result(self, argv: tuple[str, ...], raw: object) -> AdbResult:
        if isinstance(raw, AdbResult):
            return AdbResult(argv, int(raw.returncode), _bounded_text(raw.stdout, self.max_output), _bounded_text(raw.stderr, self.max_output))
        if isinstance(raw, (tuple, list)) and len(raw) >= 3:
            return AdbResult(argv, int(raw[0]), _bounded_text(raw[1], self.max_output), _bounded_text(raw[2], self.max_output))
        return AdbResult(
            argv,
            int(getattr(raw, "returncode", 0)),
            _bounded_text(getattr(raw, "stdout", ""), self.max_output),
            _bounded_text(getattr(raw, "stderr", ""), self.max_output),
        )

    def command(self, serial: str, *args: str, timeout: float = 30.0) -> AdbResult:
        return self.run((self.executable, "-s", str(serial), *(str(arg) for arg in args)), timeout)

    def connect(self, serial: str, timeout: float = 30.0) -> AdbResult:
        return self.run((self.executable, "connect", str(serial)), timeout)

    def shell_argv(self, serial: str, *args: str) -> list[str]:
        """Build a non-shell-expanded ``adb shell`` argv for inspection/use."""
        return [self.executable, "-s", str(serial), "shell", *(str(arg) for arg in args)]

    def shell(self, serial: str, args: Iterable[str], timeout: float = 30.0) -> AdbResult:
        return self.run(self.shell_argv(serial, *tuple(args)), timeout)

    def push(self, serial: str, local_path: str | Path, remote_path: str, timeout: float = 60.0) -> AdbResult:
        return self.run((self.executable, "-s", str(serial), "push", str(local_path), str(remote_path)), _timeout(timeout))

    def forward(self, serial: str, local_port: int, socket_name: str, timeout: float = 30.0) -> AdbResult:
        return self.run(
            (
                self.executable, "-s", str(serial), "forward", "--no-rebind",
                f"tcp:{local_port}", f"localabstract:{socket_name}",
            ),
            _timeout(timeout),
        )

    def remove_forward(self, serial: str, local_port: int, timeout: float = 30.0) -> AdbResult:
        return self.run((self.executable, "-s", str(serial), "forward", "--remove", f"tcp:{local_port}"), _timeout(timeout))


def _parse_resolution(text: str) -> tuple[int, int] | None:
    match = re.search(r"(?:Physical|Override)\s+size:\s*(\d+)x(\d+)", text, re.IGNORECASE)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _parse_logical_resolution(text: str) -> tuple[int, int] | None:
    """Parse the current logical viewport reported by Android input/display services."""
    match = re.search(r"\blogicalSize\s*[=:]\s*(\d+)x(\d+)", text, re.IGNORECASE)
    if match:
        return int(match.group(1)), int(match.group(2))
    if re.search(r"\blogicalSize\s*=", text, re.IGNORECASE):
        return (0, 0)
    match = re.search(
        r"\blogicalFrame\s*=\s*\[\s*([-+]?\d+)\s*,\s*([-+]?\d+)\s*,\s*"
        r"([-+]?\d+)\s*,\s*([-+]?\d+)\s*\]",
        text, re.IGNORECASE,
    )
    if match:
        left, top, right, bottom = (int(value) for value in match.groups())
        width, height = right - left, bottom - top
        return (width, height) if width > 0 and height > 0 else (0, 0)
    if re.search(r"\blogicalFrame\s*=", text, re.IGNORECASE):
        return (0, 0)
    match = re.search(r"\bdeviceSize\s*[=:]\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]", text, re.IGNORECASE)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r"\bdeviceSize\s*[=:]\s*(\d+)x(\d+)", text, re.IGNORECASE)
    if match:
        return int(match.group(1)), int(match.group(2))
    return (0, 0) if re.search(r"\bdeviceSize\s*=", text, re.IGNORECASE) else None


def _parse_orientation(text: str) -> str | None:
    explicit = re.search(r"\b(landscape|portrait)\b", text, re.IGNORECASE)
    if explicit:
        return explicit.group(1).lower()
    for pattern in (r"SurfaceOrientation\s*:\s*(\d+)", r"mCurrentRotation\s*=\s*ROTATION_(\d+)", r"rotation\s*[=:]\s*(\d+)"):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            rotation = int(match.group(1)) % 4
            return "landscape" if rotation in (1, 3) else "portrait"
    return None


def _parse_sdk(text: str) -> int | None:
    text = text.strip()
    return int(text) if text.isdigit() else None


def _parse_density(text: str) -> int | None:
    matches = re.findall(r"(?:Override|Physical)?\s*density\s*:\s*(\d+)", text, re.IGNORECASE)
    return int(matches[0]) if matches else None


def _parse_display_id(text: str) -> int | None:
    match = re.search(r"(?:mDisplayId|displayId)\s*[=:]\s*(\d+)", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


class CombatAgentDeployment:
    """Push, forward, start, and stop one Combat Agent instance."""

    def __init__(
        self,
        channel: DeviceChannel,
        *,
        adb: AdbRunner | None = None,
        adb_executable: str | Path = "adb",
        normal_port: int = 29101,
        emergency_port: int = 29102,
        session_id: str | None = None,
        jar_path: str | Path | None = None,
        remote_jar: str = REMOTE_AGENT_JAR,
        agent_class: str = DEFAULT_AGENT_CLASS,
        control_boundary: object | None = None,
        transport: object | None = None,
        popen_factory: PopenFactory | None = None,
        probe: Probe | None = None,
        readiness_probe: Probe | None = None,
        transport_factory: Callable[..., object] | None = None,
        serial_unique_probe: Callable[[DeviceChannel], bool] | None = None,
        screenshot_probe: Callable[[DeviceChannel], tuple[int, int]] | None = None,
        frame_capture: Callable[[DeviceChannel], object] | None = None,
        time_offset_probe: Callable[[DeviceChannel], float] | None = None,
        process_lock_probe: Callable[[DeviceChannel], bool] | None = None,
        startup_timeout: float = 10.0,
        poll_interval: float = 0.05,
        port_pool: PortLeasePool | None = None,
        asset_root: str | Path | None = None,
        build_version: str | None = None,
    ) -> None:
        if not isinstance(channel, DeviceChannel):
            raise TypeError("channel must be a DeviceChannel")
        if isinstance(normal_port, bool) or not isinstance(normal_port, int) or not 0 < normal_port <= 65535:
            raise ValueError("normal_port must be an integer in 1..65535")
        if isinstance(emergency_port, bool) or not isinstance(emergency_port, int) or not 0 < emergency_port <= 65535:
            raise ValueError("emergency_port must be an integer in 1..65535")
        if normal_port == emergency_port:
            raise ValueError("normal and emergency ports must differ")
        if not isinstance(agent_class, str) or not _JAVA_FQCN_RE.fullmatch(agent_class.strip()):
            raise ValueError("agent_class must be a safe class name")
        if (
            not isinstance(remote_jar, str)
            or not _REMOTE_PATH_RE.fullmatch(remote_jar)
            or any(segment in {".", ".."} for segment in remote_jar.split("/"))
        ):
            raise ValueError("remote_jar must be an absolute safe path")
        if probe is not None and readiness_probe is not None:
            raise ValueError("pass either probe or readiness_probe, not both")
        self.channel = channel
        self.adb = adb or AdbRunner(adb_executable)
        self._port_pool=port_pool
        self._ports_allocated=False
        self.normal_port = normal_port
        self.emergency_port = emergency_port
        self.asset_root=Path(asset_root) if asset_root is not None else None
        if build_version is not None and (not isinstance(build_version, str) or not build_version.strip() or build_version == "unknown"):
            raise ValueError("build_version must be an explicit non-placeholder string")
        self.build_version=build_version
        raw_session = session_id or f"{channel.channel_id}-{time.time_ns()}"
        if not isinstance(raw_session, str) or not raw_session.strip():
            raise ValueError("session_id must be non-empty")
        digest = hashlib.sha256(raw_session.encode("utf-8")).hexdigest()[:24]
        self.session_id = raw_session
        boundary_token = getattr(control_boundary, "session_token", None)
        candidate_token = boundary_token if boundary_token is not None else hashlib.sha256(raw_session.encode("utf-8")).hexdigest()
        self.session_token = _session_token(candidate_token)
        self.normal_socket = f"okww_combat_{digest}_n"
        self.emergency_socket = f"okww_combat_{digest}_e"
        self.jar_path = Path(jar_path) if jar_path is not None else None
        self.remote_jar = remote_jar
        self.agent_class = agent_class.strip()
        self.control_boundary = control_boundary
        self.transport = transport
        self._transport_factory = transport_factory
        self._serial_unique_probe = serial_unique_probe
        self._screenshot_probe = screenshot_probe
        self._frame_capture = frame_capture
        self._time_offset_probe = time_offset_probe
        self._process_lock_probe = process_lock_probe
        self._popen_factory = popen_factory or subprocess.Popen
        self._readiness_probe = readiness_probe or probe
        self.startup_timeout = _timeout(startup_timeout, "startup_timeout")
        self.poll_interval = _timeout(poll_interval, "poll_interval")
        self._process: Any | None = None
        self._forwarded_ports: set[int] = set()
        self._started = False
        self._stopped = False
        self.last_error: Exception | None = None
        self._stop_result: bool | None = None
        self._boundary: ControlBoundary | object | None = control_boundary

    def capture_frame(self):
        if not callable(self._frame_capture):
            raise DeploymentError("设备缺少截图提供者")
        frame = self._frame_capture(self.channel)
        shape = getattr(frame, "shape", ())
        if len(shape) < 2 or tuple(shape[:2]) != (720, 1280):
            raise DeploymentError("设备截图尺寸必须是 1280x720")
        return frame

    @staticmethod
    def _reparse(path: Path) -> bool:
        try:
            st = path.lstat()
            return path.is_symlink() or bool(getattr(st, "st_file_attributes", 0) & 0x400)
        except OSError as exc:
            raise DeploymentError("无法读取 Agent 资产路径") from exc

    def _local_hash(self):
        if self.jar_path is None or self.asset_root is None:
            raise DeploymentError("必须提供 Agent JAR 和资产根目录")
        root, jar = self.asset_root.absolute(), self.jar_path.absolute()
        if self._reparse(root) or not root.is_dir(): raise DeploymentError("Agent 资产根目录无效")
        parent = root.parent
        while parent != root:
            if self._reparse(parent): raise DeploymentError("Agent 资产根目录父级包含链接或重解析点")
            root_parent = parent.parent
            if root_parent == parent: break
            parent = root_parent
        try: relative = jar.relative_to(root)
        except ValueError as exc: raise DeploymentError("Agent JAR 不在资产根目录内") from exc
        current = root
        for part in relative.parts[:-1]:
            current /= part
            if self._reparse(current): raise DeploymentError("Agent JAR 路径包含链接或重解析点")
        if self._reparse(jar) or not jar.is_file(): raise DeploymentError("Agent JAR 必须是普通文件")
        before = jar.stat()
        if before.st_size > 128 * 1024 * 1024: raise DeploymentError("Agent JAR 超过大小上限")
        digest = hashlib.sha256()
        with jar.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""): digest.update(chunk)
        after = jar.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise DeploymentError("Agent JAR 在读取期间发生变化")
        return digest.hexdigest()
    def inspect(self):
        local=self._local_hash();remote=None
        try:
            out=self.adb.shell(self.channel.adb_serial,('sha256sum',self.remote_jar),timeout=5).stdout
            m=re.search(r'\b([0-9a-fA-F]{64})\b',out);remote=m.group(1).lower() if m else None
        except Exception:pass
        remote_build, remote_protocol = None, None
        if self.transport is not None:
            handshake=getattr(self.transport,'identity',None)
            if callable(handshake):
                try:
                    info = handshake(self.session_token, timeout=5)
                    if not isinstance(info, AgentIdentityInfo): raise ProtocolError("身份握手返回类型无效")
                    remote_build, remote_protocol = info.build_version, info.protocol_version
                except ProtocolError as exc: raise DeploymentError("Agent 身份握手无效") from exc
                except Exception: pass
        return AgentIdentity(local,remote,remote_build,remote_protocol)
    def ensure_installed(self):
        identity=self.inspect()
        if not isinstance(identity, AgentIdentity):
            raise DeploymentError("Agent 身份检查结果无效")
        if self.identity_current(identity) and self.verify_channels(): return False
        if self._port_pool is not None and not self._ports_allocated:
            self.normal_port,self.emergency_port=self._port_pool.acquire(self.channel.device_id);self._ports_allocated=True
        try:
            self._transaction_install(); return True
        except Exception:
            self._terminate_process(); self._remove_owned_forwards()
            if self._port_pool is not None:
                self._port_pool.release(self.channel.device_id); self._ports_allocated = False
            raise

    def identity_current(self, identity: object) -> bool:
        return (isinstance(identity, AgentIdentity)
                and identity.remote_sha256 == identity.local_sha256
                and identity.build_version == self.build_version
                and identity.protocol_version == 1
                and not self._stopped)

    def _transaction_install(self):
        local=self._local_hash(); safe_id = re.sub(r'[^A-Za-z0-9_.-]', '_', self.channel.device_id)
        temp=self.remote_jar+'.'+safe_id+'.tmp'
        if not self._stop_control(2.0):
            raise DeploymentError("旧 Agent 安全停止失败")
        self._terminate_process()
        self._started = False
        self._remove_owned_forwards()
        try:
            self.adb.push(self.channel.adb_serial,self.jar_path,temp,30)
            remote=self.adb.shell(self.channel.adb_serial,('sha256sum',temp),30).stdout
            match = re.search(r'\b([0-9a-fA-F]{64})\b', remote)
            if match is None or match.group(1).lower() != local: raise DeploymentError('Agent 临时文件哈希不匹配')
            self.adb.shell(self.channel.adb_serial,('mv',temp,self.remote_jar),30)
            self._skip_push=True
            try:
                self.start()
            finally:
                self._skip_push=False
            installed = self.inspect()
            if (installed.remote_sha256 != local or installed.build_version != self.build_version or
                    installed.protocol_version != 1):
                raise DeploymentError("Agent 安装后身份校验失败")
            if not self.verify_channels():
                raise DeploymentError("Agent 安装后通道校验失败")
        except Exception:
            try:self.adb.shell(self.channel.adb_serial,('rm','-f',temp),10)
            except Exception:pass
            self._skip_push=False; raise
    def verify_channels(self, timeout=2.0):
        transport = self.transport
        if transport is None: return False
        try:
            for lane in ("request", "emergency_request"):
                response = getattr(transport, lane)(CombatMessage.new(self.session_token, CommandKind.HEARTBEAT), timeout)
                if not self._heartbeat_ok(response): return False
            for kind in (CommandKind.CANCEL, CommandKind.RELEASE_ALL):
                response = transport.emergency_request(CombatMessage.new(self.session_token, kind), timeout)
                if not isinstance(response, CombatMessage) or response.kind is not kind:
                    return False
                if response.status not in (MessageStatus.COMPLETED, MessageStatus.CANCELLED): return False
            return True
        except Exception:
            return False

    @property
    def process(self) -> object | None:
        return self._process

    @property
    def forwarded_ports(self) -> tuple[int, ...]:
        return tuple(sorted(self._forwarded_ports))

    def preflight(self, timeout: float = 10.0) -> DevicePreflight:
        timeout = _timeout(timeout)
        serial, package = self.channel.adb_serial, self.channel.package
        errors: list[str] = []
        state: str | None = None
        resolution: tuple[int, int] | None = None
        orientation: str | None = None
        installed = False
        abi: str | None = None
        sdk: int | None = None
        density: int | None = None
        display_id: int | None = None
        screenshot_size: tuple[int, int] | None = None
        time_offset: float | None = None
        process_lock: bool | None = None
        serial_unique: bool | None = None

        def check(label: str, action: Callable[[], AdbResult]) -> str:
            try:
                return action().stdout
            except AdbError as exc:
                errors.append(f"{label}: {exc}")
                return ""

        if re.fullmatch(r"(?:localhost|\d{1,3}(?:\.\d{1,3}){3}):\d{1,5}", serial):
            check("connect", lambda: self.adb.connect(serial, timeout=timeout))
        state = check("get-state", lambda: self.adb.command(serial, "get-state", timeout=timeout)).strip().lower() or None
        if state != "device":
            errors.append(f"device state is {state or 'unknown'}, expected device")
        orientation_output = check("dumpsys input", lambda: self.adb.shell(serial, ("dumpsys", "input"), timeout))
        orientation_output += "\n" + check("dumpsys display", lambda: self.adb.shell(serial, ("dumpsys", "display"), timeout))
        density = _parse_density(check("wm density", lambda: self.adb.shell(serial, ("wm", "density"), timeout)))
        if density != 240:
            errors.append(f"设备密度为 {density if density is not None else '未知'}，要求 240ppi")
        display_id = _parse_display_id(orientation_output)
        if display_id != self.channel.display_id:
            errors.append(f"显示编号为 {display_id if display_id is not None else '未知'}，要求 {self.channel.display_id}")
        wm = check("wm size", lambda: self.adb.shell(serial, ("wm", "size"), timeout))
        physical_resolution = _parse_resolution(wm)
        logical_resolution = _parse_logical_resolution(orientation_output)
        resolution = logical_resolution if logical_resolution is not None else physical_resolution
        if resolution != (1280, 720):
            errors.append(f"resolution is {resolution or 'unknown'}, expected (1280, 720)")
        orientation = _parse_orientation(orientation_output)
        if orientation != "landscape":
            errors.append(f"orientation is {orientation or 'unknown'}, expected landscape")
        package_output = check("package", lambda: self.adb.shell(serial, ("pm", "path", package), timeout))
        installed = any(line.strip().startswith("package:") for line in package_output.splitlines())
        if not installed:
            errors.append(f"package is not installed: {package}")
        abi_text = check("abi", lambda: self.adb.shell(serial, ("getprop", "ro.product.cpu.abi"), timeout)).strip()
        if abi_text and abi_text.casefold() != "unknown":
            abi = abi_text
        else:
            errors.append("ABI is unknown")
        sdk = _parse_sdk(check("sdk", lambda: self.adb.shell(serial, ("getprop", "ro.build.version.sdk"), timeout)))
        if sdk is None:
            errors.append("SDK is unknown")
        elif sdk < MIN_ANDROID_SDK:
            errors.append(f"SDK is {sdk}, expected at least {MIN_ANDROID_SDK}")

        def probe(label: str, callback):
            if callback is None:
                return None
            try:
                return callback(self.channel)
            except Exception as exc:
                errors.append(f"{label}失败：{exc}")
                return None

        serial_unique = probe("ADB serial 唯一性检查", self._serial_unique_probe)
        screenshot_size = probe("截图尺寸检查", self._screenshot_probe)
        time_offset = probe("设备时间偏差检查", self._time_offset_probe)
        process_lock = probe("设备进程锁检查", self._process_lock_probe)
        # ``wm size`` reports the panel's physical orientation on MuMu tablet
        # profiles (720x1280), even while the active logical viewport and the
        # actual screencap are 1280x720 landscape.  Black-bar detection must
        # therefore use the active viewport/screenshot when available and only
        # fall back to the physical size when those signals are absent.
        viewport = screenshot_size or logical_resolution or physical_resolution
        black_bars = viewport != (1280, 720)
        return DevicePreflight(
            serial, package, state, resolution, orientation, installed, abi, sdk, tuple(errors),
            density=density, display_id=display_id, logical_resolution=logical_resolution,
            black_bars=black_bars, time_offset=time_offset, process_lock=process_lock,
            device_id=self.channel.device_id, instance_index=self.channel.instance_index,
            serial_unique=serial_unique, screenshot_size=screenshot_size,
        )

    def start(self, *, timeout: float | None = None) -> bool:
        if self._started and not self._stopped:
            return True
        if self._stopped:
            raise DeploymentError("deployment has already been stopped")
        startup_timeout = self.startup_timeout if timeout is None else _timeout(timeout)
        diagnostic = self.preflight(timeout=startup_timeout)
        if not diagnostic.ok:
            raise DeploymentError("device preflight failed: " + "; ".join(diagnostic.errors))
        if self.jar_path is None or not self.jar_path.is_file():
            raise DeploymentError(f"agent jar does not exist: {self.jar_path}")
        if self._port_pool is not None and not self._ports_allocated:
            self.normal_port,self.emergency_port=self._port_pool.acquire(self.channel.device_id);self._ports_allocated=True
        self.last_error = None
        self._stop_result = None
        mutation_attempted = False
        try:
            mutation_attempted = True
            if not getattr(self,'_skip_push',False): self.adb.push(self.channel.adb_serial, self.jar_path, self.remote_jar, startup_timeout)
            self.adb.forward(self.channel.adb_serial, self.normal_port, self.normal_socket, startup_timeout)
            self._forwarded_ports.add(self.normal_port)
            self.adb.forward(self.channel.adb_serial, self.emergency_port, self.emergency_socket, startup_timeout)
            self._forwarded_ports.add(self.emergency_port)
            agent_args = [
                f"CLASSPATH={self.remote_jar}", "app_process", "/", self.agent_class,
                "--normal-socket", self.normal_socket, "--emergency-socket", self.emergency_socket,
            ]
            if self.build_version is not None:
                agent_args.extend(("--build-version", self.build_version))
            argv = self.adb.shell_argv(self.channel.adb_serial, *agent_args)
            self._process = self._popen_factory(
                argv,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if not self._wait_until_ready(startup_timeout):
                raise DeploymentError("Combat Agent forwards did not become ready before timeout")
            if self.transport is None and self._transport_factory is not None:
                self._get_transport()
            if self._boundary is None and self.transport is not None:
                self._boundary = ControlBoundary(
                    self.transport,
                    session_token=self.session_token,
                    mode=ControlMode.COMBAT,
                )
            self._started = True
            return True
        except Exception as exc:
            self.last_error = exc
            self._rollback(mutation_attempted)
            if isinstance(exc, DeploymentError):
                raise
            raise DeploymentError(f"Combat Agent start failed: {exc}") from exc

    def _wait_until_ready(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        transport = None
        if self._readiness_probe is None:
            transport = self._get_transport()
        while time.monotonic() < deadline:
            self._raise_if_process_exited()
            if self._readiness_probe is not None:
                if self._probe_ready(self._readiness_probe):
                    return True
            elif self._protocol_ready(transport):
                return True
            time.sleep(min(self.poll_interval, max(0.001, deadline - time.monotonic())))
        self._raise_if_process_exited()
        return False

    def _probe_ready(self, probe: Probe) -> bool:
        try:
            try:
                result = probe(self, self.normal_port, self.emergency_port, self.session_token)
            except TypeError:
                try:
                    result = probe("127.0.0.1", self.normal_port, min(self.poll_interval, 1.0))
                except TypeError:
                    result = probe(self.normal_port)
            return result is not False
        except Exception:
            return False

    def _get_transport(self) -> object:
        if self.transport is not None:
            return self.transport
        if self._transport_factory is not None:
            self.transport = self._transport_factory("127.0.0.1", self.normal_port, self.emergency_port)
            if self.transport is None:
                raise DeploymentError("transport_factory returned no transport")
        else:
            self.transport = SocketCombatAgentTransport("127.0.0.1", self.normal_port, self.emergency_port)
        return self.transport

    def _protocol_ready(self, transport: object) -> bool:
        try:
            normal = transport.request(CombatMessage.new(self.session_token, CommandKind.HEARTBEAT), self.poll_interval)
            emergency = transport.emergency_request(CombatMessage.new(self.session_token, CommandKind.HEARTBEAT), self.poll_interval)
            return self._heartbeat_ok(normal) and self._heartbeat_ok(emergency)
        except Exception:
            return False

    @staticmethod
    def _heartbeat_ok(response: object) -> bool:
        return isinstance(response, CombatMessage) and response.kind is CommandKind.HEARTBEAT and response.status is MessageStatus.COMPLETED

    def _raise_if_process_exited(self) -> None:
        process = self._process
        if process is None:
            return
        poll = getattr(process, "poll", None)
        if not callable(poll):
            return
        code = poll()
        if code is not None:
            output = self._read_process_output(process)
            raise DeploymentError(f"Combat Agent exited before readiness (code {code}): {output}")

    @staticmethod
    def _read_process_output(process: object) -> str:
        chunks = []
        for name in ("stdout", "stderr"):
            stream = getattr(process, name, None)
            if stream is None or not callable(getattr(stream, "read", None)):
                continue
            try:
                chunks.append(_bounded_text(stream.read(MAX_COMMAND_OUTPUT), MAX_COMMAND_OUTPUT))
            except Exception:
                continue
        return " | ".join(item for item in chunks if item)

    def _rollback(self, seal: bool = True) -> None:
        try:
            self._stop_control(1.0)
        except Exception:
            pass
        self._close_transport()
        self._terminate_process()
        self._remove_owned_forwards()
        if self._port_pool is not None:self._port_pool.release(self.channel.device_id);self._ports_allocated=False
        if seal:
            self._stopped = True
            self._started = False
            self._stop_result = False

    def _terminate_process(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=2.0)
        except Exception:
            try:
                process.kill()
                process.wait(timeout=2.0)
            except Exception:
                pass

    def _remove_owned_forwards(self) -> None:
        ports, self._forwarded_ports = tuple(self._forwarded_ports), set()
        for port in ports:
            try:
                self.adb.remove_forward(self.channel.adb_serial, port)
            except Exception as exc:
                self.last_error = self.last_error or exc

    def stop(self, *, timeout: float = 3.0) -> bool:
        if self._stopped:
            return bool(self._stop_result)
        timeout = _timeout(timeout)
        cleanup_ok = True
        try:
            cleanup_ok = self._stop_control(timeout) and cleanup_ok
        except Exception as exc:
            self.last_error = exc
            cleanup_ok = False
        self._close_transport()
        self._terminate_process()
        self._remove_owned_forwards()
        self._stopped = True
        self._started = False
        self._stop_result = cleanup_ok and self.last_error is None
        if self._port_pool is not None:self._port_pool.release(self.channel.device_id);self._ports_allocated=False
        return self._stop_result

    close = stop

    def _stop_control(self, timeout: float) -> bool:
        target = self._boundary
        if target is None and self.transport is not None:
            target = ControlBoundary(
                self.transport,
                session_token=self.session_token,
                mode=ControlMode.COMBAT,
            )
            self._boundary = target
        if target is None:
            return True
        stop = getattr(target, "stop", None)
        if callable(stop):
            try:
                return bool(stop(timeout=timeout))
            except TypeError:
                return bool(stop())
        release = getattr(target, "release_all", None)
        if callable(release):
            try:
                return bool(release(timeout=timeout))
            except TypeError:
                return bool(release())
        return True

    def _close_transport(self) -> None:
        transport, self.transport = self.transport, None
        close = getattr(transport, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:
                self.last_error = self.last_error or exc


@dataclass(frozen=True, slots=True)
class AgentArtifactStatus:
    jar_present: bool
    hash_valid: bool
    local_sha256: str | None
    remote_sha256: str | None
    error: str | None = None


class AgentArtifactInspector:
    """Inspect the packaged Agent without starting it or sending input."""

    def __init__(self, jar_path: str | Path, *, remote_path: str = REMOTE_AGENT_JAR) -> None:
        self.jar_path = Path(jar_path)
        self.remote_path = remote_path

    def inspect(self, adb: AdbRunner | None = None, serial: str | None = None) -> AgentArtifactStatus:
        if not self.jar_path.is_file():
            return AgentArtifactStatus(False, False, None, None, "Combat Agent JAR 不存在")
        digest = hashlib.sha256(self.jar_path.read_bytes()).hexdigest()
        if adb is None or not serial:
            return AgentArtifactStatus(True, True, digest, None)
        try:
            remote = adb.shell(serial, ("sha256sum", self.remote_path), timeout=5).stdout
            match = re.search(r"\b([0-9a-fA-F]{64})\b", remote)
            remote_digest = match.group(1).lower() if match else None
            return AgentArtifactStatus(True, remote_digest == digest, digest, remote_digest,
                                       None if remote_digest == digest else "Combat Agent 远端哈希不一致")
        except Exception as exc:
            return AgentArtifactStatus(True, False, digest, None, f"Combat Agent 远端哈希检查失败：{exc}")


__all__ = [
    "AdbError",
    "AdbResult",
    "AdbRunner",
    "CombatAgentDeployment",
    "DeploymentError",
    "AgentIdentity",
    "PortLeasePool",
    "DevicePreflight",
    "MIN_ANDROID_SDK",
    "REMOTE_AGENT_JAR",
    "AgentArtifactInspector",
    "AgentArtifactStatus",
]
