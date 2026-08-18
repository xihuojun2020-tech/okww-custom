# -*- coding: utf-8 -*-
"""Read-only account master configuration and integrity enforcement.

The account master file is deliberately a *read-only input* to this module.  The
service may repair the legacy working copy and write runtime metadata, but it
never exposes a save operation for ``account_master_config.json``.  Keeping the
rules here (rather than duplicating them in tasks and widgets) is important:
all consumers use the same protected projection and fingerprint.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional


SCHEMA_VERSION = 1
MASTER_FILENAME = "account_master_config.json"
WORKING_FILENAME = "daily_profiles.json"
RUNTIME_FILENAME = "account_runtime_state.json"
INCIDENT_DIRNAME = "config_integrity_incidents"

# One canonical definition used by validation, comparison, recovery and UI.
# ``task_config`` is a namespace containing DailyTask.PROFILE_KEYS; unknown
# names are retained in the projection so an upgrade cannot silently discard a
# user setting.
PROTECTED_PROFILE_FIELDS = (
    "profile_id",
    "display_name",
    "account_aliases",
    "task_config",
    "schedule",
    "sequence_ids",
    "extensions",
)

PROTECTED_TASK_KEYS = (
    "Which to Farm",
    "Which Tacet Suppression to Farm",
    "Which Forgery Challenge to Farm",
    "Material Selection",
    "Farm Nightmare Nest for Daily Echo",
    "Nightmare Which to Farm",
    "Tacet Discord Nests to Farm",
    "Auto Farm all Nightmare Nest",
    "Weekly Garden Check Day",
    "Merge Echo on Sunday",
    "备用识别名称",
    "备用识别名称内容",
)
_TASK_KEY_TYPES = {
    "Which to Farm": str,
    "Which Tacet Suppression to Farm": int,
    "Which Forgery Challenge to Farm": int,
    "Material Selection": str,
    "Farm Nightmare Nest for Daily Echo": bool,
    "Nightmare Which to Farm": list,
    "Tacet Discord Nests to Farm": list,
    "Auto Farm all Nightmare Nest": bool,
    "Weekly Garden Check Day": str,
    "Merge Echo on Sunday": bool,
    "备用识别名称": str,
    "备用识别名称内容": str,
}

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_SHORT_PROFILE_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]\d+)(?=$|[\s:：_\-.】])")
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")

_DEFAULT_SERVICE: "ConfigIntegrityService | None" = None


class ConfigIntegrityError(ValueError):
    """Raised when a master or working configuration is malformed."""


class ConfigWriteBlocked(PermissionError):
    """Raised when code attempts to write the read-only master file."""


class ConfigIntegrityBlocked(RuntimeError):
    """Raised by the task-start guard while the configuration is not trusted."""


@dataclass(frozen=True)
class ConfigPaths:
    """Filesystem locations used by the integrity service.

    ``root`` can be a repository/working root or an explicit ``configs``
    directory.  This makes tests isolated while preserving the application's
    normal ``<working>/configs`` layout.
    """

    root: Path
    config_dir: Path
    master: Path
    working: Path
    runtime: Path
    incidents: Path

    @classmethod
    def from_root(cls, root: os.PathLike | str | None = None) -> "ConfigPaths":
        base = Path(root or os.getcwd()).resolve()
        config_dir = base if base.name.casefold() == "configs" else base / "configs"
        return cls(
            root=base,
            config_dir=config_dir,
            master=config_dir / MASTER_FILENAME,
            working=config_dir / WORKING_FILENAME,
            runtime=config_dir / RUNTIME_FILENAME,
            incidents=(base / INCIDENT_DIRNAME) if config_dir != base else (base.parent / INCIDENT_DIRNAME),
        )


def _canonical(value: Any) -> Any:
    """Return JSON-compatible data with deterministic ordering."""
    if isinstance(value, Mapping):
        return {str(k): _canonical(value[k]) for k in sorted(value, key=lambda x: str(x))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def canonical_json(value: Any) -> str:
    return json.dumps(_canonical(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _alias_key(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _sorted_aliases(values: Iterable[Any]) -> list[str]:
    cleaned = {" ".join(str(value).split()) for value in values if _alias_key(value)}
    return sorted(cleaned, key=lambda value: (value.casefold(), value))


def _identity_candidates(value: Any) -> set[str]:
    """Return conservative identity keys for legacy profile migration.

    Short names are tokenized exactly (A1 never matches A10), complete phone
    numbers also produce the canonical masked form, and arbitrary aliases
    (including U-prefixed login names) remain exact normalized strings.
    """
    if value is None:
        return set()
    text = " ".join(str(value).split()).strip()
    if not text:
        return set()
    candidates = {_alias_key(text)}
    for match in _SHORT_PROFILE_RE.finditer(text):
        candidates.add(match.group(1).casefold())
    for phone in _PHONE_RE.findall(text):
        candidates.add(_alias_key(phone[:3] + "****" + phone[-4:]))
    return {candidate for candidate in candidates if candidate}


def _split_identity_values(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        values = list(value)
    elif value:
        values = re.split(r"[,，;；\r\n]+", str(value))
    else:
        values = []
    return [str(item).strip() for item in values if str(item).strip()]


def _profile_identity_values(profile_id: str, profile: Mapping[str, Any]) -> list[str]:
    values: list[str] = [str(profile.get("display_name", "")), str(profile_id)]
    values.extend(_split_identity_values(profile.get("account_aliases")))
    task_config = profile.get("task_config")
    if isinstance(task_config, Mapping):
        for key in ("备用识别名称内容", "Account Name", "account_name", "账号名称"):
            values.extend(_split_identity_values(task_config.get(key)))
    return values


def _master_identity_index(master: Mapping[str, Any]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for profile_id, profile in master.get("profiles", {}).items():
        if not isinstance(profile, Mapping):
            continue
        for value in _profile_identity_values(str(profile_id), profile):
            for candidate in _identity_candidates(value):
                index.setdefault(candidate, set()).add(str(profile_id))
    return index


def _resolve_working_profile_id(key: Any, profile: Mapping[str, Any],
                                master: Mapping[str, Any], index: Mapping[str, set[str]]) -> str | None:
    direct = profile.get("profile_id")
    master_profiles = master.get("profiles", {})
    direct_id = direct if isinstance(direct, str) and direct in master_profiles else None
    values: list[str] = [str(key), str(profile.get("display_name", ""))]
    values.extend(_split_identity_values(profile.get("account_aliases")))
    task_config = profile.get("task_config")
    sources = [profile]
    if isinstance(task_config, Mapping):
        sources.append(task_config)
    for source in sources:
        for name in ("备用识别名称内容", "Account Name", "account_name", "账号名称"):
            values.extend(_split_identity_values(source.get(name)))
    matches: set[str] = set()
    for value in values:
        for candidate in _identity_candidates(value):
            matches.update(index.get(candidate, set()))
    if len(matches) > 1:
        raise ConfigIntegrityError(
            f"working profile {key!r} ambiguously matches profile_ids: {', '.join(sorted(matches))}"
        )
    if direct_id and matches and matches != {direct_id}:
        raise ConfigIntegrityError(
            f"working profile {key!r} profile_id conflicts with identity candidates"
        )
    if direct_id:
        return direct_id
    return next(iter(matches), None)


def _read_json(path: Path) -> tuple[Any, bytes]:
    raw = path.read_bytes()
    try:
        return json.loads(raw.decode("utf-8-sig")), raw
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigIntegrityError(f"{path.name}: invalid JSON: {exc}") from exc


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_master(data: Any) -> list[str]:
    """Validate schema v1 and return all errors (without changing ``data``)."""
    errors: list[str] = []
    if not isinstance(data, Mapping):
        return ["master must be a JSON object"]
    _require(data.get("schema_version") == SCHEMA_VERSION,
             f"schema_version must be {SCHEMA_VERSION}", errors)
    _require(isinstance(data.get("config_id"), str) and bool(data.get("config_id").strip()),
             "config_id must be a non-empty string", errors)
    _require(isinstance(data.get("timezone"), str) and bool(data.get("timezone").strip()),
             "timezone must be a non-empty string", errors)
    profiles = data.get("profiles")
    _require(isinstance(profiles, Mapping), "profiles must be an object", errors)
    if not isinstance(profiles, Mapping):
        return errors
    # Validate the same derived identity candidates used by legacy working-copy
    # migration.  Exact aliases alone miss collisions such as a full phone in
    # one profile versus its masked form in another, or alternate U names in
    # task_config.  Short-name candidates are tokenized by _identity_candidates,
    # so A1 and A10 remain distinct.
    identity_owner: dict[str, str] = {}
    for profile_id, profile in profiles.items():
        path = f"profiles[{profile_id!r}]"
        _require(isinstance(profile_id, str) and bool(_UUID_RE.match(profile_id)),
                 f"{path}: profile_id must be a UUID", errors)
        if not isinstance(profile, Mapping):
            errors.append(f"{path} must be an object")
            continue
        _require(profile.get("display_name") is not None and isinstance(profile.get("display_name"), str)
                 and bool(profile.get("display_name").strip()), f"{path}.display_name must be a non-empty string", errors)
        aliases = profile.get("account_aliases", [])
        _require(isinstance(aliases, list) and all(isinstance(v, str) and v.strip() for v in aliases),
                 f"{path}.account_aliases must be a list of non-empty strings", errors)
        task_config = profile.get("task_config", {})
        _require(isinstance(task_config, Mapping), f"{path}.task_config must be an object", errors)
        if isinstance(profile, Mapping):
            for identity in _profile_identity_values(str(profile_id), profile):
                for candidate in _identity_candidates(identity):
                    previous = identity_owner.get(candidate)
                    if previous and previous != profile_id:
                        errors.append(
                            f"identity candidate {candidate!r} is ambiguous between "
                            f"{previous} and {profile_id}"
                        )
                    else:
                        identity_owner[candidate] = str(profile_id)
        if isinstance(task_config, Mapping):
            missing_keys = [key for key in PROTECTED_TASK_KEYS if key not in task_config]
            if missing_keys:
                errors.append(f"{path}.task_config missing protected keys: {', '.join(missing_keys)}")
            for key, expected in _TASK_KEY_TYPES.items():
                if key in task_config and not (type(task_config[key]) is expected or
                                               (expected not in (bool, int) and isinstance(task_config[key], expected))):
                    errors.append(f"{path}.task_config[{key!r}] must be {expected.__name__}")
        schedule = profile.get("schedule", {})
        _require(isinstance(schedule, Mapping), f"{path}.schedule must be an object", errors)
        if isinstance(schedule, Mapping):
            mode = schedule.get("mode", "")
            _require(mode in ("", "disabled", "daily", "weekly", "once"),
                     f"{path}.schedule.mode is invalid", errors)
            if "local_time" in schedule:
                value = schedule["local_time"]
                _require(isinstance(value, str) and bool(re.match(r"^([01]\d|2[0-3]):[0-5]\d$", value)),
                         f"{path}.schedule.local_time must be HH:MM", errors)
            weekdays = schedule.get("weekdays", [])
            _require(isinstance(weekdays, list) and all(isinstance(day, (str, int)) for day in weekdays),
                     f"{path}.schedule.weekdays must be a list", errors)
            _require(isinstance(schedule.get("extensions", {}), Mapping),
                     f"{path}.schedule.extensions must be an object", errors)
        _require(isinstance(profile.get("extensions", {}), Mapping), f"{path}.extensions must be an object", errors)
    sequences = data.get("sequences")
    _require(isinstance(sequences, Mapping), "sequences must be an object", errors)
    if isinstance(sequences, Mapping):
        profile_ids = set(profiles)
        for name, members in sequences.items():
            _require(isinstance(name, str) and bool(name.strip()), "sequence names must be non-empty strings", errors)
            _require(isinstance(members, list), f"sequences[{name!r}] must be a list", errors)
            if isinstance(members, list):
                seen: set[str] = set()
                for member in members:
                    _require(isinstance(member, str) and member in profile_ids,
                             f"sequences[{name!r}] references unknown profile_id {member!r}", errors)
                    if member in seen:
                        errors.append(f"sequences[{name!r}] contains duplicate profile_id {member!r}")
                    seen.add(member)
    _require(isinstance(data.get("extensions", {}), Mapping), "extensions must be an object", errors)
    return errors


def validate_working(data: Any) -> list[str]:
    """Validate the legacy working copy without imposing master-only fields."""
    if not isinstance(data, Mapping):
        return ["working profiles must be a JSON object"]
    profiles = data.get("profiles", data)
    if not isinstance(profiles, Mapping):
        return ["working profiles must be an object"]
    errors: list[str] = []
    for name, profile in profiles.items():
        if name in ("sequences", "active_profile", "schema_version"):
            continue
        if not isinstance(profile, Mapping):
            errors.append(f"working profile {name!r} must be an object")
    return errors


def normalize_master(data: Mapping[str, Any]) -> dict[str, Any]:
    """Project protected master fields into a stable, comparable structure."""
    errors = validate_master(data)
    if errors:
        raise ConfigIntegrityError("; ".join(errors))
    memberships: dict[str, list[str]] = {profile_id: [] for profile_id in data["profiles"]}
    for sequence, members in data.get("sequences", {}).items():
        for profile_id in members:
            memberships.setdefault(profile_id, []).append(str(sequence))
    profiles: dict[str, Any] = {}
    for profile_id, profile in data["profiles"].items():
        profiles[profile_id] = {
            "profile_id": profile_id,
            "display_name": str(profile["display_name"]).strip(),
            "account_aliases": _sorted_aliases(profile.get("account_aliases", [])),
            "task_config": _canonical(profile.get("task_config", {})),
            "schedule": _canonical(profile.get("schedule", {})),
            "sequence_ids": sorted(memberships.get(profile_id, [])),
            "extensions": _canonical(profile.get("extensions", {})),
        }
    return {"config_id": data["config_id"], "timezone": data["timezone"], "profiles": profiles,
            "sequences": {str(k): list(v) for k, v in sorted(data.get("sequences", {}).items())},
            "extensions": _canonical(data.get("extensions", {}))}


def _working_profiles(data: Mapping[str, Any]) -> Mapping[str, Any]:
    profiles = data.get("profiles", data)
    return profiles if isinstance(profiles, Mapping) else {}


def normalize_working(data: Mapping[str, Any], master: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Project the old name-keyed profile file into the master projection.

    Newer working copies may carry ``profile_id``.  Older copies are matched by
    display name and aliases, allowing a read-only upgrade without rewriting
    them merely to compute a fingerprint.
    """
    errors = validate_working(data)
    if errors:
        raise ConfigIntegrityError("; ".join(errors))
    master_norm = normalize_master(master) if master is not None else None
    master_profiles = (master_norm or {}).get("profiles", {})
    identity_index = _master_identity_index(master) if master is not None else {}
    output: dict[str, Any] = {}
    for key, profile in _working_profiles(data).items():
        if key in ("sequences", "active_profile", "schema_version") or not isinstance(profile, Mapping):
            continue
        profile_id = _resolve_working_profile_id(key, profile, master, identity_index) if master is not None else None
        profile_id = profile_id or f"working:{key}"
        task_config = profile.get("task_config")
        if not isinstance(task_config, Mapping):
            # Legacy files store PROFILE_KEYS at profile top level.
            task_config = {str(k): _canonical(v) for k, v in profile.items()
                           if k not in {"profile_id", "display_name", "account_aliases", "schedule", "extensions",
                                        "last_completed"}}
        aliases = profile.get("account_aliases") or []
        output[profile_id] = {
            "profile_id": profile_id,
            "display_name": str(profile.get("display_name", key)).strip(),
            "account_aliases": _sorted_aliases(aliases),
            "task_config": _canonical(task_config),
            "schedule": _canonical(profile.get("schedule", {})),
            "sequence_ids": [],
            "extensions": _canonical(profile.get("extensions", {})),
        }
    # Legacy sequences are keyed by display name/alias; map those names to IDs.
    sequences: dict[str, list[str]] = {}
    raw_sequences = data.get("sequences", {})
    if isinstance(raw_sequences, Mapping):
        for seq, members in raw_sequences.items():
            ids = []
            for member in members if isinstance(members, list) else []:
                normalized = _alias_key(member)
                matches = identity_index.get(normalized, set())
                if len(matches) > 1:
                    raise ConfigIntegrityError(
                        f"working sequence {seq!r} member {member!r} ambiguously matches profile_ids: "
                        f"{', '.join(sorted(matches))}"
                    )
                pid = next(iter(matches), None)
                if pid in output:
                    ids.append(pid)
                elif member in output:
                    ids.append(member)
            sequences[str(seq)] = ids
            for pid in ids:
                if pid in output and str(seq) not in output[pid]["sequence_ids"]:
                    output[pid]["sequence_ids"].append(str(seq))
    return {"profiles": output, "sequences": sequences,
            "extensions": _canonical(data.get("extensions", {}))}


def diff_normalized(master: Mapping[str, Any], working: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return structured differences at profile/field granularity."""
    differences: list[dict[str, Any]] = []
    mp, wp = master.get("profiles", {}), working.get("profiles", {})
    for pid in sorted(set(mp) | set(wp)):
        if pid not in mp:
            differences.append({"profile_id": pid, "field": "profile", "kind": "removed_from_master", "master": None, "working": wp[pid]})
            continue
        if pid not in wp:
            differences.append({"profile_id": pid, "field": "profile", "kind": "missing_from_working", "master": mp[pid], "working": None})
            continue
        for field_name in PROTECTED_PROFILE_FIELDS[1:]:
            if _canonical(mp[pid].get(field_name)) != _canonical(wp[pid].get(field_name)):
                differences.append({"profile_id": pid, "field": field_name, "kind": "changed",
                                    "master": mp[pid].get(field_name), "working": wp[pid].get(field_name)})
    if _canonical(master.get("sequences", {})) != _canonical(working.get("sequences", {})):
        differences.append({"profile_id": None, "field": "sequences", "kind": "changed",
                            "master": master.get("sequences", {}), "working": working.get("sequences", {})})
    if _canonical(master.get("extensions", {})) != _canonical(working.get("extensions", {})):
        differences.append({"profile_id": None, "field": "extensions", "kind": "changed",
                            "master": master.get("extensions", {}), "working": working.get("extensions", {})})
    return differences


def assert_master_read_only(path: os.PathLike | str) -> None:
    """Reject writes targeting an account master path."""
    if Path(path).name.casefold() == MASTER_FILENAME.casefold():
        raise ConfigWriteBlocked(f"account master configuration is read-only: {path}")


def atomic_write_json(path: os.PathLike | str, data: Any, *, indent: int = 2) -> None:
    """Write JSON through flush/fsync/replace, refusing the master path."""
    target = Path(path)
    assert_master_read_only(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=indent) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Verify the temporary file before it can become the official state.
        with open(temp_name, encoding="utf-8") as stream:
            json.load(stream)
        os.replace(temp_name, target)
        try:
            directory_fd = os.open(str(target.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _atomic_replace_bytes(path: Path, payload: bytes) -> None:
    """Atomically replace a file from a previously backed-up byte snapshot."""
    assert_master_read_only(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".rollback", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


@dataclass
class IntegrityResult:
    ok: bool
    master_valid: bool
    working_valid: bool
    master_changed: bool = False
    errors: list[str] = field(default_factory=list)
    differences: list[dict[str, Any]] = field(default_factory=list)
    master_fingerprint: str = ""
    working_fingerprint: str = ""
    accepted_fingerprint: str = ""
    event_dir: Optional[Path] = None
    master: Optional[dict[str, Any]] = None
    working: Optional[dict[str, Any]] = None

    @property
    def needs_review(self) -> bool:
        return not self.ok

    @property
    def snapshot(self) -> Optional[dict[str, Any]]:
        return copy.deepcopy(self.master) if self.ok and self.master else None


class ConfigIntegrityService:
    """Read/compare/restore service and the shared task-start guard."""

    def __init__(self, root: os.PathLike | str | None = None, *, paths: ConfigPaths | None = None,
                 program_version: str = "development"):
        self.paths = paths or ConfigPaths.from_root(root)
        self.program_version = str(program_version or "development")
        self._lock = threading.RLock()
        self._last_result: IntegrityResult | None = None
        self._snapshot: dict[str, Any] | None = None
        self._runtime_error: str | None = None

    @property
    def master_path(self) -> Path:
        return self.paths.master

    @property
    def working_path(self) -> Path:
        return self.paths.working

    @property
    def runtime_path(self) -> Path:
        return self.paths.runtime

    @property
    def incidents_path(self) -> Path:
        return self.paths.incidents

    @property
    def last_result(self) -> IntegrityResult | None:
        return self._last_result

    # Descriptive aliases keep call sites readable and make the service easy to
    # embed in command-line validators without exposing implementation details.
    validate = lambda self, **kwargs: self.check(**kwargs)
    verify = lambda self, **kwargs: self.check(**kwargs)
    check_integrity = lambda self, **kwargs: self.check(**kwargs)

    @property
    def is_safe(self) -> bool:
        return bool(self._last_result and self._last_result.ok)

    def _runtime(self) -> dict[str, Any]:
        self._runtime_error = None
        if not self.paths.runtime.is_file():
            return {}
        try:
            value, _ = _read_json(self.paths.runtime)
            if not isinstance(value, dict):
                raise ConfigIntegrityError('runtime state must be a JSON object')
            return value
        except (ConfigIntegrityError, OSError) as exc:
            self._runtime_error = str(exc)
            return {}

    def check(self, *, record_incident: bool = True, resolve_incidents: bool = True) -> IntegrityResult:
        with self._lock:
            errors: list[str] = []
            master_data = working_data = None
            master_norm = working_norm = None
            master_valid = working_valid = False
            if not self.paths.master.is_file():
                errors.append(f"missing master configuration: {self.paths.master}")
            else:
                try:
                    master_data, _ = _read_json(self.paths.master)
                    master_errors = validate_master(master_data)
                    errors.extend(master_errors)
                    if not master_errors:
                        master_norm = normalize_master(master_data)
                        master_valid = True
                except (ConfigIntegrityError, OSError) as exc:
                    errors.append(str(exc))
            if not self.paths.working.is_file():
                errors.append(f"missing working configuration: {self.paths.working}")
            else:
                try:
                    working_data, _ = _read_json(self.paths.working)
                    working_errors = validate_working(working_data)
                    errors.extend(working_errors)
                    working_valid = not working_errors
                    if working_valid and master_valid:
                        working_norm = normalize_working(working_data, master_data)
                except (ConfigIntegrityError, OSError) as exc:
                    errors.append(str(exc))
            master_fp = fingerprint(master_norm) if master_norm is not None else ""
            working_fp = fingerprint(working_norm) if working_norm is not None else ""
            runtime = self._runtime()
            if self._runtime_error:
                errors.append(f"runtime state invalid: {self._runtime_error}")
            accepted = str(runtime.get("accepted_master_fingerprint") or runtime.get("last_accepted_fingerprint") or "")
            master_changed = bool(master_fp and master_fp != accepted)
            differences = diff_normalized(master_norm, working_norm) if master_norm is not None and working_norm is not None else []
            ok = master_valid and working_valid and not errors and not differences and not master_changed
            result = IntegrityResult(ok=ok, master_valid=master_valid, working_valid=working_valid,
                                     master_changed=master_changed, errors=errors, differences=differences,
                                     master_fingerprint=master_fp, working_fingerprint=working_fp,
                                     accepted_fingerprint=accepted,
                                     master=master_norm, working=working_norm)
            if record_incident and (errors or differences or master_changed):
                result.event_dir = self.record_incident(result, master_data, working_data)
                if self._runtime_error and self.paths.runtime.exists():
                    try:
                        (result.event_dir / "runtime.snapshot.json").write_bytes(self.paths.runtime.read_bytes())
                    except OSError:
                        pass
            self._last_result = result
            if ok:
                self._snapshot = copy.deepcopy(master_norm)
                if resolve_incidents:
                    self._resolve_matching_incidents(master_fp, working_fp)
            return result

    def require_safe(self) -> dict[str, Any]:
        result = self.check()
        if not result.ok:
            raise ConfigIntegrityBlocked(self.describe(result))
        return copy.deepcopy(self._snapshot or result.master or {})

    def guard_task_start(self, *_args, **_kwargs) -> bool:
        """Shared pre-flight hook; must run before device/window operations."""
        self.require_safe()
        return True

    def accept_master_change(self, *, result: IntegrityResult | None = None) -> IntegrityResult:
        """Record explicit user acknowledgement of a valid new master fingerprint."""
        result = result or self._last_result or self.check()
        if not result.master_valid or not result.master_fingerprint:
            raise ConfigIntegrityBlocked("cannot accept an invalid or missing master configuration")
        with self._lock:
            runtime = self._runtime()
            if self._runtime_error:
                raise ConfigIntegrityBlocked(
                    "runtime state is corrupt; explicitly rebuild runtime state before accepting master changes"
                )
            runtime["accepted_master_fingerprint"] = result.master_fingerprint
            runtime["last_integrity_event"] = str(result.event_dir) if result.event_dir else None
            atomic_write_json(self.paths.runtime, runtime)
        return self.check()

    confirm_master_change = accept_master_change

    def apply_master_to_working(self, *, result: IntegrityResult | None = None) -> IntegrityResult:
        """Accept the current master and replace protected working data in one flow.

        The check is deliberately fresh and runs under the service lock so an
        external edit between opening the dialog and pressing the primary
        action cannot be silently applied.  Working bytes and runtime bytes
        are backed up before either file is changed; a failed post-check rolls
        both files back and verifies the original bytes.
        """
        with self._lock:
            fresh = self.check()
            if not fresh.master_valid or not fresh.master:
                raise ConfigIntegrityBlocked(
                    f"cannot apply an invalid or missing master configuration: {self.paths.master}"
                )
            self._runtime()
            if self._runtime_error:
                raise ConfigIntegrityBlocked(
                    "runtime state is corrupt; explicitly rebuild runtime state before applying master configuration"
                )

            working_before = self.paths.working.read_bytes() if self.paths.working.exists() else None
            runtime_before = self.paths.runtime.read_bytes() if self.paths.runtime.exists() else None
            needs_working_rebuild = (not fresh.working_valid) or bool(fresh.differences)
            event_dir = fresh.event_dir

            try:
                if needs_working_rebuild:
                    self.paths.incidents.mkdir(parents=True, exist_ok=True)
                    event_dir = event_dir or self.record_incident(fresh, None, None)
                    before = event_dir / "before_restore"
                    before.mkdir(parents=True, exist_ok=True)
                    if working_before is not None:
                        shutil.copy2(self.paths.working, before / self.paths.working.name)
                    try:
                        working_data, _ = _read_json(self.paths.working)
                    except (ConfigIntegrityError, OSError):
                        working_data = {}
                    master_raw, _ = _read_json(self.paths.master)
                    rebuilt = self._rebuild_working(master_raw, working_data)
                    atomic_write_json(self.paths.working, rebuilt)

                runtime = self._runtime()
                if self._runtime_error:
                    raise ConfigIntegrityBlocked("runtime state is corrupt")
                runtime["accepted_master_fingerprint"] = fresh.master_fingerprint
                runtime["last_integrity_event"] = str(event_dir) if event_dir else None
                atomic_write_json(self.paths.runtime, runtime)

                checked = self.check(record_incident=False, resolve_incidents=False)
                if not checked.ok:
                    raise ConfigIntegrityBlocked("account configuration is still inconsistent after applying master")
                if event_dir:
                    self._resolve_incident(
                        event_dir,
                        "RESOLVED_BY_MASTER_RESTORE" if needs_working_rebuild else "RESOLVED_BY_MASTER_APPLY",
                    )
                return checked
            except Exception:
                if working_before is not None:
                    _atomic_replace_bytes(self.paths.working, working_before)
                    if self.paths.working.read_bytes() != working_before:
                        raise ConfigIntegrityBlocked("working copy rollback verification failed")
                elif self.paths.working.exists() and needs_working_rebuild:
                    self.paths.working.unlink()
                if runtime_before is not None:
                    _atomic_replace_bytes(self.paths.runtime, runtime_before)
                    if self.paths.runtime.read_bytes() != runtime_before:
                        raise ConfigIntegrityBlocked("runtime rollback verification failed")
                elif self.paths.runtime.exists():
                    self.paths.runtime.unlink()
                raise

    # Descriptive aliases for callers that phrase the action as a user intent.
    use_master_for_all_accounts = apply_master_to_working
    apply_master = apply_master_to_working

    def rebuild_runtime_state(self, *, confirm: bool = False) -> IntegrityResult:
        """Explicitly replace corrupt runtime metadata with empty state."""
        if not confirm:
            raise ConfigIntegrityBlocked('explicit confirmation is required to rebuild runtime state')
        with self._lock:
            if self.paths.runtime.is_file():
                backup = self.paths.runtime.with_name(
                    f"{self.paths.runtime.name}.before_rebuild_{datetime.now():%Y%m%d_%H%M%S_%f}"
                )
                shutil.copy2(self.paths.runtime, backup)
            atomic_write_json(self.paths.runtime, {"completed_at": {}, "progress": {},
                                                    "runtime_rebuilt_with_warning": True})
        return self.check()

    def restore_working_from_master(self, *, result: IntegrityResult | None = None) -> IntegrityResult:
        """Repair protected fields in the working copy, preserving non-protected data."""
        result = result or self._last_result or self.check(record_incident=False)
        if not result.master_valid or not result.master:
            raise ConfigIntegrityBlocked("cannot restore from an invalid master configuration")
        with self._lock:
            self._runtime()
            if self._runtime_error:
                raise ConfigIntegrityBlocked(
                    "runtime state is corrupt; explicitly rebuild runtime state before restoring working config"
                )
            self.paths.incidents.mkdir(parents=True, exist_ok=True)
            event_dir = result.event_dir or self.record_incident(result, None, None)
            before = event_dir / "before_restore"
            before.mkdir(parents=True, exist_ok=True)
            before_bytes = None
            if self.paths.working.exists():
                before_bytes = self.paths.working.read_bytes()
                shutil.copy2(self.paths.working, before / self.paths.working.name)
                try:
                    working_data, _ = _read_json(self.paths.working)
                except ConfigIntegrityError:
                    # A corrupt legacy copy is replaced with a master-derived
                    # projection only after the original bytes were backed up.
                    working_data = {}
            else:
                working_data = {"profiles": {}}
            master_raw, _ = _read_json(self.paths.master)
            rebuilt = self._rebuild_working(master_raw, working_data)
            try:
                atomic_write_json(self.paths.working, rebuilt)
                checked = self.check(record_incident=False, resolve_incidents=False)
                if not checked.ok:
                    raise ConfigIntegrityBlocked("working copy is still inconsistent after restore")
            except Exception:
                if before_bytes is not None:
                    _atomic_replace_bytes(self.paths.working, before_bytes)
                    # Verify rollback bytes and leave the service blocked if
                    # the original copy itself was malformed.
                    if self.paths.working.read_bytes() != before_bytes:
                        raise ConfigIntegrityBlocked("working copy rollback verification failed")
                else:
                    try:
                        self.paths.working.unlink()
                    except FileNotFoundError:
                        pass
                raise
            self._resolve_incident(event_dir, "RESOLVED_BY_MASTER_RESTORE")
            return self.check(record_incident=False, resolve_incidents=False)

    restore_working_copy = restore_working_from_master

    @staticmethod
    def _rebuild_working(master: Mapping[str, Any], working: Mapping[str, Any]) -> dict[str, Any]:
        old_profiles = _working_profiles(working)
        identity_index = _master_identity_index(master)
        old_by_id: dict[str, Mapping[str, Any]] = {}
        for old_key, old_profile in old_profiles.items():
            if not isinstance(old_profile, Mapping):
                continue
            resolved = _resolve_working_profile_id(old_key, old_profile, master, identity_index)
            if resolved:
                if resolved in old_by_id:
                    raise ConfigIntegrityError(
                        f"working profiles {old_key!r} and another entry both map to profile_id {resolved}"
                    )
                old_by_id[resolved] = old_profile
        result = {k: copy.deepcopy(v) for k, v in working.items() if k not in ("profiles", "sequences")}
        profiles: dict[str, Any] = {}
        for pid, p in master.get("profiles", {}).items():
            old = old_by_id.get(pid, {})
            # Only retain the explicitly supported historical completion
            # record.  Arbitrary per-profile keys may be stale or polluted;
            # all account configuration fields come from the validated master.
            item = {}
            if isinstance(old, Mapping) and "last_completed" in old:
                item["last_completed"] = copy.deepcopy(old["last_completed"])
            item["profile_id"] = pid
            item["display_name"] = p["display_name"]
            item["account_aliases"] = list(p.get("account_aliases", []))
            item["task_config"] = copy.deepcopy(p.get("task_config", {}))
            # Keep the legacy consumer shape in sync while removing any stale
            # protected values first.  normalize_working prefers task_config,
            # but older OK versions still read the flat keys.
            for key, value in (p.get("task_config") or {}).items():
                item[key] = copy.deepcopy(value)
            item["schedule"] = copy.deepcopy(p.get("schedule", {}))
            item["extensions"] = copy.deepcopy((master.get("profiles", {}).get(pid) or {}).get("extensions", {}))
            profiles[p["display_name"]] = item
        result["profiles"] = profiles
        result["sequences"] = {str(k): [master["profiles"][pid]["display_name"] for pid in members]
                                for k, members in master.get("sequences", {}).items()}
        result["extensions"] = copy.deepcopy(master.get("extensions", {}))
        active = working.get("active_profile")
        names = set(profiles)
        result["active_profile"] = active if active in names else (next(iter(names), ""))
        return result

    @staticmethod
    def legacy_profile_projection(master: Mapping[str, Any]) -> dict[str, Any]:
        """Expose a read-only legacy-shaped view for existing task widgets."""
        profiles: dict[str, Any] = {}
        for pid, profile in master.get("profiles", {}).items():
            item = copy.deepcopy(profile.get("task_config", {}))
            item.update({"profile_id": pid, "display_name": profile.get("display_name", pid),
                         "account_aliases": list(profile.get("account_aliases", [])),
                         "schedule": copy.deepcopy(profile.get("schedule", {}))})
            profiles[str(profile.get("display_name", pid))] = item
        sequences = {}
        for sequence, members in master.get("sequences", {}).items():
            sequences[sequence] = [str(master.get("profiles", {}).get(pid, {}).get("display_name", pid)) for pid in members]
        return {"profiles": profiles, "sequences": sequences}

    def record_incident(self, result: IntegrityResult, master_raw: Any, working_raw: Any) -> Path:
        self.paths.incidents.mkdir(parents=True, exist_ok=True)
        diff_fingerprint = fingerprint({"errors": result.errors, "differences": result.differences,
                                        "master": result.master_fingerprint, "working": result.working_fingerprint})
        for candidate in sorted(self.paths.incidents.iterdir()):
            if not candidate.is_dir():
                continue
            manifest_path = candidate / "manifest.json"
            try:
                manifest, _ = _read_json(manifest_path)
            except Exception:
                continue
            if manifest.get("diff_fingerprint") == diff_fingerprint and manifest.get("status") == "PENDING_REVIEW":
                occurrences = manifest.setdefault("occurrences", [])
                occurrences.append(datetime.now(timezone.utc).isoformat())
                manifest["program_version"] = self.program_version
                atomic_write_json(manifest_path, manifest)
                log_path = candidate / "integrity.log"
                if log_path.is_file():
                    current_log = log_path.read_text(encoding="utf-8", errors="replace")
                    if "differences:" not in current_log:
                        log_path.write_text(
                            current_log.rstrip() + "\nerrors: " +
                            (" | ".join(result.errors) if result.errors else "none") +
                            "\ndifferences: " + (" | ".join(
                                f"{d.get('profile_id') or 'global'}:{d.get('field')}:{d.get('kind')}"
                                for d in result.differences
                            ) if result.differences else "none") + "\n",
                            encoding="utf-8",
                        )
                return candidate
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        event_id = uuid.uuid4().hex[:12]
        event_dir = self.paths.incidents / f"{timestamp}_{event_id}_PENDING_REVIEW"
        event_dir.mkdir(parents=True, exist_ok=False)
        manifest = {
            "event_id": event_id, "status": "PENDING_REVIEW", "created_at": datetime.now(timezone.utc).isoformat(),
            "program_version": self.program_version, "config_id": (result.master or {}).get("config_id"),
            "master_fingerprint": result.master_fingerprint, "working_fingerprint": result.working_fingerprint,
            "diff_fingerprint": diff_fingerprint, "errors": list(result.errors), "occurrences": [datetime.now(timezone.utc).isoformat()],
        }
        atomic_write_json(event_dir / "manifest.json", manifest)
        atomic_write_json(event_dir / "master.snapshot.json", master_raw if master_raw is not None else {})
        atomic_write_json(event_dir / "working.snapshot.json", working_raw if working_raw is not None else {})
        atomic_write_json(event_dir / "normalized_diff.json", result.differences)
        log_lines = [
            "integrity check: PENDING_REVIEW",
            f"program_version: {self.program_version}",
            "errors: " + (" | ".join(result.errors) if result.errors else "none"),
            "differences: " + (" | ".join(
                f"{d.get('profile_id') or 'global'}:{d.get('field')}:{d.get('kind')}"
                for d in result.differences
            ) if result.differences else "none"),
        ]
        (event_dir / "integrity.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        (event_dir / "PENDING_REVIEW").touch()
        return event_dir

    @staticmethod
    def _resolve_incident(event_dir: Path, marker: str) -> None:
        manifest_path = event_dir / "manifest.json"
        manifest, _ = _read_json(manifest_path)
        manifest["status"] = marker
        manifest["resolved_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(manifest_path, manifest)
        try:
            (event_dir / "PENDING_REVIEW").unlink()
        except FileNotFoundError:
            pass
        (event_dir / marker).touch()

    def _resolve_matching_incidents(self, master_fp: str, working_fp: str) -> None:
        """Close pending events after an explicit confirmation/manual repair."""
        if not master_fp or not working_fp or not self.paths.incidents.is_dir():
            return
        for event_dir in self.paths.incidents.iterdir():
            if not event_dir.is_dir() or not (event_dir / "PENDING_REVIEW").exists():
                continue
            try:
                manifest, _ = _read_json(event_dir / "manifest.json")
                if (manifest.get("master_fingerprint") == master_fp and
                        manifest.get("working_fingerprint") == working_fp):
                    self._resolve_incident(event_dir, "RESOLVED_MANUALLY")
            except (OSError, ValueError, ConfigIntegrityError):
                continue

    def describe(self, result: IntegrityResult | None = None) -> str:
        result = result or self._last_result
        if not result:
            return "account configuration has not been checked"
        parts = list(result.errors)
        parts.extend(f"{d.get('profile_id') or 'global'}:{d.get('field')}" for d in result.differences)
        if result.master_changed:
            parts.append("master configuration fingerprint changed and requires confirmation")
        return "; ".join(parts) or "account configuration is not trusted"

    def _trusted_profile_ids(self) -> set[str]:
        result = self._last_result or self.check(record_incident=False)
        if not result.ok or not result.master:
            raise ConfigIntegrityBlocked("account configuration is not trusted")
        return set(result.master.get("profiles", {}))

    def _require_profile_id(self, profile_id: str) -> str:
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise ConfigIntegrityBlocked("profile_id is required for runtime records")
        if profile_id not in self._trusted_profile_ids():
            raise ConfigIntegrityBlocked(f"unknown profile_id is not accepted: {profile_id}")
        return profile_id

    def record_completion(self, profile_id: str, task_name: str, when: str | None = None) -> dict[str, Any]:
        """Record a completion under an immutable profile ID in runtime state."""
        with self._lock:
            profile_id = self._require_profile_id(profile_id)
            runtime = self._runtime()
            if self._runtime_error:
                raise ConfigIntegrityBlocked("runtime state is corrupt")
            completions = runtime.setdefault("completed_at", {})
            profile = completions.setdefault(profile_id, {})
            profile[str(task_name)] = when or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            atomic_write_json(self.paths.runtime, runtime)
            return copy.deepcopy(runtime)

    def get_completion(self, profile_id: str, task_name: str) -> str | None:
        with self._lock:
            profile_id = self._require_profile_id(profile_id)
            runtime = self._runtime()
            if self._runtime_error:
                raise ConfigIntegrityBlocked("runtime state is corrupt")
            return ((runtime.get("completed_at") or {}).get(profile_id) or {}).get(str(task_name))

    def get_profile_completions(self, profile_id: str) -> dict[str, str]:
        with self._lock:
            profile_id = self._require_profile_id(profile_id)
            runtime = self._runtime()
            if self._runtime_error:
                raise ConfigIntegrityBlocked("runtime state is corrupt")
            value = (runtime.get("completed_at") or {}).get(profile_id) or {}
            return copy.deepcopy(value) if isinstance(value, dict) else {}

    def get_progress(self, key: str, default: Any = None) -> Any:
        with self._lock:
            runtime = self._runtime()
            if self._runtime_error:
                raise ConfigIntegrityBlocked("runtime state is corrupt")
            return copy.deepcopy((runtime.get("progress") or {}).get(key, default))

    def set_progress(self, key: str, value: Any) -> dict[str, Any]:
        with self._lock:
            runtime = self._runtime()
            if self._runtime_error:
                raise ConfigIntegrityBlocked("runtime state is corrupt")
            runtime.setdefault("progress", {})[str(key)] = copy.deepcopy(value)
            atomic_write_json(self.paths.runtime, runtime)
            return copy.deepcopy(runtime)


class TaskStartGuard:
    """Small adapter suitable for GUI, command-line and scheduler callbacks."""

    def __init__(self, service: ConfigIntegrityService):
        self.service = service

    @property
    def blocked(self) -> bool:
        return not self.service.is_safe

    def check(self) -> bool:
        return self.service.guard_task_start()

    def __call__(self, *args, **kwargs) -> bool:
        return self.check()


def install_task_start_guard(service: ConfigIntegrityService, controller_cls: type) -> bool:
    """Install a fail-closed pre-device-refresh wrapper on StartController."""
    if getattr(controller_cls, "_okww_integrity_guard_installed", False):
        return True
    original = getattr(controller_cls, "do_start", None)
    if not callable(original):
        return False

    def guarded(controller, *args, **kwargs):
        try:
            service.guard_task_start()
        except Exception as exc:
            try:
                from ok.gui.Communicate import communicate
                communicate.starting_emulator.emit(True, str(exc), 0)
            except Exception:
                pass
            return False
        return original(controller, *args, **kwargs)

    controller_cls.do_start = guarded
    controller_cls._okww_integrity_guard_installed = True
    return True


def set_default_service(service: ConfigIntegrityService | None) -> None:
    """Set the process-wide service used by tasks created by the OK framework."""
    global _DEFAULT_SERVICE
    _DEFAULT_SERVICE = service


def get_default_service() -> ConfigIntegrityService | None:
    return _DEFAULT_SERVICE


__all__ = [
    "SCHEMA_VERSION", "PROTECTED_PROFILE_FIELDS", "PROTECTED_TASK_KEYS", "ConfigPaths", "ConfigIntegrityError",
    "ConfigWriteBlocked", "ConfigIntegrityBlocked", "ConfigIntegrityService", "IntegrityResult",
    "TaskStartGuard", "install_task_start_guard", "validate_master", "validate_working", "normalize_master", "normalize_working",
    "diff_normalized", "fingerprint", "canonical_json", "atomic_write_json", "assert_master_read_only",
    "set_default_service", "get_default_service",
]
