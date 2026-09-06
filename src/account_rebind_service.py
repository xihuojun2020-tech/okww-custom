"""Explicit, auditable account-identity re-binding.

Normal account editing deliberately cannot change identity fields.  This
service is the only write path for those fields: it validates the requested
identity, checks collisions, takes an account-scoped backup, and publishes a
CAS-protected profile update.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping

from .account_config_editor import sanitize_error
from .account_identity import (
    AccountIdentityError,
    build_identity_index,
    identity_candidates,
    normalize_identity,
)
from .account_repository import ProfileEditScope, ProfileRevisionConflict


_IDENTITY_FIELDS = (
    "phone", "masked_phone", "nickname", "alternate_login_name",
    "game_feature_code", "account_aliases",
)


@dataclass(frozen=True)
class RebindPreview:
    profile_id: str
    current_identity: Mapping[str, Any]
    new_identity: Mapping[str, Any]
    changes: tuple[str, ...]
    conflicts: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.changes)


def _display_label(profile_id: str, account: Mapping[str, Any]) -> str:
    return str(account.get("display_name") or account.get("short_name") or profile_id)


def _identity_mapping(account: Mapping[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(account.get(key)) for key in _IDENTITY_FIELDS
            if account.get(key) not in (None, "", [])}


def _values_for_field(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


class AccountRebindService:
    """Rebind identity through one explicit confirmation and repository CAS."""

    def __init__(self, repository: Any, backup_service: Any | None = None):
        self.repository = repository
        self.backup_service = backup_service or repository

    def _profiles(self) -> dict[str, Mapping[str, Any]]:
        profiles: dict[str, Mapping[str, Any]] = {}
        for record in self.repository.list_profiles():
            profiles[str(record.profile_id)] = dict(record.account)
        return profiles

    @staticmethod
    def _validate_identity(new_identity: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(new_identity, Mapping):
            raise AccountIdentityError("新身份必须是 JSON 对象")
        unknown = set(new_identity) - set(_IDENTITY_FIELDS)
        if unknown:
            raise AccountIdentityError("包含不支持的身份字段")
        result = {key: copy.deepcopy(new_identity[key]) for key in _IDENTITY_FIELDS
                  if key in new_identity}
        if not result or not any(_values_for_field(value) for value in result.values()):
            raise AccountIdentityError("新身份不能为空")
        if "alternate_login_name" in result:
            value = str(result["alternate_login_name"] or "").strip()
            if value and not (value.upper().startswith("U") and value.upper().endswith("A")):
                raise AccountIdentityError("备用识别名必须为 U…A 格式")
            result["alternate_login_name"] = value
        return result

    def _collision_labels(self, profile_id: str, new_identity: Mapping[str, Any]) -> tuple[str, ...]:
        profiles = self._profiles()
        # Build the same conservative candidate index used by runtime account
        # switching, then test only fields supplied by the re-bind request.
        index = build_identity_index(profiles)
        collisions: set[str] = set()
        for value in new_identity.values():
            for item in _values_for_field(value):
                for candidate in identity_candidates(item):
                    for owner in index.get(candidate, ()):
                        if owner != profile_id:
                            collisions.add(owner)
        return tuple(sorted(_display_label(owner, profiles[owner]) for owner in collisions))

    def preview(self, profile_id: str, new_identity: Mapping[str, Any]) -> RebindPreview:
        record = self.repository.load_profile(profile_id)
        requested = self._validate_identity(new_identity)
        conflicts = self._collision_labels(str(profile_id), requested)
        if conflicts:
            raise AccountIdentityError("新身份已被其他账号占用：" + ", ".join(conflicts))
        current = _identity_mapping(record.account)
        changes = tuple(key for key in requested
                        if normalize_identity(current.get(key)) != normalize_identity(requested[key]))
        return RebindPreview(str(profile_id), current, requested, changes)

    def rebind(self, profile_id: str, current_identity: Any,
               new_identity: Mapping[str, Any], confirmed: bool = False, *, expected_revision=None) -> Any:
        record = self.repository.load_profile(profile_id)
        if expected_revision is not None and str(record.revision) != str(expected_revision):
            raise ProfileRevisionConflict('账号配置已被其他操作修改，请重新预览身份绑定')
        current = _identity_mapping(record.account)
        observed = normalize_identity(current_identity)
        known = set()
        for value in current.values():
            for item in _values_for_field(value):
                known.update(identity_candidates(item))
        if not observed or observed not in known:
            raise AccountIdentityError("当前身份确认失败，请重新载入账号后再试")
        preview = self.preview(profile_id, new_identity)
        if not preview.changed:
            return record
        if not confirmed:
            raise AccountIdentityError("重新绑定必须经过显式确认")
        self.backup_service.backup_profile(profile_id, {
            "profile_id": str(profile_id),
            "revision": record.revision,
            "account": copy.deepcopy(dict(record.account)),
            "tasks": copy.deepcopy(dict(record.tasks)),
            "reason": "identity_rebind",
        })
        account = copy.deepcopy(dict(record.account))
        account.update(copy.deepcopy(dict(preview.new_identity)))
        scope = ProfileEditScope(str(profile_id), str(record.revision))
        try:
            return self.repository.publish_profile(
                scope, {"account": account, "tasks": copy.deepcopy(dict(record.tasks))},
                source="账号身份重新绑定",
            )
        except ProfileRevisionConflict:
            raise
        except Exception as exc:
            # Do not leak full phone numbers or credentials through GUI text.
            raise AccountIdentityError(sanitize_error(exc)) from exc


__all__ = ["AccountRebindService", "RebindPreview"]
