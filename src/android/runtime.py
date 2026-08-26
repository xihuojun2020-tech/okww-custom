"""Android task leases, UID gates and proof-carrying multi-device shutdown."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import threading
import time
from typing import Any, Callable, Iterable, Mapping

from .control import ControlBoundary, ControlMode, SafetyProof
from .supervisor import DeviceLease, DeviceSupervisor, SupervisorError


@dataclass(frozen=True, slots=True)
class StopDeviceReport:
    device_id: str
    thread_exited: bool
    cancel: bool | None
    emergency_stop: bool | None
    release_all: bool | None
    contact_released: bool
    error: str | None = None
    mode: str = "adb"

    @property
    def completed(self) -> bool:
        safety = self.mode == "pc" or bool(self.cancel and self.emergency_stop and self.release_all)
        return self.thread_exited and self.contact_released and safety and self.error is None


@dataclass(frozen=True, slots=True)
class StopReport:
    run_id: str
    devices: tuple[StopDeviceReport, ...]
    completed: bool


@dataclass(frozen=True, slots=True)
class RunMember:
    snapshot: object
    device_id: str | None = None
    mode: str = "adb"
    control_mode: ControlMode = ControlMode.AUTOMATION


@dataclass(frozen=True, slots=True)
class RunHandle:
    run_id: str
    leases: tuple[DeviceLease, ...]


@dataclass
class _Member:
    device_id: str
    mode: str
    profile_ids: tuple[str, ...]
    lease: DeviceLease
    control: ControlBoundary | None
    control_mode: ControlMode
    expected_uids: dict[str, str]
    task_thread: threading.Thread | None = None
    task_exited: threading.Event = field(default_factory=threading.Event)
    stop_callback: Callable[[], object] | None = None
    identity_verified: bool = False


@dataclass
class _Run:
    run_id: str
    members: dict[str, _Member]
    stopped: bool = False
    stop_event: threading.Event = field(default_factory=threading.Event)
    last_report: StopReport | None = None


class TaskControlBoundary:
    """Task-facing gate; ADB inputs cannot reach the legacy PC interaction."""

    def __init__(self, coordinator: "AndroidRunCoordinator", run_id: str, device_id: str):
        self.coordinator = coordinator
        self.run_id = run_id
        self.device_id = device_id
        self._switching_threads: set[int] = set()
        self._lock = threading.RLock()

    def _member(self, *, identity: bool = False) -> _Member:
        run, member = self.coordinator._run_member(self.run_id, self.device_id)
        if run.stopped or run.stop_event.is_set():
            raise SupervisorError(f"设备 {self.device_id} 已停止，拒绝后续操作")
        if identity and not member.identity_verified and threading.get_ident() not in self._switching_threads:
            raise SupervisorError(f"设备 {self.device_id} 尚未通过 UID 核验，拒绝输入")
        return member

    def submit_input(self, action: str, payload: Mapping[str, Any] | None = None):
        member = self._member(identity=True)
        if member.control is None:
            raise SupervisorError("ADB 输入缺少 ControlBoundary")
        mode = ControlMode.AUTOMATION if threading.get_ident() in self._switching_threads else member.control_mode
        return member.control.submit_action(action, payload, mode=mode)

    def guard_capture(self) -> None:
        self._member()

    def capture_frame(self):
        self._member()
        if self.coordinator.supervisor is None:
            raise SupervisorError(f"设备 {self.device_id} 缺少截图提供者")
        return self.coordinator.supervisor.capture_frame(self.device_id)

    def guard_logout(self) -> None:
        self._member(identity=True)

    def guard_deploy(self) -> None:
        self._member(identity=True)

    def mark_identity_verified(self) -> None:
        _, member = self.coordinator._run_member(self.run_id, self.device_id)
        member.identity_verified = True

    def mark_identity_unverified(self) -> None:
        _, member = self.coordinator._run_member(self.run_id, self.device_id)
        member.identity_verified = False

    def verify_profile_uid(self, profile_id: str, actual_uid: str) -> bool:
        _, member = self.coordinator._run_member(self.run_id, self.device_id)
        member.identity_verified = False
        expected = member.expected_uids.get(str(profile_id).strip())
        if expected is None or str(actual_uid).strip() != expected:
            raise SupervisorError(f"账号 {profile_id} UID 核验失败")
        member.identity_verified = True
        return True

    @contextmanager
    def production_account_switch(self):
        member = self._member()
        if member.control is None:
            raise SupervisorError("账号切换缺少 ControlBoundary")
        ident = threading.get_ident()
        original_mode = member.control_mode
        with self._lock:
            nested = ident in self._switching_threads
        if (not nested and member.control.mode is not ControlMode.AUTOMATION
                and not member.control.switch_mode(ControlMode.AUTOMATION)):
            raise SupervisorError("无法进入账号切换控制模式")
        if not nested:
            with self._lock:
                self._switching_threads.add(ident)
        try:
            yield
        finally:
            if not nested:
                with self._lock:
                    self._switching_threads.discard(ident)
                if original_mode is not ControlMode.AUTOMATION:
                    member.control.switch_mode(original_mode)


class AndroidRunCoordinator:
    """Own shared supervisor leases and per-device task/control lifecycles."""

    def __init__(self, supervisor: DeviceSupervisor | None = None, *, control_factory=None,
                 max_parallel_devices: int = 1):
        if (isinstance(max_parallel_devices, bool) or not isinstance(max_parallel_devices, int)
                or max_parallel_devices < 1):
            raise SupervisorError("并行设备上限必须是正整数")
        self.supervisor = supervisor
        self.control_factory = control_factory
        self.max_parallel_devices = max_parallel_devices
        self._runs: dict[str, _Run] = {}
        self._reports: dict[str, StopReport] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _snapshots(snapshot: object) -> tuple[object, ...]:
        profiles = getattr(snapshot, "profiles", None)
        return tuple(profiles) if profiles else (snapshot,)

    @classmethod
    def _profiles(cls, snapshot: object) -> tuple[str, ...]:
        values = tuple(str(getattr(item, "profile_id", "")).strip() for item in cls._snapshots(snapshot))
        if not values or any(not value for value in values) or len(set(values)) != len(values):
            raise SupervisorError("运行快照缺少唯一 profile_id")
        return values

    @staticmethod
    def _device(snapshot: object, device_id: str | None) -> str:
        value = device_id or getattr(snapshot, "device_id", None)
        if value is None and isinstance(getattr(snapshot, "account", None), Mapping):
            value = snapshot.account.get("device_id")
        if not isinstance(value, str) or not value.strip():
            raise SupervisorError("运行快照缺少 device_id")
        return value.strip()

    @classmethod
    def _expected_uids(cls, snapshot: object) -> tuple[tuple[str, str], ...]:
        result = []
        for item in cls._snapshots(snapshot):
            account = getattr(item, "account", None)
            uid = getattr(item, "uid", None)
            if uid is None and isinstance(account, Mapping):
                uid = next((account.get(key) for key in ("uid", "game_uid", "player_uid", "鸣潮UID")
                            if account.get(key) not in (None, "")), None)
            if uid not in (None, ""):
                result.append((str(getattr(item, "profile_id", "")).strip(), str(uid).strip()))
        if not result:
            raise SupervisorError("运行快照缺少已确认的游戏 UID")
        return tuple(result)

    def _make_control(self, lease: DeviceLease, mode: ControlMode) -> ControlBoundary:
        if self.control_factory is not None:
            control = self.control_factory(lease)
        elif self.supervisor is not None:
            control = self.supervisor.control_boundary(lease.device_id, mode)
        else:
            control = None
        if not isinstance(control, ControlBoundary):
            raise SupervisorError("ADB 模式必须提供 ControlBoundary")
        if control.mode is not mode and not control.switch_mode(mode):
            raise SupervisorError("控制边界模式切换失败")
        return control

    def create_run(self, members: Iterable[RunMember]) -> RunHandle:
        requests = tuple(members)
        if not requests:
            raise SupervisorError("运行至少需要一个设备")
        prepared = []
        for request in requests:
            mode = str(request.mode).lower()
            if mode not in {"adb", "pc"}:
                raise SupervisorError("运行模式无效")
            profiles = self._profiles(request.snapshot)
            device = self._device(request.snapshot, request.device_id)
            prepared.append((request, mode, profiles, device))
        devices = [item[3] for item in prepared]
        profiles = [profile for item in prepared for profile in item[2]]
        if len(devices) != len(set(devices)) or len(profiles) != len(set(profiles)):
            raise SupervisorError("同一运行中的设备或 profile 重复")

        with self._lock:
            active_devices = {device for run in self._runs.values() for device in run.members}
            active_profiles = {profile for run in self._runs.values()
                               for member in run.members.values() for profile in member.profile_ids}
            if active_devices.intersection(devices) or active_profiles.intersection(profiles):
                raise SupervisorError("设备或 profile 已被租用")
            if len(active_devices.union(devices)) > self.max_parallel_devices:
                raise SupervisorError(f"超过并行设备上限 {self.max_parallel_devices}")
            run_id = f"run-{time.time_ns()}"
            acquired: list[_Member] = []
            try:
                for request, mode, profile_ids, device in prepared:
                    if self.supervisor is None:
                        lease = DeviceLease(device, profile_ids[0], f"lease-{time.time_ns()}", time.time(),
                                            profile_ids=profile_ids)
                    else:
                        lease = self.supervisor.lease(device, profile_ids[0], profile_ids=profile_ids)
                    object.__setattr__(lease, "run_id", run_id)
                    control_mode = ControlMode(request.control_mode)
                    control = None if mode == "pc" else self._make_control(lease, control_mode)
                    expected_uids = dict(self._expected_uids(request.snapshot))
                    acquired.append(_Member(device, mode, profile_ids, lease, control, control_mode,
                                            expected_uids))
                run = _Run(run_id, {member.device_id: member for member in acquired})
                self._runs[run_id] = run
                return RunHandle(run_id, tuple(member.lease for member in acquired))
            except Exception:
                for member in reversed(acquired):
                    try:
                        member.lease.release()
                    except Exception:
                        pass
                raise

    def acquire(self, snapshot: object, *, device_id: str | None = None, mode: str = "adb",
                control_mode: ControlMode = ControlMode.AUTOMATION) -> DeviceLease:
        return self.create_run((RunMember(snapshot, device_id, mode, control_mode),)).leases[0]

    def register_task(self, run_id: str, device_id: str, *, thread: threading.Thread | None = None,
                      stop_callback: Callable[[], object] | None = None) -> threading.Event:
        with self._lock:
            _, member = self._run_member(run_id, device_id)
            member.task_thread = thread or threading.current_thread()
            member.stop_callback = stop_callback
            member.task_exited.clear()
            return member.task_exited

    def task_exited(self, run_id: str, device_id: str) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None and device_id in run.members:
                run.members[device_id].task_exited.set()

    def boundary(self, run_id: str, device_id: str) -> TaskControlBoundary:
        self._run_member(run_id, device_id)
        return TaskControlBoundary(self, run_id, device_id)

    def _run_member(self, run_id: str, device_id: str) -> tuple[_Run, _Member]:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise SupervisorError("未知 run_id")
            try:
                return run, run.members[device_id]
            except KeyError as exc:
                raise SupervisorError(f"运行不包含设备 {device_id}") from exc

    def verify_uid(self, snapshot: object, actual_uid: str, *, production_switch=None, verify=None,
                   boundary: TaskControlBoundary | None = None) -> bool:
        expected = self._expected_uids(snapshot)
        actual = str(actual_uid).strip()
        if any(actual == uid for _, uid in expected):
            return True
        if not callable(production_switch) or not callable(verify):
            raise SupervisorError("运行 UID 不匹配且没有生产切号路径")
        target_profile = expected[0][0]
        if boundary is None:
            production_switch(target_profile)
        else:
            with boundary.production_account_switch():
                production_switch(target_profile)
        verified = verify()
        ok = verified if isinstance(verified, bool) else any(str(verified).strip() == uid for _, uid in expected)
        if not ok:
            raise SupervisorError("生产切号后 UID 核验失败")
        return True

    @staticmethod
    def _task_mode(task: object) -> str:
        explicit = getattr(task, "_android_mode", None)
        if explicit is not None:
            return str(explicit).lower()
        executor = getattr(task, "executor", None)
        config = getattr(executor, "config", None)
        android = config.get("android", {}) if isinstance(config, Mapping) else {}
        return "adb" if isinstance(android, Mapping) and android.get("enabled") else "pc"

    def acquire_task(self, task: object, *, control_mode: ControlMode = ControlMode.AUTOMATION) -> DeviceLease | None:
        if self._task_mode(task) == "pc":
            return None
        snapshot = (getattr(task, "_run_snapshot", None)
                    or getattr(task, "_run_profile_snapshot", None)
                    or getattr(task, "_sequence_snapshot", None))
        if snapshot is None:
            raise SupervisorError("ADB 任务缺少不可变运行快照")
        lease = self.acquire(snapshot, device_id=getattr(task, "_device_id", None), mode="adb",
                             control_mode=control_mode)
        try:
            boundary = self.boundary(lease.run_id, lease.device_id)
            task._android_lease = lease
            task._android_runtime_boundary = boundary
            self.register_task(lease.run_id, lease.device_id, thread=threading.current_thread(),
                               stop_callback=getattr(task, "disable", None))
            reader = getattr(task, "_android_uid_reader", None)
            if not callable(reader):
                reader = getattr(task, "read_android_uid", None)
            actual_uid = reader() if callable(reader) else getattr(task, "_current_uid", None)
            if actual_uid in (None, ""):
                raise SupervisorError("ADB 任务启动前无法读取游戏 UID")
            verifier = getattr(task, "_verify_uid", None)
            if not callable(verifier) and callable(reader):
                verifier = reader
            self.verify_uid(snapshot, str(actual_uid),
                            production_switch=getattr(task, "_production_switch", None),
                            verify=verifier, boundary=boundary)
            boundary.mark_identity_verified()
            return lease
        except Exception:
            self.task_exited(lease.run_id, lease.device_id)
            self.stop_run(lease.run_id, request_task_stop=False)
            task._android_runtime_boundary = None
            raise

    @staticmethod
    def _append_error(errors: list[str], value: object) -> None:
        text = str(value).strip()
        if text and text not in errors:
            errors.append(text)

    def _stop_member(self, member: _Member, timeout: float, request_task_stop: bool) -> StopDeviceReport:
        deadline = time.monotonic() + timeout
        errors: list[str] = []
        if request_task_stop and callable(member.stop_callback):
            try:
                member.stop_callback()
            except Exception as exc:
                self._append_error(errors, f"任务取消失败：{exc}")

        proof: SafetyProof | None = None
        if member.mode == "adb":
            result: list[SafetyProof] = []

            def stop_control():
                try:
                    result.append(member.control.stop_with_proof(timeout=timeout))
                except Exception as exc:
                    self._append_error(errors, f"紧急停止失败：{exc}")

            safety_thread = threading.Thread(target=stop_control, name=f"停止-{member.device_id}", daemon=True)
            safety_thread.start()
            safety_thread.join(max(0.0, deadline - time.monotonic()))
            if safety_thread.is_alive():
                self._append_error(errors, "紧急停止确认超时")
                proof = SafetyProof(False, False, False)
            else:
                proof = result[0] if result else SafetyProof(False, False, False)
                if not proof.completed:
                    self._append_error(errors, "安全指令未全部确认")

        if member.task_thread is None:
            thread_exited = True
        else:
            member.task_exited.wait(max(0.0, deadline - time.monotonic()))
            thread_exited = member.task_exited.is_set()
            if not thread_exited:
                self._append_error(errors, "任务线程退出超时")

        contact_released = False
        try:
            member.lease.release()
            contact_released = True
        except Exception as exc:
            self._append_error(errors, f"设备租约释放失败：{exc}")

        if member.mode == "adb" and (proof is None or not proof.completed or not thread_exited):
            if self.supervisor is not None:
                try:
                    self.supervisor.stop(member.device_id)
                    self.supervisor.mark_fault(member.device_id, "；".join(errors) or "设备停止未确认")
                except Exception as exc:
                    self._append_error(errors, f"故障隔离失败：{exc}")

        return StopDeviceReport(member.device_id, thread_exited,
                                None if member.mode == "pc" else proof.cancel,
                                None if member.mode == "pc" else proof.emergency_stop,
                                None if member.mode == "pc" else proof.release_all,
                                contact_released, "；".join(errors) or None, member.mode)

    def stop_run(self, run_id: str, timeout: float = 3.0, *, request_task_stop: bool = True) -> StopReport:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise SupervisorError("停止超时必须为正数")
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise SupervisorError("未知 run_id")
            run.stopped = True
            run.stop_event.set()
            members = tuple(run.members.values())

        reports: dict[str, StopDeviceReport] = {}
        report_lock = threading.Lock()

        def stop_one(member: _Member):
            report = self._stop_member(member, float(timeout), request_task_stop)
            with report_lock:
                reports[member.device_id] = report

        threads = [threading.Thread(target=stop_one, args=(member,), name=f"停止报告-{member.device_id}", daemon=True)
                   for member in members]
        started = time.monotonic()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(max(0.0, float(timeout) - (time.monotonic() - started)))
        for member, thread in zip(members, threads):
            if thread.is_alive() or member.device_id not in reports:
                reports[member.device_id] = StopDeviceReport(
                    member.device_id, False, False if member.mode == "adb" else None,
                    False if member.mode == "adb" else None, False if member.mode == "adb" else None,
                    False, "设备停止报告超时", member.mode)

        ordered = tuple(reports[member.device_id] for member in members)
        report = StopReport(run_id, ordered, all(item.completed for item in ordered))
        with self._lock:
            run.last_report = report
            self._reports[run_id] = report
            if report.completed:
                self._runs.pop(run_id, None)
        return report

    def last_stop_report(self, run_id: str) -> StopReport | None:
        with self._lock:
            run = self._runs.get(run_id)
            return run.last_report if run is not None else self._reports.get(run_id)


_DEFAULT_COORDINATOR: AndroidRunCoordinator | None = None
_DEFAULT_LOCK = threading.RLock()


def set_default_coordinator(coordinator: AndroidRunCoordinator | None) -> None:
    global _DEFAULT_COORDINATOR
    with _DEFAULT_LOCK:
        _DEFAULT_COORDINATOR = coordinator


def get_default_coordinator() -> AndroidRunCoordinator | None:
    with _DEFAULT_LOCK:
        return _DEFAULT_COORDINATOR


def resolve_task_coordinator(task: object) -> AndroidRunCoordinator:
    for owner in (task, getattr(task, "executor", None), getattr(task, "_app", None)):
        coordinator = getattr(owner, "android_coordinator", None) or getattr(owner, "_android_coordinator", None)
        if isinstance(coordinator, AndroidRunCoordinator):
            return coordinator
    coordinator = get_default_coordinator()
    if coordinator is None:
        raise SupervisorError("ADB 运行协调器尚未配置")
    return coordinator


@contextmanager
def android_task_run(task: object, control_mode: ControlMode = ControlMode.AUTOMATION):
    """Attach one task to the shared coordinator; PC mode is an explicit no-op."""
    mode = AndroidRunCoordinator._task_mode(task)
    if mode == "pc":
        yield None
        return
    executor = getattr(task, "executor", None)
    existing = (getattr(task, "_android_runtime_boundary", None)
                or getattr(executor, "_android_runtime_boundary", None))
    if isinstance(existing, TaskControlBoundary):
        _, member = existing.coordinator._run_member(existing.run_id, existing.device_id)
        requested_mode = ControlMode(control_mode)
        original_mode = member.control_mode
        if member.control is None:
            raise SupervisorError("ADB 任务缺少 ControlBoundary")
        if member.control.mode is not requested_mode and not member.control.switch_mode(requested_mode):
            raise SupervisorError("嵌套任务无法切换控制模式")
        member.control_mode = requested_mode
        task._android_lease = member.lease
        task._android_runtime_boundary = existing
        try:
            yield member.lease
        finally:
            if original_mode is not requested_mode:
                if not member.control.switch_mode(original_mode):
                    raise SupervisorError("嵌套任务无法恢复控制模式")
                member.control_mode = original_mode
            task._android_runtime_boundary = None
        return
    coordinator = resolve_task_coordinator(task)
    lease = None
    try:
        lease = coordinator.acquire_task(task, control_mode=control_mode)
        if executor is not None:
            executor._android_runtime_boundary = task._android_runtime_boundary
        yield lease
    finally:
        if lease is not None:
            coordinator.task_exited(lease.run_id, lease.device_id)
            try:
                run, _ = coordinator._run_member(lease.run_id, lease.device_id)
            except SupervisorError:
                run = None
            if run is not None and not run.stopped:
                coordinator.stop_run(lease.run_id, request_task_stop=False)
        executor = getattr(task, "executor", None)
        if executor is not None:
            executor._android_runtime_boundary = None
        task._android_runtime_boundary = None


__all__ = [
    "AndroidRunCoordinator", "RunHandle", "RunMember", "StopDeviceReport", "StopReport",
    "TaskControlBoundary", "android_task_run", "get_default_coordinator", "set_default_coordinator",
]
