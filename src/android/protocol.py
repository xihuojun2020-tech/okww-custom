"""Small, strict JSON protocol shared by the host and Combat Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
import math
import re
import time
from typing import Any, Mapping
from uuid import uuid4


PROTOCOL_VERSION = 1
MAX_IDENTITY_FIELD_BYTES = 256


class ProtocolError(ValueError):
    """Raised for malformed or unsafe protocol messages."""


@dataclass(frozen=True, slots=True)
class AgentIdentityInfo:
    """Identity reported by the running agent, never inferred by the host."""

    build_version: str
    protocol_version: int
    sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.build_version, str) or not self.build_version.strip():
            raise ProtocolError("identity build_version must be non-empty")
        if len(self.build_version.encode("utf-8")) > MAX_IDENTITY_FIELD_BYTES:
            raise ProtocolError("identity build_version is too large")
        if (isinstance(self.protocol_version, bool) or not isinstance(self.protocol_version, int)
                or self.protocol_version < 1):
            raise ProtocolError("身份协议版本必须是正整数")
        if self.sha256 is not None and not isinstance(self.sha256, str):
            raise ProtocolError("identity sha256 must be a string")
        if self.sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", self.sha256):
            raise ProtocolError("identity sha256 is invalid")


def parse_agent_identity(payload: Mapping[str, Any]) -> AgentIdentityInfo:
    if not isinstance(payload, Mapping):
        raise ProtocolError("identity payload must be an object")
    allowed = {"build_version", "protocol_version", "sha256"}
    unknown = set(payload).difference(allowed)
    if unknown:
        raise ProtocolError("unknown identity fields")
    if "build_version" not in payload or "protocol_version" not in payload:
        raise ProtocolError("identity payload is incomplete")
    return AgentIdentityInfo(payload["build_version"], payload["protocol_version"], payload.get("sha256"))


class CommandKind(str, Enum):
    SEMANTIC_ACTION = "semantic_action"
    HEARTBEAT = "heartbeat"
    CANCEL = "cancel"
    EMERGENCY_STOP = "emergency_stop"
    RELEASE_ALL = "release_all"


class MessageStatus(str, Enum):
    ACCEPTED = "accepted"
    STARTED = "started"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


_FIELDS = frozenset({
    "protocol_version", "session_token", "command_id", "kind", "payload",
    "issued_at", "deadline", "status",
})


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ProtocolError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_nonstandard_number(value: str) -> None:
    raise ProtocolError(f"non-standard JSON number: {value}")


def _finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"{field_name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ProtocolError(f"{field_name} must be finite")
    return number


@dataclass(frozen=True, slots=True)
class CombatMessage:
    protocol_version: int
    session_token: str
    command_id: str
    kind: CommandKind | str
    payload: Mapping[str, Any]
    issued_at: float = field(default_factory=time.time)
    deadline: float | None = None
    status: MessageStatus | str = MessageStatus.ACCEPTED

    def __post_init__(self) -> None:
        if (
            isinstance(self.protocol_version, bool)
            or not isinstance(self.protocol_version, int)
            or self.protocol_version != PROTOCOL_VERSION
        ):
            raise ProtocolError(f"unsupported protocol_version: {self.protocol_version!r}")
        for value, name in ((self.session_token, "session_token"), (self.command_id, "command_id")):
            if not isinstance(value, str) or not value.strip():
                raise ProtocolError(f"{name} must be a non-empty string")
            try:
                encoded = value.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ProtocolError(f"{name} must be valid UTF-8") from exc
            if len(value) > 256 or len(encoded) > 256:
                raise ProtocolError(f"{name} must be at most 256 characters and UTF-8 bytes")
            object.__setattr__(self, name, value.strip())
        try:
            kind = self.kind if isinstance(self.kind, CommandKind) else CommandKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise ProtocolError(f"unknown command kind: {self.kind!r}") from exc
        try:
            status = self.status if isinstance(self.status, MessageStatus) else MessageStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ProtocolError(f"unknown message status: {self.status!r}") from exc
        if not isinstance(self.payload, Mapping):
            raise ProtocolError("payload must be an object")
        payload = dict(self.payload)
        if kind is CommandKind.SEMANTIC_ACTION:
            action = payload.get("action")
            if not isinstance(action, str) or not action.strip():
                raise ProtocolError("semantic_action payload requires a non-empty action")
            payload["action"] = action.strip()
        issued = _finite_number(self.issued_at, "issued_at")
        deadline = issued + 5.0 if self.deadline is None else _finite_number(self.deadline, "deadline")
        if deadline < issued:
            raise ProtocolError("deadline must not precede issued_at")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "deadline", deadline)

    @classmethod
    def new(
        cls,
        session_token: str,
        kind: CommandKind | str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout: float = 5.0,
        command_id: str | None = None,
        status: MessageStatus | str = MessageStatus.ACCEPTED,
    ) -> "CombatMessage":
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(float(timeout)):
            raise ProtocolError("timeout must be a finite number")
        if timeout < 0:
            raise ProtocolError("timeout must not be negative")
        issued = time.time()
        return cls(
            PROTOCOL_VERSION,
            session_token,
            command_id or uuid4().hex,
            kind,
            payload or {},
            issued,
            issued + float(timeout),
            status,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "session_token": self.session_token,
            "command_id": self.command_id,
            "kind": self.kind.value,
            "payload": dict(self.payload),
            "issued_at": self.issued_at,
            "deadline": self.deadline,
            "status": self.status.value,
        }

    def to_json(self) -> str:
        return encode_message(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CombatMessage":
        if not isinstance(value, Mapping):
            raise ProtocolError("message must be a JSON object")
        keys = set(value)
        missing = _FIELDS.difference(keys)
        if missing:
            raise ProtocolError(f"missing message fields: {', '.join(sorted(missing))}")
        unknown = keys.difference(_FIELDS)
        if unknown:
            raise ProtocolError(f"unknown message fields: {', '.join(sorted(unknown))}")
        try:
            return cls(
                value["protocol_version"], value["session_token"], value["command_id"],
                value["kind"], value["payload"], value["issued_at"], value["deadline"], value["status"],
            )
        except ProtocolError:
            raise
        except (TypeError, ValueError, KeyError) as exc:
            raise ProtocolError("invalid message fields") from exc

    @classmethod
    def from_json(cls, raw: str | bytes) -> "CombatMessage":
        return decode_message(raw)


def encode_message(message: CombatMessage) -> str:
    if not isinstance(message, CombatMessage):
        raise ProtocolError("only CombatMessage can be encoded")
    try:
        return json.dumps(
            message.to_dict(), ensure_ascii=False, separators=(",", ":"),
            sort_keys=True, allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ProtocolError("message payload is not JSON serializable") from exc


def decode_message(raw: str | bytes) -> CombatMessage:
    if not isinstance(raw, (str, bytes)):
        raise ProtocolError("encoded message must be text or UTF-8 bytes")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_nonstandard_number,
        )
    except ProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid JSON message") from exc
    return CombatMessage.from_dict(value)


CombatCommand = CombatMessage
