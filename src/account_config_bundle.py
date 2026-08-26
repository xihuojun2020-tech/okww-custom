# -*- coding: utf-8 -*-
"""Account configuration bundles and legacy sequence migration.

This module is intentionally file-oriented and UI-agnostic.  Consumers get a
read-only preflight result and an explicit, transactional import/repair API;
no operation silently merges two competing sequence sources.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from . import config_integrity as ci


BUNDLE_TYPE = "okww_account_bundle"
BUNDLE_VERSION = 3
_TASK_SEQUENCE_RE = re.compile(r"^\s*序列\s*(\d+)\s*账号\s*$")
_CHINESE_SEQUENCE_RE = re.compile(r"^\s*序列\s*([一二三四五六七八九十百千万零〇两]+)\s*$")
_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_PREFERENCE_EXCLUDED_KEYS = {"当前执行账号"}
_PARTITION_NAMES = ("master_config", "runtime_data", "preferences", "extensions")
_NON_PORTABLE_RUNTIME_KEYS = {
    "accepted_master_fingerprint",
    "last_accepted_fingerprint",
    "last_integrity_event",
    "last_bundle_import",
}
_REDACTED = "[REDACTED]"
_SECRET_KEY_RE = re.compile(
    r"(?:^|[_\-. ])(?:password|passwd|pwd|token|access[_\-. ]?token|refresh[_\-. ]?token|"
    r"id[_\-. ]?token|api[_\-. ]?key|apikey|secret|pat|personal[_\-. ]?access[_\-. ]?token|"
    r"authorization|credential|cookie|auth|密码|令牌|口令|鉴权|凭证|密钥)(?:$|[_\-. ])", re.IGNORECASE)
_SECRET_QUERY_RE = re.compile(
    r"(?:password|passwd|pwd|token|access[_\-. ]?token|refresh[_\-. ]?token|"
    r"api[_\-. ]?key|apikey|secret|pat|authorization|credential)\s*=",
    re.IGNORECASE,
)
_AUTH_URL_RE = re.compile(
    r"https?://[^\s]+(?:auth|oauth|login|token|pat)(?:[^\s]*)",
    re.IGNORECASE,
)


class BundleImportBlocked(RuntimeError):
    """Raised until a caller explicitly confirms a potentially destructive action."""


class ConfigBundleError(BundleImportBlocked):
    """Raised when a bundle cannot pass its structural/configuration checks."""


def _sensitive_key(key: Any) -> bool:
    text = str(key).strip()
    return bool(_SECRET_KEY_RE.search(text) or
                any(term in text for term in ("密码", "令牌", "口令", "鉴权", "凭证", "密钥")))


def _redact_sensitive(value: Any, *, key: Any = None) -> Any:
    """Recursively remove credentials while retaining ordinary identities.

    Full phone numbers are deliberately not treated as secrets: the existing
    identity index uses them to match masked OCR phone numbers during import.
    """
    if _sensitive_key(key):
        return _REDACTED
    if isinstance(value, Mapping):
        return {copy.deepcopy(item_key): _redact_sensitive(item, key=item_key)
                for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_sensitive(item) for item in value]
    if isinstance(value, str):
        if _SECRET_QUERY_RE.search(value) or _AUTH_URL_RE.search(value):
            return _REDACTED
    return copy.deepcopy(value)


def _validate_bundle_shapes(bundle: Mapping[str, Any], *, v3: bool = False) -> list[str]:
    """Reject malformed nested objects before validators can hit unhashables."""
    errors: list[str] = []
    master = bundle.get("master_config")
    if master is not None and not isinstance(master, Mapping):
        errors.append("配置包 master_config 必须是对象")
    if isinstance(master, Mapping):
        profiles = master.get("profiles")
        if profiles is not None and not isinstance(profiles, Mapping):
            errors.append("配置包 profiles 必须是对象")
        elif isinstance(profiles, Mapping):
            for profile_id, profile in profiles.items():
                if not isinstance(profile, Mapping):
                    errors.append(f"配置包账号 {profile_id!r} 必须是对象")
                    continue
                if profile.get("profile_id", profile_id) != profile_id:
                    errors.append(f"配置包账号 {profile_id!r} 的 profile_id 不匹配")
                for name in ("phone", "masked_phone", "nickname", "alternate_login_name", "game_feature_code"):
                    if name in profile and not isinstance(profile[name], str):
                        errors.append(f"配置包账号 {profile_id!r}.{name} 必须是字符串")
                for name in ("account_aliases",):
                    if name in profile and (not isinstance(profile[name], list) or
                                            not all(isinstance(item, str) and item.strip()
                                                    for item in profile[name])):
                        errors.append(f"配置包账号 {profile_id!r}.{name} 必须是非空字符串列表")
                for name in ("task_config", "schedule", "extensions"):
                    if name in profile and not isinstance(profile[name], Mapping):
                        errors.append(f"配置包账号 {profile_id!r}.{name} 必须是对象")
        sequences = master.get("sequences")
        if sequences is not None and not isinstance(sequences, Mapping):
            errors.append("配置包 sequences 必须是对象")
        elif isinstance(sequences, Mapping):
            for name, members in sequences.items():
                if not isinstance(members, list):
                    errors.append(f"配置包序列 {name!r} 的 members 必须是列表")
                elif any(not isinstance(member, str) for member in members):
                    errors.append(f"配置包序列 {name!r} 的成员必须是字符串 UUID")
    if v3:
        for name in ("accounts", "profiles", "devices", "device", "members"):
            if name in bundle and not isinstance(bundle[name], Mapping):
                errors.append(f"配置包 {name} 必须是对象")
        if "sequences" in bundle:
            sequences = bundle["sequences"]
            if not isinstance(sequences, Mapping):
                errors.append("配置包 sequences 必须是对象")
            else:
                for name, members in sequences.items():
                    if not isinstance(members, list) or any(not isinstance(item, str)
                                                            for item in members):
                        errors.append(f"配置包序列 {name!r} 的 members 必须是字符串列表")
    return errors


class SequenceSourceConflict(ValueError):
    """Raised when two non-empty legacy sequence sources differ."""

    def __init__(self, differences: list[dict[str, Any]]):
        self.differences = differences
        super().__init__("sequence sources conflict: " + json.dumps(differences, ensure_ascii=False))


def _sequence_name(name: Any) -> str:
    text = " ".join(str(name).split()).strip()
    match = _TASK_SEQUENCE_RE.match(text)
    if match:
        return f"序列{int(match.group(1))}"
    match = _CHINESE_SEQUENCE_RE.match(text)
    if match:
        digits = match.group(1)
        # Current UI uses 一至十.  Keep a conservative parser for larger
        # Chinese numbers so this migration never drops a named sequence.
        if digits in _CN_DIGITS:
            return f"序列{_CN_DIGITS[digits]}"
    return text


def _canonical_sequences(value: Mapping[str, Any] | None) -> dict[str, list[Any]]:
    if not isinstance(value, Mapping):
        raise ValueError("sequences must be an object")
    result: dict[str, list[Any]] = {}
    for name, members in value.items():
        if not isinstance(members, list):
            raise ValueError(f"sequence {name!r} must be a list")
        # Preserve the source's display form (notably ``序列一``) for the
        # working projection.  Comparison normalizes numeric/Chinese forms
        # separately, while the selected source retains its order and label.
        canonical = " ".join(str(name).split()).strip()
        if not canonical:
            raise ValueError("sequence names must be non-empty")
        if canonical in result:
            raise SequenceSourceConflict([{"sequence": canonical, "kind": "duplicate_name"}])
        result[canonical] = copy.deepcopy(members)
    return result


def extract_task_sequences(task_data: Mapping[str, Any] | None) -> dict[str, list[Any]]:
    """Extract only explicit ``序列 N 账号`` fields from legacy task JSON."""
    if not isinstance(task_data, Mapping):
        return {}
    result: dict[str, list[Any]] = {}
    for key, value in task_data.items():
        match = _TASK_SEQUENCE_RE.match(str(key))
        if not match:
            continue
        if not isinstance(value, list):
            raise ValueError(f"{key} must be a list")
        canonical = f"序列{int(match.group(1))}"
        if canonical in result:
            raise SequenceSourceConflict([{"sequence": canonical, "kind": "duplicate_name"}])
        result[canonical] = copy.deepcopy(value)
    return result


@dataclass(frozen=True)
class SequenceMergeResult:
    sequences: dict[str, list[Any]]
    source: str
    differences: list[dict[str, Any]] = field(default_factory=list)


def merge_sequence_sources(working_sequences: Mapping[str, Any] | None,
                           task_sequences: Mapping[str, Any] | None) -> SequenceMergeResult:
    """Apply the strict single-source/equal-source/conflict policy."""
    primary = _canonical_sequences(working_sequences or {})
    secondary = _canonical_sequences(task_sequences or {})
    def comparable(values: Mapping[str, list[Any]]) -> dict[str, list[Any]]:
        return {_sequence_name(name): members for name, members in values.items()}

    primary_cmp = comparable(primary)
    secondary_cmp = comparable(secondary)
    if primary and secondary:
        if ci._canonical(primary_cmp) == ci._canonical(secondary_cmp):
            return SequenceMergeResult(primary, "both_equal")
        names = list(dict.fromkeys([*primary_cmp, *secondary_cmp]))
        differences = [{"sequence": name, "working": primary_cmp.get(name), "task": secondary_cmp.get(name)}
                       for name in names if primary_cmp.get(name) != secondary_cmp.get(name)]
        raise SequenceSourceConflict(differences)
    if primary:
        return SequenceMergeResult(primary, "working")
    if secondary:
        return SequenceMergeResult(secondary, "task")
    return SequenceMergeResult({}, "empty")


def resolve_sequence_members(sequences: Mapping[str, Any], master: Mapping[str, Any]) -> dict[str, list[str]]:
    """Map old display names, aliases, short names and phones to UUIDs."""
    index = ci._master_identity_index(master)
    profiles = master.get("profiles", {})
    result: dict[str, list[str]] = {}
    for name, members in _canonical_sequences(sequences).items():
        resolved: list[str] = []
        for member in members:
            if not isinstance(member, str) or not member.strip():
                raise ValueError(f"sequence {name!r} contains an invalid account reference")
            matches = {member} if member in profiles else set()
            if not matches:
                for candidate in ci._identity_candidates(member):
                    matches.update(index.get(candidate, set()))
            if not matches:
                raise ValueError(f"sequence {name!r} references unknown account {member!r}")
            if len(matches) != 1:
                raise ValueError(f"sequence {name!r} account {member!r} is ambiguous")
            resolved.append(next(iter(matches)))
        result[name] = resolved
    return result


def _digest(value: Any) -> str:
    return hashlib.sha256(ci.canonical_json(value).encode("utf-8")).hexdigest()


def _portable_runtime(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return runtime state that is safe and meaningful on another device."""
    if not isinstance(value, Mapping):
        return {}
    return {str(key): copy.deepcopy(item) for key, item in value.items()
            if str(key) not in _NON_PORTABLE_RUNTIME_KEYS}


def _merge_legacy_completions(runtime: dict[str, Any], profile_id: str,
                              completed: Any) -> None:
    """Merge embedded v1 completion records without replacing newer runtime data."""
    if not isinstance(completed, Mapping):
        return
    completed_at = runtime.get("completed_at")
    if not isinstance(completed_at, dict):
        completed_at = {}
        runtime["completed_at"] = completed_at
    target = completed_at.get(profile_id)
    if not isinstance(target, dict):
        target = {}
        completed_at[profile_id] = target
    for task_name, completed_time in completed.items():
        target.setdefault(str(task_name), copy.deepcopy(completed_time))


def _read_optional(path: Path) -> tuple[Any, bytes | None]:
    if not path.is_file():
        return {}, None
    return ci._read_json(path)


def _atomic_replace_unchecked(path: Path, payload: bytes) -> None:
    """Atomic byte rollback for the protected master path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".rollback", dir=str(path.parent))
    try:
        with open(fd, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
        Path(temp_name).replace(path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


@dataclass
class BundlePreflight:
    ok: bool
    trust_required: bool = False
    errors: list[str] = field(default_factory=list)
    differences: list[dict[str, Any]] = field(default_factory=list)
    candidate_master: dict[str, Any] | None = None
    candidate_runtime: dict[str, Any] | None = None
    candidate_preferences: dict[str, Any] | None = None
    bundle: dict[str, Any] | None = None
    account_count: int = 0
    sequence_count: int = 0
    runtime_record_count: int = 0
    diff_summary: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "trust_required": self.trust_required,
                "errors": list(self.errors), "differences": copy.deepcopy(self.differences),
                "account_count": self.account_count, "sequence_count": self.sequence_count,
                "runtime_record_count": self.runtime_record_count,
                "diff_summary": list(self.diff_summary)}

    to_dict = as_dict


class AccountConfigBundleService:
    """Export, preflight and transactionally import account bundle v2 files."""

    def __init__(self, root: str | Path | None = None, *, integrity_service: ci.ConfigIntegrityService | None = None,
                 transaction_snapshot_hook: Any | None = None):
        self.integrity = integrity_service or ci.ConfigIntegrityService(root)
        self.paths = self.integrity.paths
        self.transaction_snapshot_hook = transaction_snapshot_hook

    def _preferences(self) -> dict[str, Any]:
        data, _ = _read_optional(self.paths.multi_account_task or self.paths.config_dir / "MultiAccountDailyTask.json")
        if not isinstance(data, Mapping):
            return {}
        return {str(k): copy.deepcopy(v) for k, v in data.items()
                if not _TASK_SEQUENCE_RE.match(str(k)) and str(k) not in _PREFERENCE_EXCLUDED_KEYS}

    def export_bundle(self, destination: str | Path | None = None, *, extensions: Mapping[str, Any] | None = None) -> dict[str, Any]:
        result = self.integrity.check(record_incident=False)
        if not result.ok or not result.master:
            raise BundleImportBlocked("export requires a trusted, fully verified account configuration")
        master_raw, _ = ci._read_json(self.paths.master)
        runtime_raw, _ = _read_optional(self.paths.runtime)
        if not isinstance(runtime_raw, Mapping):
            runtime_raw = {}
        # Portable progress is UUID-keyed.  Integrity acceptance, incident
        # paths and import markers belong to this installation and must be
        # regenerated after import instead of leaking across devices.
        runtime = _portable_runtime(runtime_raw)
        bundle: dict[str, Any] = {
            "type": BUNDLE_TYPE, "bundle_version": BUNDLE_VERSION,
            "manifest": {}, "master_config": copy.deepcopy(master_raw),
            "runtime_data": runtime, "preferences": self._preferences(),
            "extensions": copy.deepcopy(dict(extensions or {})),
        }
        # Sanitize before hashing so the manifest authenticates exactly what
        # leaves this process.  Phone aliases intentionally survive this pass.
        bundle = _redact_sensitive(bundle)
        partitions = {name: _digest(bundle[name]) for name in _PARTITION_NAMES}
        bundle["manifest"] = {"program_version": self.integrity.program_version,
                               "exported_at": datetime.now(timezone.utc).isoformat(),
                               "config_id": master_raw.get("config_id"), "partitions": partitions,
                               "capabilities": ["uuid_runtime", "sequence_migration", "transactional_replace"]}
        if destination is not None:
            ci._atomic_write_json_unchecked(Path(destination), bundle)
        return copy.deepcopy(bundle)

    def _upgrade(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        raw_type = raw.get("type")
        version = raw.get("bundle_version", raw.get("version", 1))
        try:
            version_number = int(version)
        except (TypeError, ValueError) as exc:
            raise ConfigBundleError(f"配置包版本无效：{version!r}") from exc
        if raw_type == BUNDLE_TYPE:
            if version_number not in (2, 3):
                raise ConfigBundleError(f"不支持的配置包版本：{version!r}")
            return copy.deepcopy(dict(raw))
        if raw_type != "okww_account_config" or version_number != 1:
            raise BundleImportBlocked(f"unsupported account bundle type/version: {raw_type!r} v{version!r}")
        legacy_seed = _digest(raw)
        profiles = raw.get("profiles", {})
        runtime = _portable_runtime(raw.get("runtime_data", raw.get("runtime", {})))
        # v1 exports commonly held a valid schema-v1 master under `master`.
        master = raw.get("master_config", raw.get("master"))
        if not isinstance(master, Mapping):
            master = {"schema_version": 1, "config_id": str(raw.get("config_id") or f"legacy-bundle-{legacy_seed[:24]}"),
                      "timezone": str(raw.get("timezone") or "Asia/Shanghai"),
                      "profiles": copy.deepcopy(profiles), "sequences": copy.deepcopy(raw.get("sequences", {})),
                      "extensions": copy.deepcopy(raw.get("extensions", {}))}
        # v1 commonly used display-name keys and flat task fields.  Reuse the
        # exact first-anchor converter so upgrades produce stable UUID schema
        # instead of handing invalid data to validate_master.
        if ci.validate_master(master):
            legacy_profiles = master.get("profiles") if isinstance(master, Mapping) else profiles
            if isinstance(legacy_profiles, Mapping):
                prepared_profiles = copy.deepcopy(dict(legacy_profiles))
                for legacy_key, legacy_profile in prepared_profiles.items():
                    if not isinstance(legacy_profile, dict) or "profile_id" in legacy_profile:
                        continue
                    key_text = str(legacy_key)
                    legacy_profile["profile_id"] = (
                        key_text if ci._UUID_RE.match(key_text) else
                        str(uuid.uuid5(uuid.NAMESPACE_URL,
                                      f"okww-account-bundle-v1:{legacy_seed}:{key_text}"))
                    )
                legacy_working = {"profiles": prepared_profiles,
                                  "sequences": copy.deepcopy(master.get("sequences", raw.get("sequences", {}))) }
                try:
                    master, updated_working = self.integrity._bootstrap_master_candidate(legacy_working)
                    updated_profiles = updated_working.get("profiles", updated_working)
                    for legacy_key, legacy_profile in legacy_profiles.items():
                        updated_profile = updated_profiles.get(legacy_key, {}) if isinstance(updated_profiles, Mapping) else {}
                        profile_id = updated_profile.get("profile_id") if isinstance(updated_profile, Mapping) else None
                        if isinstance(profile_id, str) and isinstance(legacy_profile, Mapping):
                            _merge_legacy_completions(runtime, profile_id, legacy_profile.get("last_completed"))
                except (ValueError, ci.ConfigIntegrityError):
                    # Let preflight report the original structural errors when
                    # a v1 file is too malformed even for legacy conversion.
                    pass
        elif isinstance(master, Mapping):
            # Some v1 files already contain a valid UUID master but still
            # embed mutable completion timestamps inside profiles.  Strip
            # those records from the protected partition and migrate them.
            master = copy.deepcopy(dict(master))
            master_profiles = master.get("profiles", {})
            if isinstance(master_profiles, dict):
                for profile_id, profile in master_profiles.items():
                    if isinstance(profile, dict):
                        _merge_legacy_completions(runtime, str(profile_id), profile.pop("last_completed", None))
        return {"type": BUNDLE_TYPE, "bundle_version": BUNDLE_VERSION,
                "manifest": {"upgraded_from": 1, "partitions": {}, "hashes_unavailable": True},
                "master_config": copy.deepcopy(dict(master)),
                "runtime_data": runtime,
                "preferences": copy.deepcopy(raw.get("preferences", {"active_profile": raw.get("active_profile")})),
                "extensions": copy.deepcopy(raw.get("extensions", {})) if isinstance(raw.get("extensions", {}), Mapping) else {}}

    @staticmethod
    def _diff_summary(differences: list[dict[str, Any]], account_count: int,
                      sequence_count: int, runtime_record_count: int) -> list[str]:
        fields = sorted({str(item.get("field")) for item in differences if item.get("field")})
        summary = [f"accounts: {account_count}", f"sequences: {sequence_count}",
                   f"runtime records: {runtime_record_count}"]
        if fields:
            summary.append("changed: " + ", ".join(fields[:6]))
        return summary

    def preflight_import(self, source: str | Path | Mapping[str, Any]) -> BundlePreflight:
        try:
            raw = copy.deepcopy(dict(source)) if isinstance(source, Mapping) else ci._read_json(Path(source))[0]
            if not isinstance(raw, Mapping):
                raise ConfigBundleError("配置包必须是 JSON 对象")
            bundle = self._upgrade(raw)
            errors: list[str] = []
            try:
                raw_version = int(raw.get("bundle_version", raw.get("version", 1)))
            except (TypeError, ValueError):
                raw_version = 0
            errors.extend(_validate_bundle_shapes(bundle, v3=raw.get("type") == BUNDLE_TYPE and
                                                  raw_version == 3))
            manifest = bundle.get("manifest", {})
            if not isinstance(manifest, Mapping):
                errors.append("manifest must be an object")
                manifest = {}
            native_v2 = raw.get("type") == BUNDLE_TYPE and raw_version in (2, 3)
            trust_required = False
            partitions = manifest.get("partitions", {})
            if native_v2:
                if not isinstance(manifest, Mapping):
                    errors.append("v2 manifest is required")
                    partitions = {}
                if not isinstance(partitions, Mapping) or any(
                        not isinstance(partitions.get(name), str) or
                        not re.fullmatch(r"[0-9a-fA-F]{64}", partitions.get(name, ""))
                        for name in _PARTITION_NAMES):
                    errors.append("v2 manifest must contain SHA-256 hashes for all partitions")
                else:
                    for name in _PARTITION_NAMES:
                        if partitions[name].casefold() != _digest(bundle.get(name, {})).casefold():
                            trust_required = True
            # External bundles may contain credentials even when their old
            # manifest hash is valid.  Never expose those values to callers or
            # write them back during import.
            bundle = _redact_sensitive(bundle)
            master = bundle.get("master_config")
            if not isinstance(master, Mapping):
                errors.append("master_config must be an object")
            elif not errors:
                errors.extend(ci.validate_master(master))
            runtime_raw = bundle.get("runtime_data", {})
            if not isinstance(runtime_raw, Mapping):
                errors.append("runtime_data must be an object")
                runtime_raw = {}
            runtime = _portable_runtime(runtime_raw)
            preferences = bundle.get("preferences", {})
            if not isinstance(preferences, Mapping):
                errors.append("preferences must be an object")
                preferences = {}
            preferences = {str(k): copy.deepcopy(v) for k, v in preferences.items()
                           if str(k) not in _PREFERENCE_EXCLUDED_KEYS and
                           not _TASK_SEQUENCE_RE.match(str(k))}
            differences = []
            current = self.integrity.check(record_incident=False)
            if isinstance(master, Mapping) and not errors and not ci.validate_master(master) and current.master:
                differences = ci.diff_normalized(current.master, ci.normalize_master(master))
            account_count = len(master.get("profiles", {})) if isinstance(master, Mapping) and isinstance(master.get("profiles"), Mapping) else 0
            sequence_count = len(master.get("sequences", {})) if isinstance(master, Mapping) and isinstance(master.get("sequences"), Mapping) else 0
            completed = runtime.get("completed_at", {}) if isinstance(runtime, Mapping) else {}
            runtime_record_count = sum(len(records) for records in completed.values() if isinstance(records, Mapping)) if isinstance(completed, Mapping) else 0
            diff_summary = self._diff_summary(differences, account_count, sequence_count, runtime_record_count)
            ok = not errors and not trust_required
            return BundlePreflight(ok=ok, trust_required=trust_required, errors=errors,
                                   differences=differences, candidate_master=copy.deepcopy(dict(master)) if isinstance(master, Mapping) else None,
                                   candidate_runtime=copy.deepcopy(dict(runtime)), candidate_preferences=copy.deepcopy(dict(preferences)),
                                   bundle=copy.deepcopy(dict(bundle)), account_count=account_count,
                                   sequence_count=sequence_count, runtime_record_count=runtime_record_count,
                                   diff_summary=diff_summary)
        except (OSError, ValueError, RuntimeError, TypeError, KeyError, AttributeError,
                json.JSONDecodeError) as exc:
            message = str(exc)
            if isinstance(exc, (ConfigBundleError, TypeError, KeyError, AttributeError)):
                message = f"配置包预检失败：{message}"
            return BundlePreflight(False, errors=[message])

    def import_bundle(self, source: str | Path | Mapping[str, Any], *, confirm: bool = False,
                      trust_external: bool = False) -> BundlePreflight:
        preflight = self.preflight_import(source)
        if not confirm:
            raise BundleImportBlocked("explicit confirmation is required to import an account bundle")
        if preflight.trust_required and not trust_external:
            raise BundleImportBlocked("bundle changed after export; explicitly trust the external modification")
        if not preflight.candidate_master or preflight.errors:
            raise ConfigBundleError("配置包预检失败：" + "; ".join(preflight.errors))
        master = preflight.candidate_master
        runtime = preflight.candidate_runtime or {}
        task_path = self.paths.multi_account_task or self.paths.config_dir / "MultiAccountDailyTask.json"
        try:
            existing_working, _ = _read_optional(self.paths.working)
        except (OSError, ValueError, ci.ConfigIntegrityError):
            existing_working = {}
        if not isinstance(existing_working, Mapping):
            existing_working = {}
        try:
            working = self.integrity._rebuild_working(master, existing_working)
        except (ValueError, TypeError, ci.ConfigIntegrityError):
            # A corrupt legacy projection cannot prevent full replacement;
            # rebuild a clean compatibility projection from the candidate.
            working = self.integrity._rebuild_working(master, {})
        try:
            existing_preferences, _ = _read_optional(task_path)
        except (OSError, ValueError, ci.ConfigIntegrityError):
            existing_preferences = {}
        if not isinstance(existing_preferences, Mapping):
            existing_preferences = {}
        before: dict[Path, bytes | None] = {}
        paths = [self.paths.master, self.paths.working, self.paths.runtime]
        paths.append(task_path)
        with self.integrity._lock:
            for path in paths:
                before[path] = path.read_bytes() if path.exists() else None
            self._write_transaction_snapshot(before)
            try:
                ci._atomic_write_json_unchecked(self.paths.master, master)
                ci.atomic_write_json(self.paths.working, working)
                runtime = self._restore_runtime(runtime, set(master.get("profiles", {})))
                runtime["accepted_master_fingerprint"] = ci.fingerprint(ci.normalize_master(master))
                runtime["last_bundle_import"] = datetime.now(timezone.utc).isoformat()
                ci.atomic_write_json(self.paths.runtime, runtime)
                # Preserve legacy/non-exported task keys and only overlay the
                # explicitly exported preference namespace.
                preferences = {**copy.deepcopy(dict(existing_preferences)),
                               **copy.deepcopy(preflight.candidate_preferences or {})}
                if preferences:
                    ci.atomic_write_json(task_path, preferences)
                checked = self.integrity.check(record_incident=False, resolve_incidents=False)
                if not checked.ok:
                    raise BundleImportBlocked("bundle import failed post-write integrity check")
                return BundlePreflight(True, candidate_master=copy.deepcopy(master), candidate_runtime=runtime,
                                       candidate_preferences=preferences, bundle=preflight.bundle,
                                       differences=preflight.differences, account_count=preflight.account_count,
                                       sequence_count=preflight.sequence_count,
                                       runtime_record_count=preflight.runtime_record_count,
                                       diff_summary=preflight.diff_summary)
            except Exception:
                rollback_errors = []
                for path, payload in before.items():
                    try:
                        if payload is None:
                            path.unlink(missing_ok=True)
                        elif path == self.paths.master:
                            _atomic_replace_unchecked(path, payload)
                        else:
                            ci._atomic_replace_bytes(path, payload)
                    except Exception as rollback_error:
                        rollback_errors.append(f"{path}: {rollback_error}")
                for path, payload in before.items():
                    current = path.read_bytes() if path.exists() else None
                    if current != payload:
                        rollback_errors.append(f"{path}: rollback bytes differ")
                if rollback_errors:
                    raise BundleImportBlocked("bundle import rollback failed: " + "; ".join(rollback_errors))
                raise

    def _write_transaction_snapshot(self, before: Mapping[Path, bytes | None]) -> Path:
        """Persist a verifiable pre-import snapshot before any replacement."""
        if self.transaction_snapshot_hook is not None:
            adopted = self.transaction_snapshot_hook(copy.deepcopy(dict(before)))
            # A ConfigBackupService hook may return its completed transaction
            # snapshot path.  Adopt it directly and avoid a second permanent
            # copy; returning None means the safe local fallback is needed.
            if isinstance(adopted, Mapping):
                adopted = adopted.get("path") or adopted.get("snapshot_path")
            if adopted:
                adopted_path = Path(adopted)
                if adopted_path.exists():
                    return adopted_path
        root = self.paths.root / "config_bundle_transactions"
        event = root / (datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid.uuid4().hex[:8])
        event.mkdir(parents=True, exist_ok=False)
        manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "files": {}}
        for path, payload in before.items():
            if payload is None:
                manifest["files"][str(path)] = None
                continue
            name = path.name + ".before"
            (event / name).write_bytes(payload)
            manifest["files"][str(path)] = {"name": name, "length": len(payload),
                                              "sha256": hashlib.sha256(payload).hexdigest()}
        (event / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return event

    @staticmethod
    def _restore_runtime(runtime: Mapping[str, Any], profile_ids: set[str]) -> dict[str, Any]:
        """Restore UUID-keyed records and quarantine records for absent UUIDs."""
        result = _portable_runtime(runtime)
        completed = result.get("completed_at", {})
        if not isinstance(completed, Mapping):
            completed = {}
        kept, quarantined = {}, {}
        for profile_id, records in completed.items():
            if profile_id in profile_ids:
                kept[str(profile_id)] = copy.deepcopy(records)
            else:
                quarantined[str(profile_id)] = copy.deepcopy(records)
        result["completed_at"] = kept
        if quarantined:
            existing = result.get("unrestored_records", {})
            if not isinstance(existing, Mapping):
                existing = {}
            result["unrestored_records"] = {**copy.deepcopy(dict(existing)), **quarantined}
        return result

    # Descriptive names for task/UI integrations.
    export_account_bundle = export_bundle
    preflight = preflight_import
    import_account_bundle = import_bundle


AccountConfigBundle = AccountConfigBundleService


__all__ = ["BUNDLE_TYPE", "BUNDLE_VERSION", "BundleImportBlocked", "ConfigBundleError", "SequenceSourceConflict",
           "SequenceMergeResult", "extract_task_sequences", "merge_sequence_sources",
           "resolve_sequence_members", "BundlePreflight", "AccountConfigBundleService", "AccountConfigBundle"]
