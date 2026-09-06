"""Structured, redacted observability primitives for startup and task edges."""

from __future__ import annotations

import contextlib
import contextvars
import logging
import re
import threading
import traceback
from dataclasses import dataclass
from typing import Any, Callable


_PHONE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_MASKED_PHONE = re.compile(r"(?<!\d)1[3-9]\d\*{4}\d{4}(?!\d)")
_ALT_LOGIN = re.compile(
    r"(?<![A-Za-z0-9])U(?=[A-Za-z0-9]{5,30}(?![A-Za-z0-9]))"
    r"(?=[A-Za-z0-9]*\d)[A-Za-z0-9]+"
)
_PRIVATE_FIELD = r'password|passwd|pwd|token|cookie|authorization|credential|webhook|phone|nickname|display_name|alternate_login_name|login_name|game_feature_code|profile_id|account_aliases|(?:target_|last_)?account|密码|令牌|凭证|手机号|昵称|特征码'
_SECRET = re.compile(
    rf'''(?i)((?:{_PRIVATE_FIELD})["']?\s*[=:]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;}}\]]+)''')
_PRIVATE_KEY = re.compile(rf'(?:{_PRIVATE_FIELD})$', re.I)
_AUTH_HEADER = re.compile(r'(?im)\b(Authorization|Cookie)\s*:\s*[^\r\n]+')
_LOGIN_URL = re.compile(r"https?://[^\s]+(?:login|oauth|auth|token)[^\s]*", re.I)
_CURRENT_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("okww_observation", default={})
_SENSITIVE_VALUES: set[str] = set()
_SENSITIVE_LOCK = threading.RLock()
_BASE_RECORD_FACTORY = logging.getLogRecordFactory()


def register_sensitive_values(values) -> None:
    with _SENSITIVE_LOCK:
        _SENSITIVE_VALUES.update(
            str(value) for value in values
            if value is not None and len(str(value)) >= 3
        )


def _registered_redaction(text: str) -> str:
    with _SENSITIVE_LOCK:
        values = sorted(_SENSITIVE_VALUES, key=len, reverse=True)
    for value in values:
        text = text.replace(value, "[REDACTED_ID]")
    return text


def redact_message(value: Any) -> str:
    text = _registered_redaction(str(value))
    if ("Config:init self.config =" in text or "OKTestRunner init_ok config:" in text
            or "ok:do_init, config:" in text or "ok-script init " in text and " config:" in text):
        return "[REDACTED_CONFIG]"
    text = _AUTH_HEADER.sub(lambda m: f'{m.group(1)}: [REDACTED]', text)
    text = _SECRET.sub(lambda m: f"{m.group(1)}[REDACTED]", text)
    text = _LOGIN_URL.sub("[REDACTED_URL]", text)
    text = _PHONE.sub("[REDACTED_PHONE]", text)
    text = _MASKED_PHONE.sub("[REDACTED_PHONE]", text)
    text = _ALT_LOGIN.sub("[REDACTED_LOGIN]", text)
    return text


def redact_data(value: Any, *, redact=redact_message) -> Any:
    """Preserve diagnostic JSON structure while removing nested identities/secrets."""
    if isinstance(value, dict):
        return {redact(str(key)): '[REDACTED]' if _PRIVATE_KEY.search(str(key)) else
                redact_data(item, redact=redact) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_data(item, redact=redact) for item in value]
    return redact(value) if isinstance(value, str) else value


class RedactingFilter(logging.Filter):
    """Redact a record before console, file, queue or UI handlers see it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_message(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = redact_message(
                "".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact_message(record.exc_text)
        return True


def _redacting_record_factory(*args, **kwargs):
    record = _BASE_RECORD_FACTORY(*args, **kwargs)
    RedactingFilter().filter(record)
    return record


def install_redaction_filters() -> None:
    if logging.getLogRecordFactory() is not _redacting_record_factory:
        logging.setLogRecordFactory(_redacting_record_factory)
    for logger in (logging.getLogger("ok"), logging.getLogger()):
        if not any(isinstance(item, RedactingFilter) for item in logger.filters):
            logger.addFilter(RedactingFilter())


def _reset_sensitive_values_for_tests() -> None:
    with _SENSITIVE_LOCK:
        _SENSITIVE_VALUES.clear()


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


__all__ = [
    "CorrelationContext", "Observation", "RedactingFilter", "SafeCallResult",
    "SafeModeReason", "StartupFailure", "install_redaction_filters",
    "redact_message", "register_sensitive_values", "safe_call",
]
