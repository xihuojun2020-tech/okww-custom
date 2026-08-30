"""Side-effect-free post-selection account verification."""

from __future__ import annotations

from typing import Any, Mapping

from ..account_identity import AccountIdentityError
from .account_selection_service import AccountSelectionService


class AccountVerificationService:
    def __init__(self, selection: AccountSelectionService | None = None, *,
                 strict_feature_code: bool = False):
        self.selection = selection or AccountSelectionService()
        self.strict_feature_code = bool(strict_feature_code)

    def resolve_observed(self, observed: Any,
                         profiles: Mapping[str, Any] | None = None) -> str | None:
        return self.selection.resolve_optional(
            observed, profiles, strict_feature_code=self.strict_feature_code)

    def verify(self, expected: str, observed: Any,
               profiles: Mapping[str, Any] | None = None) -> str:
        available = self.selection._profiles(profiles)
        canonical_expected = (
            str(expected) if str(expected) in available
            else self.selection.resolve(str(expected), available)
        )
        actual = self.resolve_observed(observed, available)
        if actual is None:
            raise AccountIdentityError("无法确认当前登录账号")
        if actual != canonical_expected:
            raise AccountIdentityError("当前登录账号与任务目标不一致")
        return actual


__all__ = ["AccountVerificationService"]
