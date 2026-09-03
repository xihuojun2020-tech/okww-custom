"""Safe detached editing for one PC account profile."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .account_repository import ProfileEditScope, ProfileRevisionConflict
from .account_identity import masked_phone


class AccountConfigEditorError(RuntimeError):
    pass


class LockedProfileField(AccountConfigEditorError):
    pass


class AccountLabelMismatch(AccountConfigEditorError):
    pass


_PHONE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_TOKEN = re.compile(r"[A-Za-z0-9]{32,}")
_LOCKED_ACCOUNT = {
    # Identity is owned by the explicit re-bind workflow.  Keeping these
    # fields out of the ordinary task editor prevents an accidental save from
    # changing the account that a sequence or switch operation targets.
    "profile_id", "phone", "masked_phone", "nickname", "alternate_login_name",
    "account_aliases", "account_name", "Account Name", "账号名称", "game_feature_code",
}
LOCKED_IDENTITY_FIELDS = (
    "profile_id", "phone", "masked_phone", "nickname", "alternate_login_name",
    "game_feature_code", "account_aliases",
)
_LOCKED_TASK = {
    "phone", "masked_phone", "nickname", "alternate_login_name", "game_feature_code",
    "account_aliases", "Account Name", "account_name", "账号名称",
}
_ALIAS_ENABLE = "备用识别名称"
_ALIAS_TEXT = "备用识别名称内容"


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        value = _PHONE.sub(lambda match: match.group(1)[:3] + "****" + match.group(1)[-4:], value)
        return _TOKEN.sub(lambda match: match.group(0)[:8] + "****", value)
    if isinstance(value, Mapping):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_redact(item) for item in value)
    return value


def sanitize_error(error: BaseException) -> str:
    """Return GUI-safe exception text without phone numbers or long credentials."""
    return _redact(str(error))


@dataclass
class ProfileDraft:
    profile_id: str
    revision: str
    account: dict[str, Any]
    tasks: dict[str, Any]

    @property
    def scope(self) -> ProfileEditScope:
        return ProfileEditScope(self.profile_id, self.revision)


@dataclass(frozen=True)
class DiffEntry:
    path: str
    before: Any
    after: Any


@dataclass(frozen=True)
class ProfileDiff:
    profile_id: str
    account_label: str
    changes: tuple[DiffEntry, ...]

    @property
    def changed(self) -> bool:
        return bool(self.changes)


def _flatten(value: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        path = f"{prefix}.{key}"
        if isinstance(item, Mapping):
            result.update(_flatten(item, path))
        else:
            result[path] = item
    return result


class AccountConfigEditor:
    """Draft, preview, confirm, backup, then CAS-publish one profile."""

    locked_identity_fields = LOCKED_IDENTITY_FIELDS

    def __init__(self, repository: Any, backup_service: Any | None = None):
        self.repository = repository
        self.backup_service = backup_service or repository

    def load_draft(self, profile_id: str) -> ProfileDraft:
        record = self.repository.load_profile(profile_id)
        return ProfileDraft(record.profile_id, str(record.revision),
                            copy.deepcopy(dict(record.account)), copy.deepcopy(dict(record.tasks)))

    def preview_diff(self, draft: ProfileDraft) -> ProfileDiff:
        current = self.repository.load_profile(draft.profile_id)
        before = {**_flatten(current.account, "账号"), **_flatten(current.tasks, "任务")}
        after = {**_flatten(draft.account, "账号"), **_flatten(draft.tasks, "任务")}
        changes = tuple(DiffEntry(path, _redact(before.get(path)), _redact(after.get(path)))
                        for path in sorted(set(before) | set(after))
                        if before.get(path) != after.get(path))
        return ProfileDiff(draft.profile_id, str(draft.account.get("display_name", draft.profile_id)), changes)

    def _validate_locked(self, draft: ProfileDraft) -> None:
        current = self.repository.load_profile(draft.profile_id)
        for key in _LOCKED_ACCOUNT:
            if draft.account.get(key) != current.account.get(key):
                raise LockedProfileField(f"字段不可在此页面修改：{key}")
        for key in _LOCKED_TASK:
            if draft.tasks.get(key) != current.tasks.get(key):
                raise LockedProfileField(f"字段不可在此页面修改：{key}")

    def save_draft(self, scope: ProfileEditScope, draft: ProfileDraft, *,
                   confirmed_account_label: str, sequence_ids: tuple[str, ...] | None = None) -> Any:
        if scope.profile_id != draft.profile_id or str(scope.base_revision) != str(draft.revision):
            raise ProfileRevisionConflict("草稿范围已失效")
        current = self.repository.load_profile(draft.profile_id)
        if str(current.revision) != str(scope.base_revision):
            raise ProfileRevisionConflict("账号配置已被其他操作修改")
        label = str(current.account.get("display_name", draft.profile_id))
        if confirmed_account_label != label:
            raise AccountLabelMismatch("确认的账号短名不匹配")
        self._validate_locked(draft)
        alias_enabled = draft.tasks.get(_ALIAS_ENABLE)
        alias_text = str(draft.tasks.get(_ALIAS_TEXT) or "").strip()
        if alias_enabled not in (None, "无", "使用"):
            raise AccountConfigEditorError("备用识别名称必须选择“无”或“使用”")
        if alias_enabled == "使用" and not alias_text:
            raise AccountConfigEditorError("启用备用识别名称后必须填写具体名称")
        self.backup_service.backup_profile(draft.profile_id, {
            "profile_id": draft.profile_id, "revision": current.revision,
            "account": copy.deepcopy(dict(current.account)), "tasks": copy.deepcopy(dict(current.tasks)),
            "sequence_ids": tuple(sequence_ids) if sequence_ids is not None else None,
        })
        account = copy.deepcopy(draft.account)
        tasks = copy.deepcopy(draft.tasks)
        if alias_enabled is not None:
            tasks[_ALIAS_TEXT] = alias_text
            account["alternate_login_name"] = alias_text if alias_enabled == "使用" else ""
        payload = {"account": account, "tasks": tasks}
        if sequence_ids is not None:
            payload["sequence_ids"] = tuple(sequence_ids)
        return self.repository.publish_profile(scope, payload, source="账号配置页面")

    def load_template(self, fallback_profile_id: str | None = None) -> Any:
        return self.repository.load_profile_template(fallback_profile_id)

    def save_template(self, tasks: Mapping[str, Any], *, expected_revision: str) -> Any:
        if not isinstance(tasks, Mapping):
            raise AccountConfigEditorError("新账号模板必须是 JSON 对象")
        return self.repository.publish_profile_template(tasks, expected_revision=expected_revision)

    def create_profile(self, template: Any, *, display_name: str, phone: str, nickname: str,
                       game_feature_code: str = "", alias_enabled: bool = False,
                       alias_text: str = "", sequence_ids: tuple[str, ...] = ()) -> Any:
        label = str(display_name or "").strip().upper()
        full_phone = re.sub(r"\s+", "", str(phone or ""))
        nickname = str(nickname or "").strip()
        feature_code = str(game_feature_code or "").strip()
        alias = str(alias_text or "").strip()
        if not re.fullmatch(r"[A-Z]\d+", label):
            raise AccountConfigEditorError("账号短名必须为一个字母加数字，例如 A5")
        if not re.fullmatch(r"1[3-9]\d{9}", full_phone):
            raise AccountConfigEditorError("完整手机号格式无效")
        if not nickname:
            raise AccountConfigEditorError("游戏昵称不能为空")
        if alias_enabled and not alias:
            raise AccountConfigEditorError("启用备用识别名称后必须填写具体名称")
        tasks = copy.deepcopy(dict(template.tasks))
        tasks[_ALIAS_ENABLE] = "使用" if alias_enabled else "无"
        tasks[_ALIAS_TEXT] = alias
        account = {
            "display_name": label,
            "phone": full_phone,
            "masked_phone": masked_phone(full_phone),
            "nickname": nickname,
            "alternate_login_name": alias if alias_enabled else "",
            "game_feature_code": feature_code,
            "account_aliases": [],
        }
        return self.repository.create_profile(
            account, tasks, sequence_ids=tuple(sequence_ids),
            expected_revision=str(template.revision),
        )

    def delete_profile(self, scope: ProfileEditScope, *, confirmed_account_label: str) -> Any:
        current = self.repository.load_profile(scope.profile_id)
        if str(current.revision) != str(scope.base_revision):
            raise ProfileRevisionConflict("账号配置已被其他操作修改")
        label = str(current.account.get("display_name") or current.account.get("short_name") or "未命名账号")
        if confirmed_account_label != label:
            raise AccountLabelMismatch("确认的账号短名不匹配")
        return self.repository.delete_profile_cascade(
            scope.profile_id, expected_revision=str(scope.base_revision)
        )


__all__ = ["AccountConfigEditor", "AccountConfigEditorError", "AccountLabelMismatch",
           "DiffEntry", "LockedProfileField", "ProfileDiff", "ProfileDraft", "ProfileEditScope",
           "LOCKED_IDENTITY_FIELDS", "sanitize_error"]
