"""Atomic per-account JSON storage used by the account editor.

The store is deliberately small: one UUID maps to one file, while the index
keeps only graph metadata and sequence membership.  Publication of a complete
runtime snapshot remains the responsibility of the publish service.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .config_integrity import atomic_write_json, canonical_json
from .account_repository import AccountRepositoryError, ProfileRevisionConflict


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


@dataclass(frozen=True)
class EditableProfile:
    profile_id: str
    revision: str
    payload: Mapping[str, Any]


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return copy.deepcopy(default)
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AccountRepositoryError(f"账号配置读取失败：{path}：{exc}") from exc


class AccountProfileStore:
    """Read and atomically write one account profile at a time."""

    def __init__(self, root: os.PathLike | str):
        base = Path(root).resolve()
        self.config_dir = base / "configs" if base.name.casefold() != "configs" else base
        self.root = self.config_dir / "accounts"
        self.profile_dir = self.root / "profiles"
        self.index_path = self.root / "index.json"

    def _validate_id(self, profile_id: str) -> str:
        value = str(profile_id).strip()
        if not _UUID_RE.fullmatch(value):
            raise AccountRepositoryError(f"账号 UUID 无效：{profile_id}")
        return value

    def _profile_path(self, profile_id: str) -> Path:
        return self.profile_dir / f"{self._validate_id(profile_id)}.json"

    def load_index(self) -> dict[str, Any]:
        raw = _read_json(self.index_path, {"schema_version": 1, "profile_ids": [], "sequences": {}})
        if not isinstance(raw, Mapping):
            raise AccountRepositoryError("账号索引必须是 JSON 对象")
        result = copy.deepcopy(dict(raw))
        profile_ids = result.get("profile_ids", [])
        sequences = result.get("sequences", {})
        if not isinstance(profile_ids, list) or any(not _UUID_RE.fullmatch(str(item)) for item in profile_ids):
            raise AccountRepositoryError("账号索引 profile_ids 无效")
        if not isinstance(sequences, Mapping) or any(
            not isinstance(name, str) or not isinstance(members, list)
            or any(str(member) not in profile_ids for member in members)
            for name, members in sequences.items()
        ):
            raise AccountRepositoryError("账号索引 sequences 无效")
        return result

    def _revision(self, value: Any) -> str:
        return _digest(value)

    def load_profile(self, profile_id: str) -> EditableProfile:
        profile_id = self._validate_id(profile_id)
        payload = _read_json(self._profile_path(profile_id), None)
        if not isinstance(payload, Mapping):
            raise AccountRepositoryError(f"账号文件不存在或结构无效：{profile_id}")
        payload = copy.deepcopy(dict(payload))
        embedded = payload.get("profile_id", profile_id)
        if str(embedded) != profile_id:
            raise AccountRepositoryError(f"账号文件 profile_id 不匹配：{profile_id}")
        payload["profile_id"] = profile_id
        return EditableProfile(profile_id, self._revision(payload), payload)

    def list_profile_ids(self) -> tuple[str, ...]:
        return tuple(str(item) for item in self.load_index().get("profile_ids", []))

    def write_profile(self, profile_id: str, payload: Mapping[str, Any], expected_revision: str = "") -> str:
        profile_id = self._validate_id(profile_id)
        if not isinstance(payload, Mapping):
            raise AccountRepositoryError("账号配置必须是 JSON 对象")
        current_path = self._profile_path(profile_id)
        current = self.load_profile(profile_id) if current_path.is_file() else None
        if expected_revision not in ("", None) and (current is None or current.revision != str(expected_revision)):
            raise ProfileRevisionConflict(f"账号 {profile_id} 已被其他修改")
        candidate = copy.deepcopy(dict(payload))
        if candidate.get("profile_id", profile_id) != profile_id:
            raise AccountRepositoryError("草稿不能修改 profile_id")
        candidate["profile_id"] = profile_id
        atomic_write_json(current_path, candidate)
        return self._revision(candidate)

    def write_index(self, payload: Mapping[str, Any], expected_revision: str = "") -> str:
        if not isinstance(payload, Mapping):
            raise AccountRepositoryError("账号索引必须是 JSON 对象")
        current = self.load_index()
        current_revision = self._revision(current)
        if expected_revision not in ("", None) and current_revision != str(expected_revision):
            raise ProfileRevisionConflict("账号索引已被其他修改")
        candidate = copy.deepcopy(dict(payload))
        atomic_write_json(self.index_path, candidate)
        return self._revision(candidate)


__all__ = ["AccountProfileStore", "EditableProfile"]
