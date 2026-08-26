"""Thread-safe host control boundary with fail-closed stop semantics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from threading import RLock
from typing import Any, Mapping, Protocol, runtime_checkable
from uuid import uuid4

from .protocol import CombatMessage, CommandKind, MessageStatus, ProtocolError


class ControlMode(str, Enum):
    COMBAT = "COMBAT"
    AUTOMATION = "AUTOMATION"


class ControlState(str, Enum):
    RUNNING = "running"
    SWITCHING = "switching"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class SafetyProof:
    cancel: bool
    emergency_stop: bool
    release_all: bool

    @property
    def completed(self) -> bool:
        return self.cancel and self.emergency_stop and self.release_all


@runtime_checkable
class ControlTransport(Protocol):
    """Injectable transport with a separate safety lane."""

    def request(self, message: CombatMessage, timeout: float) -> CombatMessage:
        ...

    def emergency_request(self, message: CombatMessage, timeout: float) -> CombatMessage:
        ...


class ControlBoundary:
    """Owns the only path capable of submitting input commands."""

    def __init__(
        self,
        transport: ControlTransport,
        *,
        session_token: str | None = None,
        mode: ControlMode = ControlMode.AUTOMATION,
        default_timeout: float = 1.0,
    ) -> None:
        if not isinstance(default_timeout, (int, float)) or isinstance(default_timeout, bool):
            raise ValueError("default_timeout must be a number")
        if not math.isfinite(float(default_timeout)) or default_timeout <= 0:
            raise ValueError("default_timeout must be finite and positive")
        if not callable(getattr(transport, "request", None)) and not callable(getattr(transport, "send", None)):
            raise TypeError("transport must provide request(message, timeout) or send(message)")
        self.transport = transport
        self.session_token = session_token or uuid4().hex
        if not isinstance(self.session_token, str) or not self.session_token.strip():
            raise ValueError("session_token must be non-empty")
        self._mode = ControlMode(mode)
        self._state = ControlState.RUNNING
        self._accepting = True
        self._default_timeout = float(default_timeout)
        self._pending: set[str] = set()
        self._cleanup_result: bool | None = None
        self._cleanup_proof: SafetyProof | None = None
        self._lock = RLock()
        self._io_lock = RLock()

    @property
    def mode(self) -> ControlMode:
        with self._lock:
            return self._mode

    @property
    def state(self) -> ControlState:
        with self._lock:
            return self._state

    @property
    def stopped(self) -> bool:
        return self.state is ControlState.STOPPED

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def submit_action(
        self,
        action: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
        mode: ControlMode | None = None,
    ) -> CombatMessage:
        if not isinstance(action, str) or not action.strip():
            raise ValueError("action must be non-empty")
        if payload is not None and not isinstance(payload, Mapping):
            raise ValueError("payload must be a mapping")
        request_timeout = self._timeout(timeout)
        with self._lock:
            if not self._accepting or self._state is not ControlState.RUNNING:
                raise RuntimeError("control boundary is stopped or switching")
            if mode is not None and ControlMode(mode) is not self._mode:
                raise RuntimeError(f"control mode is {self._mode.value}, not {ControlMode(mode).value}")
            message = CombatMessage.new(
                self.session_token,
                CommandKind.SEMANTIC_ACTION,
                {**dict(payload or {}), "action": action.strip()},
                timeout=request_timeout,
            )
            self._pending.add(message.command_id)
        try:
            response = self._request(message, request_timeout)
            with self._lock:
                if self._state is not ControlState.RUNNING or not self._accepting:
                    raise RuntimeError("action completed after control was stopped")
            if not self._ack(response, CommandKind.SEMANTIC_ACTION):
                raise ProtocolError("semantic action was not completed")
            return response
        except Exception:
            # A transport failure is not an acknowledgement.  Fail closed so
            # a caller cannot continue issuing input after an unknown delivery.
            with self._lock:
                already_stopped = self._state is ControlState.STOPPED
                if not already_stopped:
                    self._state = ControlState.STOPPED
                    self._accepting = False
            if not already_stopped:
                proof = self._drain(request_timeout)
                with self._lock:
                    self._cleanup_proof = proof
                    self._cleanup_result = proof.completed
            raise
        finally:
            with self._lock:
                self._pending.discard(message.command_id)

    def switch_mode(self, mode: ControlMode, *, timeout: float | None = None) -> bool:
        target = ControlMode(mode)
        request_timeout = self._timeout(timeout)
        with self._lock:
            if self._state is ControlState.STOPPED:
                return False
            if target is self._mode and self._accepting:
                return True
            self._state = ControlState.SWITCHING
            self._accepting = False
            self._cleanup_result = None
        proof = self._drain(request_timeout)
        ok = proof.completed
        with self._lock:
            if not ok or self._state is ControlState.STOPPED:
                self._state = ControlState.STOPPED
                self._accepting = False
                self._cleanup_result = False
                return False
            self._mode = target
            self._state = ControlState.RUNNING
            self._accepting = True
            self._cleanup_result = None
            return True

    def stop(self, *, timeout: float | None = None) -> bool:
        """Reject new actions first, then best-effort emergency cleanup."""
        return self.stop_with_proof(timeout=timeout).completed

    def stop_with_proof(self, *, timeout: float | None = None) -> SafetyProof:
        """Stop and retain an independent acknowledgement for each safety command."""
        request_timeout = self._timeout(timeout)
        with self._lock:
            if self._state is ControlState.STOPPED:
                return self._cleanup_proof or SafetyProof(False, False, False)
            self._state = ControlState.STOPPED
            self._accepting = False
        proof = self._drain(request_timeout)
        with self._lock:
            self._cleanup_proof = proof
            self._cleanup_result = proof.completed
        return proof

    request_stop = stop

    def release_all(self, *, timeout: float | None = None) -> bool:
        request_timeout = self._timeout(timeout)
        with self._lock:
            if not self._accepting:
                return False
        message = CombatMessage.new(self.session_token, CommandKind.RELEASE_ALL, timeout=request_timeout)
        try:
            return self._ack(self._safety_request(message, request_timeout), CommandKind.RELEASE_ALL)
        except Exception:
            with self._lock:
                self._state = ControlState.STOPPED
                self._accepting = False
            proof = self._drain(request_timeout)
            with self._lock:
                self._cleanup_proof = proof
                self._cleanup_result = proof.completed
            return False

    def _drain(self, timeout: float) -> SafetyProof:
        # Always attempt emergency_stop and release_all, even if cancellation ACK fails.
        messages = (
            CombatMessage.new(self.session_token, CommandKind.CANCEL, timeout=timeout),
            CombatMessage.new(self.session_token, CommandKind.EMERGENCY_STOP, timeout=timeout),
            CombatMessage.new(self.session_token, CommandKind.RELEASE_ALL, timeout=timeout),
        )
        results: list[bool] = []
        for message in messages:
            try:
                results.append(self._ack(self._safety_request(message, timeout), message.kind))
            except Exception:
                results.append(False)
        return SafetyProof(*results)

    @staticmethod
    def _ack(response: object, expected_kind: CommandKind) -> bool:
        if not isinstance(response, CombatMessage) or response.kind is not expected_kind:
            return False
        if expected_kind is CommandKind.CANCEL:
            return response.status in (MessageStatus.COMPLETED, MessageStatus.CANCELLED)
        return response.status is MessageStatus.COMPLETED

    def _request(self, message: CombatMessage, timeout: float) -> object:
        with self._io_lock:
            request = getattr(self.transport, "request", None)
            if callable(request):
                response = request(message, timeout)
            else:
                # Tiny fakes and legacy adapters may expose send(message) only.
                response = self.transport.send(message)
            if isinstance(response, CombatMessage):
                if response.session_token != self.session_token:
                    raise ProtocolError("transport ACK session token mismatch")
                if response.command_id != message.command_id:
                    raise ProtocolError("transport ACK command_id mismatch")
                if response.kind is not message.kind:
                    raise ProtocolError("transport ACK kind mismatch")
            return response

    def _safety_request(self, message: CombatMessage, timeout: float) -> object:
        """Send cleanup outside the ordinary action lock.

        A missing emergency lane is an explicit safety failure; falling back to
        the potentially blocked ordinary request would defeat emergency stop.
        """
        request = getattr(self.transport, "emergency_request", None)
        if not callable(request):
            raise ProtocolError("transport has no independent emergency_request lane")
        response = request(message, timeout)
        if isinstance(response, CombatMessage):
            if response.session_token != self.session_token:
                raise ProtocolError("safety ACK session token mismatch")
            if response.command_id != message.command_id:
                raise ProtocolError("safety ACK command_id mismatch")
            if response.kind is not message.kind:
                raise ProtocolError("safety ACK kind mismatch")
        return response

    def _timeout(self, timeout: float | None) -> float:
        value = self._default_timeout if timeout is None else timeout
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError("timeout must be a finite number")
        if value <= 0:
            raise ValueError("timeout must be positive")
        return float(value)
