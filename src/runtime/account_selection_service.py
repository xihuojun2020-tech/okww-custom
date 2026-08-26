"""Runtime account identity resolution shared by tasks and tests."""

from __future__ import annotations

from typing import Any, Mapping

from ..account_identity import AccountIdentityError, match_profile_identity


class AccountSelectionService:
    def __init__(self, repository: Any | None = None):
        self.repository = repository

    def _profiles(self, profiles: Mapping[str, Any] | None) -> Mapping[str, Any]:
        if profiles is not None:
            return profiles
        if self.repository is None:
            return {}
        result = {}
        for record in self.repository.list_profiles():
            result[str(record.profile_id)] = {**dict(record.account),
                                              "task_config": dict(record.tasks)}
        return result

    def resolve(self, observed: Any, profiles: Mapping[str, Any] | None = None) -> str:
        result = match_profile_identity(observed, self._profiles(profiles))
        if result is None:
            raise AccountIdentityError("找不到匹配的账号配置")
        return result


__all__ = ["AccountSelectionService"]
