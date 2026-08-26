"""无 Qt 的逐设备主管、状态机与租约。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import queue
import threading
import time
import uuid
from typing import Callable

from .control import ControlBoundary, ControlMode
from .deployment import AgentIdentity, DevicePreflight


class DeviceState(str, Enum):
    UNDISCOVERED = "未发现"
    STARTING = "正在启动模拟器"
    WAITING_ADB = "等待ADB"
    PREFLIGHT = "设备预检"
    CHECK_AGENT = "检查Agent"
    DEPLOY_AGENT = "部署Agent"
    VERIFY = "验证控制通道"
    READY = "就绪"
    LEASED = "已租用"
    STOPPING = "正在停止"
    FAULT = "故障"


_NEXT = {
    DeviceState.UNDISCOVERED: {DeviceState.STARTING, DeviceState.WAITING_ADB, DeviceState.PREFLIGHT, DeviceState.FAULT},
    DeviceState.STARTING: {DeviceState.WAITING_ADB, DeviceState.FAULT},
    DeviceState.WAITING_ADB: {DeviceState.PREFLIGHT, DeviceState.FAULT},
    DeviceState.PREFLIGHT: {DeviceState.CHECK_AGENT, DeviceState.FAULT},
    DeviceState.CHECK_AGENT: {DeviceState.DEPLOY_AGENT, DeviceState.VERIFY, DeviceState.FAULT},
    DeviceState.DEPLOY_AGENT: {DeviceState.VERIFY, DeviceState.FAULT},
    DeviceState.VERIFY: {DeviceState.READY, DeviceState.FAULT},
    DeviceState.READY: {DeviceState.LEASED, DeviceState.STOPPING, DeviceState.FAULT},
    DeviceState.LEASED: {DeviceState.STOPPING, DeviceState.FAULT},
    DeviceState.STOPPING: {DeviceState.READY, DeviceState.FAULT},
    DeviceState.FAULT: {DeviceState.STARTING, DeviceState.PREFLIGHT, DeviceState.STOPPING},
}


class SupervisorError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    device_id: str
    state: str
    error: str | None = None
    retry_budget: int = 3
    profile_id: str | None = None
    forward_ports: tuple[int, ...] = ()
    log_key: str = ""
    emulator: str = ""
    instance_index: int | None = None
    adb_serial: str = ""
    resolution: tuple[int, int] = (1280, 720)
    density: int = 240
    agent_version: str | None = None
    heartbeat: str = "未验证"


@dataclass(frozen=True, slots=True)
class DeviceLease:
    device_id: str
    profile_id: str
    lease_id: str
    acquired_at: float
    _release: Callable[[str], None] | None = None
    run_id: str = ""
    profile_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        profiles = self.profile_ids or (self.profile_id,)
        object.__setattr__(self, "profile_ids", tuple(profiles))

    def release(self) -> None:
        release = self._release
        if release:
            release(self.lease_id)
            object.__setattr__(self, "_release", None)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.release()


class _Context:
    def __init__(self, binding, retry_budget: int):
        self.binding = binding
        self.device_id = binding.device_id
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.state = DeviceState.UNDISCOVERED
        self.error: str | None = None
        self.retry_budget = retry_budget
        self.deployment = None
        self.profile_id: str | None = None
        self.lease: DeviceLease | None = None
        self.forward_ports: tuple[int, ...] = ()
        self.log_key = f"设备/{binding.device_id}"
        self.agent_version: str | None = None
        self.heartbeat = "未验证"


class DeviceSupervisor:
    def __init__(self, bindings=(), *, discovery=None, starter=None, deployment_factory=None,
                 preflight_validator=None, retry_budget: int = 3):
        bindings = tuple(bindings)
        if isinstance(retry_budget, bool) or not isinstance(retry_budget, int) or retry_budget < 1:
            raise SupervisorError("设备重试预算必须是正整数")
        identities = [(b.device_id, b.emulator, b.instance_index, b.adb_serial) for b in bindings]
        if (len({x[0] for x in identities}) != len(identities)
                or len({x[1:3] for x in identities}) != len(identities)
                or len({x[3] for x in identities}) != len(identities)):
            raise SupervisorError("设备绑定身份重复")
        self._contexts = {b.device_id: _Context(b, retry_budget) for b in bindings}
        self.discovery = discovery
        self.starter = starter
        self.deployment_factory = deployment_factory
        self.preflight_validator = preflight_validator
        self._leases: dict[str, DeviceLease] = {}
        self._queue: queue.Queue = queue.Queue()
        self._closing = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.RLock()

    def start(self) -> bool:
        with self._start_lock:
            if self._thread and self._thread.is_alive():
                return True
            self._leases.clear()
            for context in self._contexts.values():
                context.lease = None
                context.profile_id = None
                if context.state in (DeviceState.LEASED, DeviceState.STOPPING):
                    context.state = DeviceState.READY
            self._closing.clear()
            self._thread = threading.Thread(target=self._loop, name="设备主管", daemon=True)
            self._thread.start()
        return True

    def shutdown(self, timeout: float = 2.0) -> None:
        self._closing.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout)
            if thread.is_alive():
                raise SupervisorError("设备主管线程未能停止")

    close = shutdown

    def _loop(self) -> None:
        while not self._closing.is_set():
            try:
                function, args, result = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                result.put((True, function(*args)))
            except Exception as exc:
                result.put((False, exc))

    def _call(self, function, *args):
        if threading.current_thread() is self._thread:
            return function(*args)
        self.start()
        result: queue.Queue = queue.Queue(1)
        self._queue.put((function, args, result))
        ok, value = result.get()
        if not ok:
            raise value
        return value

    def _context(self, device_id: str) -> _Context:
        try:
            return self._contexts[device_id]
        except KeyError as exc:
            raise SupervisorError(f"未知设备：{device_id}") from exc

    _ctx = _context

    @staticmethod
    def _transition(context: _Context, state: DeviceState) -> None:
        if state not in _NEXT.get(context.state, set()):
            raise SupervisorError(f"非法设备状态跃迁：{context.state.value}→{state.value}")
        context.state = state

    _move = _transition

    @staticmethod
    def _snapshot(context: _Context) -> DeviceSnapshot:
        return DeviceSnapshot(context.device_id, context.state.value, context.error,
                              context.retry_budget, context.profile_id,
                              context.forward_ports, context.log_key,
                              context.binding.emulator, context.binding.instance_index,
                              context.binding.adb_serial, context.binding.resolution,
                              context.binding.density, context.agent_version, context.heartbeat)

    def snapshot(self, device_id: str | None = None):
        return self._call(lambda: self._snapshot(self._context(device_id)) if device_id
                          else tuple(self._snapshot(c) for c in self._contexts.values()))

    def discover(self):
        return self._call(self._discover)

    def _discover(self):
        if not self.discovery:
            return ()
        candidates = self.discovery.discover()
        for context in self._contexts.values():
            candidate = self.discovery.resolve_binding(candidates, context.binding)
            if candidate is None:
                context.error = "未找到唯一且完全匹配的设备候选"
                if context.state is not DeviceState.FAULT:
                    self._transition(context, DeviceState.FAULT)
            elif context.state is DeviceState.UNDISCOVERED:
                self._transition(context, DeviceState.PREFLIGHT)
                context.error = None
        return candidates

    def start_device(self, device_id: str):
        return self._call(self._start_device, device_id)

    def _start_device(self, device_id: str):
        context = self._context(device_id)
        if context.state not in (DeviceState.UNDISCOVERED, DeviceState.FAULT):
            raise SupervisorError(f"设备 {device_id} 当前状态不允许启动")
        if not callable(self.starter):
            raise SupervisorError("未配置 MuMu 明确实例启动器")
        self._transition(context, DeviceState.STARTING)
        try:
            if self.starter(context.binding) is False:
                raise SupervisorError("MuMu 明确实例启动失败")
            self._transition(context, DeviceState.WAITING_ADB)
            context.error = None
            return self._snapshot(context)
        except Exception as exc:
            context.error = str(exc)
            self._transition(context, DeviceState.FAULT)
            raise

    def preflight(self, device_id: str):
        return self._call(self._preflight, device_id)

    def _preflight(self, device_id: str):
        context = self._context(device_id)
        with context.lock:
            if context.state is DeviceState.FAULT:
                if context.retry_budget == 0:
                    raise SupervisorError("设备重试预算已耗尽")
                self._transition(context, DeviceState.PREFLIGHT)
            elif context.state is DeviceState.UNDISCOVERED:
                self._transition(context, DeviceState.PREFLIGHT)
            try:
                report = self.preflight_validator(context.binding) if self.preflight_validator else None
                self._validate_report(context, report)
                self._transition(context, DeviceState.CHECK_AGENT)
                context.error = None
                return report
            except Exception as exc:
                context.error = str(exc)
                context.retry_budget = max(0, context.retry_budget - 1)
                if context.state is not DeviceState.FAULT:
                    self._transition(context, DeviceState.FAULT)
                raise

    @staticmethod
    def _validate_report(context: _Context, report) -> None:
        binding = context.binding
        if not isinstance(report, DevicePreflight) or not report.ok:
            raise SupervisorError("设备预检失败或缺少完整报告")
        valid = (
            report.device_id == binding.device_id and report.instance_index == binding.instance_index
            and report.serial == binding.adb_serial and report.serial_unique is True
            and report.package == binding.game_package and report.state == "device"
            and isinstance(report.sdk, int) and report.sdk >= 26 and bool(report.abi)
            and isinstance(report.display_id, int) and report.display_id >= 0
            and report.resolution == (1280, 720)
            and report.logical_resolution == (1280, 720) and report.density == 240
            and report.orientation == "landscape" and report.black_bars is False
            and report.package_installed is True and report.screenshot_size == (1280, 720)
            and isinstance(report.time_offset, (int, float)) and abs(report.time_offset) <= 5
            and report.process_lock is True
        )
        if not valid:
            raise SupervisorError("设备预检报告与绑定或安全要求不一致")

    def ensure_ready(self, device_id: str):
        return self._call(self._ensure_ready, device_id)

    def _ensure_ready(self, device_id: str):
        context = self._context(device_id)
        if context.state in (DeviceState.UNDISCOVERED, DeviceState.PREFLIGHT, DeviceState.FAULT):
            self._preflight(device_id)
        try:
            if context.state is DeviceState.CHECK_AGENT:
                if context.deployment is None and self.deployment_factory:
                    context.deployment = self.deployment_factory(context.binding)
                deployment = context.deployment
                inspection = deployment.inspect() if deployment and callable(getattr(deployment, "inspect", None)) else None
                if isinstance(inspection, AgentIdentity):
                    current = getattr(deployment, "identity_current", None)
                    ready = bool(callable(current) and current(inspection))
                    context.agent_version = inspection.build_version
                else:
                    ready = bool(inspection) if deployment is not None else True
                if deployment is not None and not ready:
                    self._transition(context, DeviceState.DEPLOY_AGENT)
                    installer = getattr(deployment, "ensure_installed", None) or getattr(deployment, "start", None)
                    if not callable(installer) or installer() is False:
                        raise SupervisorError("Combat Agent 部署失败")
                self._transition(context, DeviceState.VERIFY)
            if context.state is DeviceState.VERIFY:
                verifier = getattr(context.deployment, "verify_channels", None) if context.deployment else None
                if callable(verifier) and verifier() is False:
                    raise SupervisorError("控制通道验证失败")
                if context.deployment is not None:
                    context.agent_version = getattr(context.deployment, "build_version", context.agent_version)
                    context.heartbeat = "已验证"
                context.forward_ports = tuple(getattr(context.deployment, "forwarded_ports", ())) if context.deployment else ()
                self._transition(context, DeviceState.READY)
                context.stop_event.clear()
                context.error = None
            return self._snapshot(context)
        except Exception as exc:
            context.error = str(exc)
            context.retry_budget = max(0, context.retry_budget - 1)
            if context.state is not DeviceState.FAULT:
                self._transition(context, DeviceState.FAULT)
            raise

    def deploy_agent(self, device_id: str):
        return self._call(self._deploy_agent, device_id)

    def _deploy_agent(self, device_id: str):
        context = self._context(device_id)
        if context.state is DeviceState.LEASED:
            raise SupervisorError(f"设备 {device_id} 正在运行任务，禁止部署 Agent")
        if context.state is not DeviceState.READY:
            self._ensure_ready(device_id)
        deployment = context.deployment
        installer = getattr(deployment, "ensure_installed", None) if deployment else None
        verifier = getattr(deployment, "verify_channels", None) if deployment else None
        if not callable(installer) or not callable(verifier):
            raise SupervisorError(f"设备 {device_id} 缺少 Agent 部署器")
        try:
            installer()
            if verifier() is False:
                raise SupervisorError("控制通道验证失败")
            context.agent_version = getattr(deployment, "build_version", context.agent_version)
            context.heartbeat = "已验证"
            context.error = None
            return self._snapshot(context)
        except Exception as exc:
            context.error = str(exc)
            self._transition(context, DeviceState.FAULT)
            raise

    def release_contacts(self, device_id: str) -> DeviceSnapshot:
        return self._call(self._release_contacts, device_id)

    def _release_contacts(self, device_id: str) -> DeviceSnapshot:
        context = self._context(device_id)
        boundary = getattr(context.deployment, "_boundary", None) if context.deployment else None
        if not isinstance(boundary, ControlBoundary) or boundary.stopped:
            raise SupervisorError(f"设备 {device_id} 没有可用的触点释放通道")
        if boundary.release_all() is False:
            context.error = "Agent 未确认释放全部触点"
            raise SupervisorError(context.error)
        context.error = None
        return self._snapshot(context)

    def lease(self, device_id: str, profile_id: str, *, profile_ids=None) -> DeviceLease:
        profiles = tuple(profile_ids) if profile_ids is not None else (profile_id,)
        return self._call(self._lease, device_id, profile_id, profiles)

    def _lease(self, device_id: str, profile_id: str, profile_ids: tuple[str, ...]) -> DeviceLease:
        context = self._context(device_id)
        profiles = tuple(str(value).strip() for value in profile_ids)
        if (not profiles or profile_id != profiles[0] or any(not value for value in profiles)
                or len(set(profiles)) != len(profiles)):
            raise SupervisorError("设备租约必须包含唯一且非空的账号")
        if any(value in self._leases for value in profiles) or context.lease is not None:
            raise SupervisorError("设备或账号已有活动租约")
        if not set(profiles).issubset(set(context.binding.bound_profiles)):
            raise SupervisorError(f"账号未绑定到设备 {device_id}")
        self._ensure_ready(device_id)
        self._transition(context, DeviceState.LEASED)
        lease = DeviceLease(device_id, profile_id, uuid.uuid4().hex, time.time(), self._release,
                            profile_ids=profiles)
        context.lease = lease
        context.profile_id = profile_id
        for value in profiles:
            self._leases[value] = lease
        return lease

    def capture_frame(self, device_id: str):
        return self._call(self._capture_frame, device_id)

    def _capture_frame(self, device_id: str):
        context = self._context(device_id)
        if context.state not in (DeviceState.READY, DeviceState.LEASED):
            raise SupervisorError(f"设备 {device_id} 尚未就绪，无法截图")
        capture = getattr(context.deployment, "capture_frame", None) if context.deployment else None
        if not callable(capture):
            raise SupervisorError(f"设备 {device_id} 缺少截图提供者")
        frame = capture()
        if frame is None:
            raise SupervisorError(f"设备 {device_id} 截图失败")
        return frame

    def control_boundary(self, device_id: str, mode: ControlMode = ControlMode.AUTOMATION) -> ControlBoundary:
        return self._call(self._control_boundary, device_id, ControlMode(mode))

    def _control_boundary(self, device_id: str, mode: ControlMode) -> ControlBoundary:
        context = self._context(device_id)
        deployment = context.deployment
        if context.state not in (DeviceState.READY, DeviceState.LEASED) or deployment is None:
            raise SupervisorError(f"设备 {device_id} 尚未就绪，无法创建控制边界")
        boundary = getattr(deployment, "_boundary", None)
        if not isinstance(boundary, ControlBoundary) or boundary.stopped:
            transport = getattr(deployment, "transport", None)
            if transport is None:
                raise SupervisorError(f"设备 {device_id} 缺少控制传输")
            boundary = ControlBoundary(
                transport,
                session_token=getattr(deployment, "session_token", None),
                mode=mode,
            )
            deployment._boundary = boundary
        elif boundary.mode is not mode and not boundary.switch_mode(mode):
            raise SupervisorError(f"设备 {device_id} 无法切换控制模式")
        return boundary

    def mark_fault(self, device_id: str, error: str) -> DeviceSnapshot:
        return self._call(self._mark_fault, device_id, error)

    def _mark_fault(self, device_id: str, error: str) -> DeviceSnapshot:
        context = self._context(device_id)
        context.error = str(error) or "设备停止未确认"
        if context.state is not DeviceState.FAULT:
            self._transition(context, DeviceState.FAULT)
        return self._snapshot(context)

    def _release(self, lease_id: str) -> None:
        self._call(self._release_inner, lease_id)

    def _release_inner(self, lease_id: str) -> None:
        for context in self._contexts.values():
            if context.lease and context.lease.lease_id == lease_id:
                for profile_id in context.lease.profile_ids:
                    self._leases.pop(profile_id, None)
                context.lease = None
                context.profile_id = None
                if context.state is DeviceState.LEASED:
                    self._transition(context, DeviceState.STOPPING)
                    self._transition(context, DeviceState.READY)
                return

    def stop(self, device_id: str | None = None):
        return self._call(self._stop, device_id)

    def _stop(self, device_id: str | None):
        contexts = (self._context(device_id),) if device_id else tuple(self._contexts.values())
        for context in contexts:
            with context.lock:
                context.stop_event.set()
                if context.state in (DeviceState.READY, DeviceState.LEASED):
                    self._transition(context, DeviceState.STOPPING)
                if context.lease:
                    self._leases.pop(context.profile_id, None)
                    context.lease = None
                    context.profile_id = None
                if context.state not in (DeviceState.STOPPING, DeviceState.FAULT):
                    context.stop_event.clear()
                    continue
                try:
                    if context.deployment and context.deployment.stop() is False:
                        raise SupervisorError("设备 Agent 未确认停止")
                    context.forward_ports = ()
                    context.heartbeat = "已停止"
                    if context.state is DeviceState.FAULT:
                        self._transition(context, DeviceState.STOPPING)
                    self._transition(context, DeviceState.READY)
                    context.stop_event.clear()
                except Exception as exc:
                    context.error = str(exc)
                    if context.state is not DeviceState.FAULT:
                        self._transition(context, DeviceState.FAULT)
        return self._snapshot(self._context(device_id)) if device_id else tuple(self._snapshot(c) for c in contexts)


__all__ = ["DeviceState", "DeviceSnapshot", "DeviceLease", "DeviceSupervisor", "SupervisorError"]
