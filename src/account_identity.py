# -*- coding: utf-8 -*-
"""Exact, side-effect-free account identity matching."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any


class AccountIdentityError(ValueError):
    pass


_SHORT_TOKEN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]\d+)(?![A-Za-z0-9])")
_SHORT_PREFIX = re.compile(r"^\s*[【[]?\s*([A-Za-z]\d+)(?![A-Za-z0-9])")
_PHONE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_MASKED_PHONE = re.compile(r"(?<!\d)(1[3-9]\d{2})\*{4}(\d{4})(?!\d)")
_ALIAS_FIELDS = ("备用识别名称内容", "Account Name", "account_name", "账号名称")


def normalize_identity(value: Any) -> str:
    return " ".join(str("" if value is None else value).split()).casefold()


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
    values.extend(split_identity_values(profile.get("account_aliases")))
    for source in (profile, profile.get("task_config")):
        if isinstance(source, Mapping):
            for key in _ALIAS_FIELDS:
                values.extend(split_identity_values(source.get(key)))
    return values


def profile_identity_values(profile_name: Any, profile: Mapping[str, Any] | None = None) -> frozenset[str]:
    return frozenset(_profile_values(profile_name, profile))


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
    "AccountIdentityError", "build_identity_index", "identity_candidates", "masked_phone",
    "normalize_identity", "profile_identity_values", "resolve_identity", "resolve_profile_identity",
    "resolve_profile_short_names", "short_profile_name", "split_identity_values",
]
