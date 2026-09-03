# -*- coding: utf-8 -*-
"""Exact, side-effect-free account identity matching."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


class AccountIdentityError(ValueError):
    pass


_SHORT_TOKEN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]\d+)(?![A-Za-z0-9])")
_SHORT_PREFIX = re.compile(r"^\s*[【[]?\s*([A-Za-z]\d+)(?![A-Za-z0-9])")
_PHONE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_MASKED_PHONE = re.compile(r"(?<!\d)(1[3-9]\d{2})\*{4}(\d{4})(?!\d)")
_ALIAS_FIELDS = ("备用识别名称内容", "Account Name", "account_name", "账号名称")
_ALTERNATE_NAME = re.compile(r"^U[A-Za-z0-9]+A$", re.IGNORECASE)


@dataclass(frozen=True)
class AccountIdentity:
    profile_id: str
    phone: str | None = None
    masked_phone: str | None = None
    nickname: str | None = None
    display_name: str | None = None
    alternate_login_name: str | None = None
    game_feature_code: str | None = None


def normalize_identity(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str("" if value is None else value))
    return " ".join(text.split()).casefold()


def split_identity_values(value: Any) -> list[str]:
    values = list(value) if isinstance(value, (list, tuple, set)) else re.split(r"[,，；;\r\n]+", str(value or ""))
    return [str(item).strip() for item in values if str(item).strip()]


def masked_phone(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value))
    return digits[:3] + "****" + digits[-4:] if len(digits) >= 7 else "****"


def identity_candidates(value: Any) -> frozenset[str]:
    text = normalize_identity(value)
    if not text:
        return frozenset()
    result = {text}
    result.update(match.group(1).casefold() for match in _SHORT_TOKEN.finditer(text))
    result.update(masked_phone(phone).casefold() for phone in _PHONE.findall(text))
    result.update((match.group(1) + "****" + match.group(2)).casefold() for match in _MASKED_PHONE.finditer(text))
    return frozenset(result)


def short_profile_name(value: Any) -> str | None:
    match = _SHORT_PREFIX.search(str(value or ""))
    return match.group(1).upper() if match else None


def _safe_profile_label(value: Any) -> str:
    return short_profile_name(value) or "未命名账号"


def _profile_values(name: Any, profile: Mapping[str, Any] | None) -> list[str]:
    profile = profile if isinstance(profile, Mapping) else {}
    values = [str(name)]
    for key in ("profile_id", "display_name"):
        if profile.get(key):
            values.append(str(profile[key]))
    # Feature codes are intentionally excluded from ordinary matching. They
    # become an identity source only when strict_feature_code=True.
    for key in ("phone", "masked_phone", "nickname"):
        if profile.get(key):
            values.append(str(profile[key]))
    values.extend(split_identity_values(profile.get("account_aliases")))
    task_config = profile.get("task_config") if isinstance(profile.get("task_config"), Mapping) else {}
    alias_mode = normalize_identity(task_config.get("备用识别名称"))
    alias_enabled = alias_mode in {"使用", "use", "enabled", "true"}
    alias_disabled = alias_mode in {"无", "不使用", "disabled", "false"}
    if not alias_disabled and profile.get("alternate_login_name"):
        values.append(str(profile["alternate_login_name"]))
    sources = (profile, task_config) if not alias_disabled else ()
    for source in sources:
        if isinstance(source, Mapping):
            for key in _ALIAS_FIELDS:
                if alias_enabled or not alias_mode:
                    values.extend(split_identity_values(source.get(key)))
    return values


def profile_identity_values(profile_name: Any, profile: Mapping[str, Any] | None = None) -> frozenset[str]:
    return frozenset(_profile_values(profile_name, profile))


def _text_field(profile: Mapping[str, Any], key: str) -> str | None:
    value = profile.get(key)
    if value is None:
        return None
    value = " ".join(str(value).split()).strip()
    return value or None


def extract_account_identity(profile_id: str, profile: Mapping[str, Any]) -> AccountIdentity:
    """Extract explicit identity fields while retaining legacy alias formats."""
    profile = profile if isinstance(profile, Mapping) else {}
    task_config = profile.get("task_config") if isinstance(profile.get("task_config"), Mapping) else {}
    aliases = split_identity_values(profile.get("account_aliases"))
    alias_mode = normalize_identity(task_config.get("备用识别名称"))
    alias_disabled = alias_mode in {"无", "不使用", "disabled", "false"}
    legacy_aliases: list[str] = []
    for source in (() if alias_disabled else (profile, task_config)):
        for key in _ALIAS_FIELDS:
            legacy_aliases.extend(split_identity_values(source.get(key)))
    alternate = None if alias_disabled else _text_field(profile, "alternate_login_name")
    if alternate is None:
        alternate = next((value for value in [*aliases, *legacy_aliases]
                          if _ALTERNATE_NAME.fullmatch(value)), None)
    return AccountIdentity(
        profile_id=str(profile_id),
        phone=_text_field(profile, "phone"),
        masked_phone=_text_field(profile, "masked_phone"),
        nickname=_text_field(profile, "nickname"),
        display_name=_text_field(profile, "display_name"),
        alternate_login_name=alternate,
        game_feature_code=_text_field(profile, "game_feature_code"),
    )


def build_identity_index(profiles: Mapping[Any, Any] | Iterable[Any]) -> dict[str, frozenset[str]]:
    index: dict[str, set[str]] = {}
    items = profiles.items() if isinstance(profiles, Mapping) else ((name, {}) for name in profiles)
    for name, profile in items:
        owner = str(name)
        for value in _profile_values(owner, profile if isinstance(profile, Mapping) else {}):
            for candidate in identity_candidates(value):
                index.setdefault(candidate, set()).add(owner)
    return {key: frozenset(value) for key, value in index.items()}


def resolve_profile_identity(observed: Any, profiles: Mapping[Any, Any] | Iterable[Any]) -> str | None:
    return match_profile_identity(observed, profiles)


def match_profile_identity(observed: Any, profiles: Mapping[Any, Any] | Iterable[Any], *,
                           strict_feature_code: bool = False) -> str | None:
    """Resolve identity with masked phone priority and optional feature-code checking."""
    items = profiles.items() if isinstance(profiles, Mapping) else ((name, {}) for name in profiles)
    items = list(items)
    observed_text = normalize_identity(observed)
    if strict_feature_code:
        feature_matches = {
            str(name) for name, profile in items
            if (feature := extract_account_identity(str(name), profile if isinstance(profile, Mapping) else {}).game_feature_code)
            and normalize_identity(feature) == observed_text
        }
        if len(feature_matches) > 1:
            raise AccountIdentityError("游戏内特征码同时匹配多个账号方案")
        if feature_matches:
            return next(iter(feature_matches))

    masked_matches = {
        str(name) for name, profile in items
        if (masked := extract_account_identity(str(name), profile if isinstance(profile, Mapping) else {}).masked_phone)
        and normalize_identity(masked) == observed_text
    }
    if len(masked_matches) > 1:
        labels = sorted({_safe_profile_label(match) for match in masked_matches})
        raise AccountIdentityError("脱敏手机号同时匹配多个账号方案：" + ", ".join(labels))
    if masked_matches:
        return next(iter(masked_matches))

    return _resolve_profile_identity_legacy(observed, dict(items))


def _resolve_profile_identity_legacy(observed: Any, profiles: Mapping[Any, Any]) -> str | None:
    matches: set[str] = set()
    index = build_identity_index(profiles)
    text = normalize_identity(observed)
    candidates = {text} if text else set()
    if re.fullmatch(r"[a-z]\d+", text):
        candidates.add(text)
    candidates.update(masked_phone(phone).casefold() for phone in _PHONE.findall(text))
    candidates.update((match.group(1) + "****" + match.group(2)).casefold()
                      for match in _MASKED_PHONE.finditer(text))
    for candidate in candidates:
        matches.update(index.get(candidate, ()))
    if len(matches) > 1:
        labels = sorted({_safe_profile_label(match) for match in matches})
        raise AccountIdentityError("账号身份同时匹配多个账号方案：" + ", ".join(labels))
    return next(iter(matches), None)


resolve_identity = resolve_profile_identity


def resolve_profile_short_names(short_names: Iterable[Any], profiles: Mapping[Any, Any] | Iterable[Any]) -> list[str]:
    requested = [str(value).strip() for value in short_names or () if str(value).strip()]
    if not requested:
        raise AccountIdentityError("连续账号顺序不能为空")
    result = []
    for value in requested:
        match = resolve_profile_identity(value, profiles)
        if match is None:
            raise AccountIdentityError("找不到账号配置")
        result.append(match)
    return result


__all__ = [
    "AccountIdentity", "AccountIdentityError", "build_identity_index", "extract_account_identity",
    "identity_candidates", "match_profile_identity", "masked_phone",
    "normalize_identity", "profile_identity_values", "resolve_identity", "resolve_profile_identity",
    "resolve_profile_short_names", "short_profile_name", "split_identity_values",
]
