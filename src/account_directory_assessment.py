"""Read-only assessment of a future one-JSON-file-per-account layout."""

from __future__ import annotations

import copy
from typing import Any, Mapping

from .account_identity import build_identity_index


_SUPPORTED_ROOT = {"schema_version", "config_id", "timezone", "profiles", "sequences", "extensions"}


def project_account_layout(master: Mapping[str, Any]) -> dict[str, Any]:
    profiles = master.get("profiles", {})
    return {
        "index.json": {
            key: copy.deepcopy(value) for key, value in master.items() if key != "profiles"
        },
        "accounts": {
            f"{profile_id}.json": {"profile_id": profile_id, **copy.deepcopy(dict(profile))}
            for profile_id, profile in profiles.items() if isinstance(profile, Mapping)
        },
    }


def round_trip_projection(master: Mapping[str, Any]) -> dict[str, Any]:
    layout = project_account_layout(master)
    result = copy.deepcopy(layout["index.json"])
    result["profiles"] = {
        payload["profile_id"]: {key: copy.deepcopy(value) for key, value in payload.items() if key != "profile_id"}
        for payload in layout["accounts"].values()
    }
    return result


def assess_account_directory_migration(master: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    profiles = master.get("profiles", {})
    if not isinstance(profiles, Mapping):
        blockers.append("profiles 不是对象")
        profiles = {}
    duplicates = sorted(key for key, owners in build_identity_index(profiles).items() if len(owners) > 1)
    if duplicates:
        blockers.append("存在重复账号身份，必须先消除歧义")
    unsupported = sorted(set(master) - _SUPPORTED_ROOT)
    if unsupported:
        warnings.append("存在需原样保留的未知根字段：" + ", ".join(unsupported))
    if round_trip_projection(master) != dict(master):
        blockers.append("投影无法无损往返")
    blockers.extend([
        "现有配置包、完整性指纹和回滚事务仍以单一 master 文件为边界",
        "尚未完成真实配置的双写、崩溃恢复和降级演练",
    ])
    return {
        "decision": "NO-GO",
        "projected_files": tuple(project_account_layout(master)["accounts"]),
        "blockers": tuple(blockers),
        "warnings": tuple(warnings),
        "writes_performed": False,
    }


__all__ = ["assess_account_directory_migration", "project_account_layout", "round_trip_projection"]
