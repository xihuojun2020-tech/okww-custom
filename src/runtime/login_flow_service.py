"""Compatibility adapter for production login/switch methods."""

from __future__ import annotations

from typing import Any


class LoginFlowService:
    """Delegate to the existing MultiAccountDailyTask implementation.

    The adapter intentionally contains no OCR or click logic; this keeps the
    focused switch test on the exact production path.
    """

    def __init__(self, task: Any):
        self.task = task

    def switch_to_account(self, target: Any, *args, **kwargs):
        for name in ("switch_to_account", "_switch_to_account", "login_to_account"):
            method = getattr(self.task, name, None)
            if callable(method) and method is not self.switch_to_account:
                return method(target, *args, **kwargs)
        raise AttributeError("生产任务未提供账号切换方法")


__all__ = ["LoginFlowService"]
