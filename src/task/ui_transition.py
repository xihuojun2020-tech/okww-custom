"""Bounded UI transitions; no capture, input, or Qt dependencies."""
from dataclasses import dataclass
from enum import Enum
import math
import time
from uuid import uuid4


class PageState(str, Enum):
    SOURCE = 'source'
    TARGET = 'target'
    LOADING = 'loading'
    UNKNOWN = 'unknown'
    CHANGED = 'context_changed'


class TransitionError(RuntimeError):
    pass


class TransitionTimeout(TransitionError):
    pass


class TransitionContextChanged(TransitionError):
    pass


class TargetUnavailable(TransitionError):
    """The configured destination requires user action, not another click."""


@dataclass(frozen=True)
class Policy:
    timeout: float = 18
    max_attempts: int = 3
    stable_samples: int = 3
    retry_after: float = 3
    tolerance: float = .005

    def __post_init__(self):
        if (not math.isfinite(self.timeout) or self.timeout <= 0
                or not math.isfinite(self.retry_after) or self.retry_after < 0
                or not math.isfinite(self.tolerance) or self.tolerance < 0
                or type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 3
                or type(self.stable_samples) is not int or self.stable_samples < 1):
            raise ValueError('Invalid navigation budget')


@dataclass(frozen=True)
class Observation:
    state: PageState
    identity: object = None
    point: tuple | None = None


class Transition:
    """Each tick returns wait/act/done. Reserve each input before dispatch; uncertain dispatch is never replayed."""
    def __init__(self, policy, now, deadline=None):
        self.policy = policy
        self.started = now
        self.deadline = min(now + policy.timeout, deadline) if deadline is not None else now + policy.timeout
        self.attempts = 0
        self.last_action = None
        self.previous = None
        self.stable = 0
        self.last_token = None
        self.error = None
        self.last_point = None
        self.done = False
        self.identity = None
        self.has_identity = False

    def tick(self, observation, token, now):
        if self.done:
            return 'done'
        if observation.state == PageState.CHANGED:
            raise TransitionContextChanged('页面或目标已变化，停止输入')
        if now >= self.deadline:
            raise TransitionTimeout('页面转换超时，停止输入')
        if token is None or token == self.last_token:
            return 'wait'
        self.last_token = token
        if observation.state == PageState.TARGET:
            self.done = True
            return 'done'
        if observation.state != PageState.SOURCE:
            self.previous, self.stable = None, 0
            return 'wait'
        if self.has_identity and observation.identity != self.identity:
            raise TransitionContextChanged("导航目标或分辨率已变化，停止输入")
        self.identity, self.has_identity = observation.identity, True
        point = observation.point
        if point is not None and (len(point) != 2 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in point)):
            raise TransitionContextChanged('按钮超出有效游戏画面')
        old = self.previous
        same = (old is not None and old.identity == observation.identity
                and ((old.point is None and point is None) or (old.point is not None and point is not None
                     and max(abs(a-b) for a,b in zip(old.point, point)) <= self.policy.tolerance)))
        self.stable = self.stable + 1 if same else 1
        self.previous = observation
        if self.stable < self.policy.stable_samples:
            return 'wait'
        if self.last_action is not None and now - self.last_action < self.policy.retry_after:
            return 'wait'
        if self.attempts >= self.policy.max_attempts:
            raise TransitionTimeout('点击次数已达上限，仍未确认目标页面')
        return 'act'

    def submitted(self, now):
        if now >= self.deadline or self.attempts >= self.policy.max_attempts:
            raise TransitionTimeout('输入预算已耗尽')
        self.last_point = self.previous.point if self.previous else None
        self.attempts += 1
        self.last_action = now
        self.previous, self.stable = None, 0


def present(value):
    """Predicates accept booleans or objects, never ambiguous array truth values."""
    if value is None or value is False:
        return False
    if isinstance(value, (bool, int, float, str, tuple, list, dict)):
        return bool(value)
    shape = getattr(value, 'shape', None)
    if shape == ():
        return bool(value)
    if isinstance(shape, tuple):
        raise TypeError('A navigation predicate must return a boolean or target, not an image')
    return True


def run_transition(capture, observe, act, guard, *, policy=None, deadline=None,
                   notify=None, clock=time.monotonic, pause=time.sleep, cancel_errors=()):
    """Synchronous adapter. Backend capture/OCR calls must have their own bounds."""
    machine = Transition(policy or Policy(), clock(), deadline)
    operation_id = uuid4().hex
    frame = None
    def emit(status):
        if notify:
            try:
                notify(operation_id, status, machine, frame)
            except cancel_errors:
                raise
            except Exception:
                # Diagnostic storage/UI failure cannot change game control flow.
                pass
    try:
        while True:
            guard()
            if clock() >= machine.deadline:
                raise TransitionTimeout('导航总等待时间已耗尽')
            frame, token = capture()
            guard()
            observation = observe(frame)
            guard()
            decision = machine.tick(observation, token, clock())
            emit('已到达目标' if decision == 'done' else observation.state.value)
            if decision == 'done':
                return frame, machine
            if decision == 'act':
                guard()
                # Reserve this input before dispatch: a dispatch exception is
                # never permission to repeat an uncertain operation.
                machine.submitted(clock())
                emit('准备点击')
                guard()
                if clock() >= machine.deadline:
                    raise TransitionTimeout('输入前预算已耗尽')
                act(observation)
                emit('等待切页')
            pause(min(.35, max(0, machine.deadline-clock())))
    except BaseException as error:
        if isinstance(error, TransitionTimeout):
            detail = '页面未确认，未发送输入' if machine.attempts == 0 else '输入后未确认切页'
            error.args = (f'{error}；{detail}（输入 {machine.attempts}/{machine.policy.max_attempts} 次）',)
        machine.error = type(error).__name__
        try:
            emit('停止/失败')
        except BaseException:
            pass
        raise
