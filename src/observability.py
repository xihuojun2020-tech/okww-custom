"""Structured, redacted observability primitives for startup and task edges."""

from __future__ import annotations

import contextlib
import contextvars
import re
import traceback
from dataclasses import dataclass
from typing import Any, Callable


_PHONE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_-]{24,}(?![A-Za-z0-9])")
_SECRET = re.compile(r"(?i)(password|passwd|pwd|token|cookie|authorization|credential|密码|令牌|凭证)\s*[=:]\s*[^\s,;]+")
_LOGIN_URL = re.compile(r"https?://[^\s]+(?:login|oauth|auth|token)[^\s]*", re.I)
_CURRENT_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("okww_observation", default={})


def redact_message(value: Any) -> str:
    text = str(value)
    text = _SECRET.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    text = _LOGIN_URL.sub("[REDACTED_URL]", text)
    text = _PHONE.sub(lambda m: m.group(1)[:3] + "****" + m.group(1)[-4:], text)
    return _TOKEN.sub(lambda m: m.group(0)[:8] + "****", text)


@dataclass(frozen=True)
class Observation:
    operation: str
    profile_id: str | None = None
    revision: str | None = None
    run_id: str | None = None


class CorrelationContext:
    @staticmethod
    @contextlib.contextmanager
    def new(operation: str, profile_id: str | None = None, revision: str | None = None,
            run_id: str | None = None):
        token = _CURRENT_CONTEXT.set({"operation": str(operation), "profile_id": profile_id,
                                      "revision": revision, "run_id": run_id})
        try:
            yield Observation(str(operation), profile_id, revision, run_id)
        finally:
            _CURRENT_CONTEXT.reset(token)


class SafeModeReason(str):
    pass


class StartupFailure(RuntimeError):
    def __init__(self, operation: str, error: BaseException):
        self.operation = str(operation)
        self.cause = error
        super().__init__(redact_message(error))

    @property
    def user_message(self) -> str:
        return f"{self.operation}失败：{redact_message(self.cause)}"


@dataclass(frozen=True)
class SafeCallResult:
    state: str
    value: Any = None
    user_message: str = ""


def safe_call(operation: str, function: Callable[[], Any]) -> SafeCallResult:
    try:
        return SafeCallResult("ok", function())
    except Exception as exc:
        return SafeCallResult("failed", user_message=f"{operation}失败：{redact_message(exc)}")


__all__ = ["CorrelationContext", "Observation", "SafeCallResult", "SafeModeReason",
           "StartupFailure", "redact_message", "safe_call"]
