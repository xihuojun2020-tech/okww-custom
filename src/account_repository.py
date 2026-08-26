"""Small, file-oriented boundary for account configuration and run state.

The account master remains the source of account IDs.  Mutable run state is
kept outside the master and outside the legacy working copy, so a task can
never accidentally save progress into another account's configuration.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .config_integrity import ConfigIntegrityBlocked, ConfigPaths, atomic_write_json


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_DEFAULT_REPOSITORY: "AccountRepository | None" = None


class AccountRepositoryError(RuntimeError):
    """Raised when an account repository cannot safely serve a request."""


class ProfileRevisionConflict(AccountRepositoryError):
    """The master changed after an edit scope was opened."""


@dataclass(frozen=True)
class ProfileEditScope:
    profile_id: str
    base_revision: str


@dataclass(frozen=True)
class ProfileRecord:
    profile_id: str
    revision: str
    account: Mapping[str, Any]
    tasks: Mapping[str, Any]


@dataclass(frozen=True)
class SequenceRecord:
    sequence_id: str
    revision: str
    profile_ids: tuple[str, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AccountDeletionPreview:
    profile_id: str
    account_label: str
    sequence_ids: tuple[str, ...]
    runtime_present: bool


@dataclass
class ReadyResult:
    """Structural readiness with external edits reported at account scope."""

    ok: bool
    errors: list[str] = field(default_factory=list)
    account_errors: dict[str, list[str]] = field(default_factory=dict)
    external_changes: list[str] = field(default_factory=list)
    accounts: dict[str, Any] = field(default_factory=dict)
    sequences: dict[str, list[str]] = field(default_factory=dict)
    index: dict[str, Any] | None = None

    @property
    def ready(self) -> bool:
        return self.ok

    def __bool__(self) -> bool:
        return self.ok

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "account_errors": copy.deepcopy(self.account_errors),
            "external_changes": list(self.external_changes),
            "accounts": copy.deepcopy(self.accounts),
            "sequences": copy.deepcopy(self.sequences),
            "index": copy.deepcopy(self.index),
        }

    to_dict = as_dict


def _json_read(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            return json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AccountRepositoryError(f"读取账号仓库失败：{path}：{exc}") from exc


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _profile_id(value: Any) -> str:
    text = str(value or "").strip()
    if not _UUID_RE.fullmatch(text):
        raise AccountRepositoryError(f"账号 UUID 无效：{value!r}")
    return text


class AccountRepository:
    """Read account index and own only account-scoped mutable runtime files."""

    def __init__(self, root: os.PathLike | str | None = None, *,
                 paths: ConfigPaths | None = None, index_path: os.PathLike | str | None = None,
                 runtime_dir: os.PathLike | str | None = None,
                 account_dir: os.PathLike | str | None = None,
                 sequence_dir: os.PathLike | str | None = None,
                 backup_dir: os.PathLike | str | None = None, migration_service: Any | None = None,
                 migration: Any | None = None, integrity_service: Any | None = None):
        self.paths = paths or ConfigPaths.from_root(root)
        self.root = self.paths.root
        self.index_path = Path(index_path) if index_path is not None else self.paths.master
        self.integrity_service = integrity_service
        self.migration_service = migration_service or migration
        runtime_root = Path(runtime_dir) if runtime_dir is not None else self.root / "运行状态"
        self.runtime_dir = runtime_root
        self.account_runtime_dir = runtime_root / "账号"
        self.account_dir = Path(account_dir) if account_dir is not None else self.root / "账号"
        self.sequence_dir = Path(sequence_dir) if sequence_dir is not None else self.root / "序列"
        self.progress_path = runtime_root / "全局.json"
        self.backup_dir = Path(backup_dir) if backup_dir is not None else self.root / "账号备份"
        self._lock = threading.RLock()
        self._verified_account_digests: dict[str, str] | None = None

    @property
    def account_state_dir(self) -> Path:
        return self.account_runtime_dir

    @property
    def global_progress_path(self) -> Path:
        return self.progress_path

    @property
    def profile_backup_dir(self) -> Path:
        return self.backup_dir

    def _load_index(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[str]]]:
        raw = _json_read(self.index_path)
        if not isinstance(raw, Mapping):
            raise AccountRepositoryError("账号索引必须是 JSON 对象")
        raw = dict(raw)
        source = raw.get("accounts", raw.get("profiles", {}))
        if isinstance(source, list):
            source = {str(item.get("profile_id")): item for item in source
                      if isinstance(item, Mapping) and item.get("profile_id")}
        if not isinstance(source, Mapping):
            raise AccountRepositoryError("账号索引的 accounts/profiles 必须是对象")
        accounts: dict[str, Any] = {}
        errors: list[str] = []
        for key, value in source.items():
            try:
                profile_id = _profile_id(value.get("profile_id", key) if isinstance(value, Mapping) else key)
            except AccountRepositoryError as exc:
                errors.append(str(exc))
                continue
            if profile_id != str(key) and str(key) in source:
                errors.append(f"账号索引 UUID 不一致：{key!r} != {profile_id!r}")
            if not isinstance(value, Mapping):
                errors.append(f"账号 {profile_id} 必须是对象")
                continue
            accounts[profile_id] = copy.deepcopy(dict(value))
        if errors:
            raise AccountRepositoryError("；".join(errors))
        sequences_raw = raw.get("sequences", {})
        if not isinstance(sequences_raw, Mapping):
            raise AccountRepositoryError("序列索引必须是对象")
        sequences: dict[str, list[str]] = {}
        for name, members in sequences_raw.items():
            if not isinstance(name, str) or not name.strip() or not isinstance(members, list):
                raise AccountRepositoryError(f"序列结构无效：{name!r}")
            resolved: list[str] = []
            for member in members:
                try:
                    member_id = _profile_id(member)
                except AccountRepositoryError as exc:
                    raise AccountRepositoryError(f"序列 {name} 成员无效：{member!r}") from exc
                if member_id not in accounts:
                    raise AccountRepositoryError(f"序列 {name} 引用了不存在的账号：{member_id}")
                if member_id in resolved:
                    raise AccountRepositoryError(f"序列 {name} 包含重复账号：{member_id}")
                resolved.append(member_id)
            sequences[name] = resolved
        return raw, accounts, sequences

    def _require_account(self, profile_id: str) -> str:
        profile_id = _profile_id(profile_id)
        try:
            _, accounts, _ = self._load_index()
        except AccountRepositoryError:
            raise
        if profile_id not in accounts:
            raise AccountRepositoryError(f"账号不存在：{profile_id}")
        return profile_id

    @staticmethod
    def _revision(raw: Mapping[str, Any]) -> str:
        return _digest(raw)

    def list_profile_ids(self) -> tuple[str, ...]:
        return tuple(self._load_index()[1])

    def list_profiles(self) -> tuple[ProfileRecord, ...]:
        return tuple(self.load_profile(profile_id) for profile_id in self.list_profile_ids())

    def legacy_profile_projection(self, *_args, **_kwargs) -> dict[str, Any]:
        """Detached name-keyed compatibility view for existing PC tasks."""
        profiles = {}
        for record in self.list_profiles():
            name = str(record.account.get("display_name") or record.profile_id)
            profiles[name] = {"profile_id": record.profile_id, **copy.deepcopy(dict(record.account)),
                              **copy.deepcopy(dict(record.tasks))}
        _, _, sequences = self._load_index()
        names = {record.profile_id: str(record.account.get("display_name") or record.profile_id)
                 for record in self.list_profiles()}
        return {"profiles": profiles,
                "sequences": {key: [names[item] for item in value] for key, value in sequences.items()}}

    get_detached_projection = legacy_profile_projection

    def load_profile(self, profile_id: str) -> ProfileRecord:
        raw, accounts, _ = self._load_index()
        profile_id = _profile_id(profile_id)
        if profile_id not in accounts:
            raise AccountRepositoryError(f"账号不存在：{profile_id}")
        profile = copy.deepcopy(accounts[profile_id])
        tasks = profile.pop("task_config", {})
        return ProfileRecord(profile_id, self._revision(raw), profile, copy.deepcopy(tasks))

    def _publish_master(self, raw: Mapping[str, Any]) -> None:
        from . import account_config_bundle as bundle_module

        service = bundle_module.AccountConfigBundleService(
            self.root, integrity_service=self.integrity_service)
        bundle = service.export_bundle()
        bundle["master_config"] = copy.deepcopy(dict(raw))
        bundle["manifest"]["config_id"] = raw.get("config_id")
        bundle["manifest"]["partitions"] = {
            name: bundle_module._digest(bundle[name])
            for name in bundle_module._PARTITION_NAMES
        }
        service.import_bundle(bundle, confirm=True, trust_external=True)

    def publish_profile(self, scope: ProfileEditScope, payload: Mapping[str, Any], **_kwargs) -> ProfileRecord:
        with self._lock:
            raw, accounts, _ = self._load_index()
            profile_id = _profile_id(scope.profile_id)
            if self._revision(raw) != str(scope.base_revision):
                raise ProfileRevisionConflict(f"账号 {profile_id} 已被其他修改")
            if profile_id not in accounts:
                raise AccountRepositoryError(f"账号不存在：{profile_id}")
            account = payload.get("account", {})
            tasks = payload.get("tasks", {})
            if not isinstance(account, Mapping) or not isinstance(tasks, Mapping):
                raise AccountRepositoryError("账号草稿结构无效")
            if account.get("profile_id") not in (None, profile_id):
                raise AccountRepositoryError("草稿不能修改 profile_id")
            candidate = copy.deepcopy(raw)
            candidate["profiles"][profile_id] = {**copy.deepcopy(dict(account)),
                                                  "task_config": copy.deepcopy(dict(tasks))}
            if "sequence_ids" in payload:
                sequence_ids = tuple(str(name).strip() for name in payload["sequence_ids"])
                if len(set(sequence_ids)) != len(sequence_ids):
                    raise AccountRepositoryError("账号序列不能重复")
                if any(name not in candidate.get("sequences", {}) for name in sequence_ids):
                    raise AccountRepositoryError("账号序列不存在")
                for name, members in candidate.get("sequences", {}).items():
                    members = [member for member in members if member != profile_id]
                    if name in sequence_ids:
                        members.append(profile_id)
                    candidate["sequences"][name] = members
            self._publish_master(candidate)
            return self.load_profile(profile_id)

    def list_sequence_ids(self) -> tuple[str, ...]:
        return tuple(self._load_index()[2])

    def load_sequence(self, sequence_id: str) -> SequenceRecord:
        raw, _, sequences = self._load_index()
        name = str(sequence_id).strip()
        if name not in sequences:
            raise AccountRepositoryError(f"序列不存在：{name}")
        settings = raw.get("extensions", {}).get("pc_sequence_settings", {})
        metadata = settings.get(name, {}) if isinstance(settings, Mapping) else {}
        return SequenceRecord(name, self._revision(raw), tuple(sequences[name]),
                              copy.deepcopy(dict(metadata)) if isinstance(metadata, Mapping) else {})

    def publish_sequence(self, sequence_id: str, profile_ids: list[str], *,
                         expected_revision: str | int = "", metadata: Mapping[str, Any] | None = None,
                         **_kwargs) -> SequenceRecord:
        with self._lock:
            raw, accounts, sequences = self._load_index()
            revision = self._revision(raw)
            if expected_revision not in (0, "", None) and str(expected_revision) != revision:
                raise ProfileRevisionConflict(f"序列 {sequence_id} 已被其他修改")
            name = str(sequence_id).strip()
            if not name:
                raise AccountRepositoryError("序列名称不能为空")
            members = [_profile_id(value) for value in profile_ids]
            if len(set(members)) != len(members):
                raise AccountRepositoryError("序列不能包含重复账号")
            if any(value not in accounts for value in members):
                raise AccountRepositoryError("序列引用了不存在的账号")
            candidate = copy.deepcopy(raw)
            candidate.setdefault("sequences", {})[name] = members
            settings = candidate.setdefault("extensions", {}).setdefault("pc_sequence_settings", {})
            settings[name] = copy.deepcopy(dict(metadata or settings.get(name, {})))
            self._publish_master(candidate)
            return self.load_sequence(name)

    def rename_sequence(self, sequence_id: str, new_sequence_id: str, *, expected_revision: str) -> SequenceRecord:
        with self._lock:
            raw, _, sequences = self._load_index()
            if self._revision(raw) != str(expected_revision):
                raise ProfileRevisionConflict(f"序列 {sequence_id} 已被其他修改")
            old, new = str(sequence_id).strip(), str(new_sequence_id).strip()
            if old not in sequences or not new or new in sequences:
                raise AccountRepositoryError("序列重命名目标无效或已存在")
            candidate = copy.deepcopy(raw)
            items = candidate["sequences"]
            candidate["sequences"] = {new if key == old else key: value for key, value in items.items()}
            settings = candidate.setdefault("extensions", {}).setdefault("pc_sequence_settings", {})
            if old in settings:
                settings[new] = settings.pop(old)
            self._publish_master(candidate)
            return self.load_sequence(new)

    def delete_sequence(self, sequence_id: str, *, expected_revision: str) -> None:
        with self._lock:
            raw, _, sequences = self._load_index()
            if self._revision(raw) != str(expected_revision):
                raise ProfileRevisionConflict(f"序列 {sequence_id} 已被其他修改")
            name = str(sequence_id).strip()
            if name not in sequences:
                raise AccountRepositoryError(f"序列不存在：{name}")
            candidate = copy.deepcopy(raw)
            del candidate["sequences"][name]
            candidate.get("extensions", {}).get("pc_sequence_settings", {}).pop(name, None)
            self._publish_master(candidate)

    def preview_profile_deletion(self, profile_id: str) -> AccountDeletionPreview:
        raw, accounts, sequences = self._load_index()
        profile_id = _profile_id(profile_id)
        if profile_id not in accounts:
            raise AccountRepositoryError(f"账号不存在：{profile_id}")
        account = accounts[profile_id]
        label = str(account.get("display_name") or account.get("short_name") or "未命名账号")
        references = tuple(name for name, members in sequences.items() if profile_id in members)
        return AccountDeletionPreview(profile_id, label, references,
                                      self._account_state_path(profile_id).is_file())

    def delete_profile_cascade(self, profile_id: str, *, expected_revision: str) -> AccountDeletionPreview:
        """Back up, remove sequence references, and delete one account atomically."""
        with self._lock:
            raw, accounts, sequences = self._load_index()
            profile_id = _profile_id(profile_id)
            if self._revision(raw) != str(expected_revision):
                raise ProfileRevisionConflict("账号配置已被其他操作修改")
            if profile_id not in accounts:
                raise AccountRepositoryError(f"账号不存在：{profile_id}")
            if len(accounts) <= 1:
                raise AccountRepositoryError("至少必须保留一个账号")
            preview = self.preview_profile_deletion(profile_id)
            record = self.load_profile(profile_id)
            self.backup_profile(profile_id, {
                "profile_id": profile_id, "revision": record.revision,
                "account": dict(record.account), "tasks": dict(record.tasks),
                "referenced_sequences": list(preview.sequence_ids),
            })
            state_path = self._account_state_path(profile_id)
            task_path = self.paths.multi_account_task or self.paths.config_dir / "MultiAccountDailyTask.json"
            protected_paths = tuple(dict.fromkeys((self.paths.master, self.paths.working,
                                                   self.paths.runtime, task_path, state_path)))
            before = {path: path.read_bytes() if path.exists() else None for path in protected_paths}
            candidate = copy.deepcopy(raw)
            source_key = "accounts" if "accounts" in candidate else "profiles"
            del candidate[source_key][profile_id]
            candidate["sequences"] = {
                name: [member for member in members if member != profile_id]
                for name, members in sequences.items()
            }
            try:
                self._publish_master(candidate)
                state_path.unlink(missing_ok=True)
                hook = getattr(self, "deletion_postcheck_hook", None)
                if callable(hook):
                    hook()
                return preview
            except Exception:
                from . import config_integrity as ci
                for path, payload in before.items():
                    if payload is None:
                        path.unlink(missing_ok=True)
                    elif path == self.paths.master:
                        from .account_config_bundle import _atomic_replace_unchecked
                        _atomic_replace_unchecked(path, payload)
                    else:
                        ci._atomic_replace_bytes(path, payload)
                raise

    def _account_state_path(self, profile_id: str) -> Path:
        return self.account_runtime_dir / f"{_profile_id(profile_id)}.json"

    def recover_incomplete_transactions(self) -> Any:
        """Delegate recovery to the existing migration/transaction service."""
        service = self.migration_service or self.integrity_service
        if service is None:
            return False
        for name in ("recover_incomplete_transactions", "recover_pending_restore", "recover_pending"):
            method = getattr(service, name, None)
            if callable(method):
                return method()
        return False

    def backup_profile(self, profile_id: str, payload: Any) -> Path:
        """Append an immutable backup under exactly one validated account UUID."""
        with self._lock:
            profile_id = self._require_account(profile_id)
            if isinstance(payload, Mapping):
                embedded = payload.get("profile_id", payload.get("account_id"))
                if embedded is not None and str(embedded) != profile_id:
                    raise AccountRepositoryError("账号备份越界：payload 的 UUID 与目标账号不一致")
            target = self.backup_dir / profile_id
            target.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            path = target / f"{stamp}-{time.time_ns()}-{uuid.uuid4().hex[:8]}.json"
            data = {"profile_id": profile_id, "created_at": datetime.now(timezone.utc).isoformat(),
                    "payload": copy.deepcopy(payload)}
            atomic_write_json(path, data)
            return path

    def record_completion(self, profile_id: str, task_name: str,
                          when: str | None = None) -> dict[str, Any]:
        with self._lock:
            profile_id = self._require_account(profile_id)
            path = self._account_state_path(profile_id)
            current = _json_read(path) if path.is_file() else {}
            if not isinstance(current, dict):
                raise AccountRepositoryError(f"账号运行状态必须是对象：{profile_id}")
            current[str(task_name)] = when or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            atomic_write_json(path, current)
            return copy.deepcopy(current)

    def get_completion(self, profile_id: str, task_name: str) -> str | None:
        with self._lock:
            profile_id = self._require_account(profile_id)
            path = self._account_state_path(profile_id)
            if not path.is_file():
                return None
            state = _json_read(path)
            if not isinstance(state, Mapping):
                raise AccountRepositoryError(f"账号运行状态必须是对象：{profile_id}")
            value = state.get(str(task_name))
            return value if isinstance(value, str) else None

    def get_profile_completions(self, profile_id: str) -> dict[str, Any]:
        with self._lock:
            profile_id = self._require_account(profile_id)
            path = self._account_state_path(profile_id)
            if not path.is_file():
                return {}
            state = _json_read(path)
            if not isinstance(state, Mapping):
                raise AccountRepositoryError(f"账号运行状态必须是对象：{profile_id}")
            return copy.deepcopy(dict(state))

    def _read_progress(self) -> dict[str, Any]:
        if not self.progress_path.is_file():
            return {}
        value = _json_read(self.progress_path)
        if not isinstance(value, dict):
            raise AccountRepositoryError("全局进度必须是 JSON 对象")
        return value

    def get_progress(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return copy.deepcopy(self._read_progress().get(str(key), default))

    def set_progress(self, key: str, value: Any) -> dict[str, Any]:
        with self._lock:
            progress = self._read_progress()
            progress[str(key)] = copy.deepcopy(value)
            atomic_write_json(self.progress_path, progress)
            return copy.deepcopy(progress)

    def verify_ready(self) -> ReadyResult:
        """Validate the account graph; report unconfirmed edits per account."""
        errors: list[str] = []
        account_errors: dict[str, list[str]] = {}
        external: list[str] = []
        try:
            raw, accounts, sequences = self._load_index()
        except AccountRepositoryError as exc:
            return ReadyResult(False, errors=[str(exc)])
        for profile_id, account in accounts.items():
            account_error: list[str] = []
            digest = account.get("digest") or account.get("fingerprint") if isinstance(account, Mapping) else None
            if digest:
                current = _digest({k: v for k, v in account.items() if k not in {"digest", "fingerprint"}})
                if str(digest).casefold() != current.casefold():
                    account_error.append("账号配置存在未确认的外部修改")
                    external.append(profile_id)
            account_path = self.account_dir / f"{profile_id}.json"
            if self.account_dir.is_dir():
                if not account_path.is_file():
                    account_error.append("账号文件缺失")
                else:
                    try:
                        account_file = _json_read(account_path)
                        if not isinstance(account_file, Mapping):
                            account_error.append("账号文件结构无效")
                        elif account_file.get("profile_id") not in (None, profile_id):
                            account_error.append("账号文件 UUID 不一致")
                    except AccountRepositoryError as exc:
                        account_error.append(str(exc))
            state_path = self._account_state_path(profile_id)
            if state_path.is_file():
                try:
                    state = _json_read(state_path)
                    if not isinstance(state, Mapping):
                        account_error.append("账号运行状态结构无效")
                except AccountRepositoryError as exc:
                    account_error.append(str(exc))
            if account_error:
                account_errors[profile_id] = account_error
        current_digests = {
            profile_id: _digest({key: value for key, value in account.items()
                                 if key not in {"digest", "fingerprint"}})
            for profile_id, account in accounts.items()
        }
        if self._verified_account_digests is not None:
            for profile_id, digest in current_digests.items():
                if self._verified_account_digests.get(profile_id) not in (None, digest):
                    account_errors.setdefault(profile_id, []).append("账号配置存在未确认的外部修改")
                    external.append(profile_id)
        self._verified_account_digests = current_digests
        if self.sequence_dir.is_dir():
            expected = {str(name) for name in sequences}
            actual = {path.stem for path in self.sequence_dir.glob("*.json")}
            for missing in sorted(expected - actual):
                errors.append(f"序列文件缺失：{missing}")
            for extra in sorted(actual - expected):
                errors.append(f"序列文件未登记：{extra}")
            for name in sorted(expected & actual):
                try:
                    sequence_data = _json_read(self.sequence_dir / f"{name}.json")
                    members = sequence_data.get("members") if isinstance(sequence_data, Mapping) else sequence_data
                    if not isinstance(members, list) or members != sequences[name]:
                        errors.append(f"序列文件结构无效：{name}")
                except AccountRepositoryError as exc:
                    errors.append(str(exc))
        # A changed master fingerprint is review data, not an invalid graph.
        accepted = None
        if self.paths.runtime.is_file():
            try:
                runtime = _json_read(self.paths.runtime)
                if isinstance(runtime, Mapping):
                    accepted = runtime.get("accepted_master_fingerprint")
            except AccountRepositoryError:
                pass
        if accepted and str(accepted) != _digest(raw):
            external.extend(pid for pid in accounts if pid not in external)
        fatal_account_errors = {
            profile_id: [error for error in values if error != "账号配置存在未确认的外部修改"]
            for profile_id, values in account_errors.items()
        }
        fatal_account_errors = {key: value for key, value in fatal_account_errors.items() if value}
        return ReadyResult(not errors and not fatal_account_errors, errors=errors, account_errors=account_errors,
                           external_changes=sorted(set(external)), accounts=accounts,
                           sequences=sequences, index=raw)


def set_default_repository(repository: AccountRepository | None) -> None:
    global _DEFAULT_REPOSITORY
    _DEFAULT_REPOSITORY = repository


def get_default_repository() -> AccountRepository | None:
    return _DEFAULT_REPOSITORY


__all__ = ["AccountDeletionPreview", "AccountRepository", "AccountRepositoryError", "ProfileRevisionConflict",
           "ProfileEditScope", "ProfileRecord", "SequenceRecord", "ReadyResult",
           "set_default_repository", "get_default_repository"]
