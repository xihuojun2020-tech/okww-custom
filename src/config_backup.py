"""Verified, recoverable snapshots for the application's ``configs`` tree.

The backup format is deliberately boring: every completed snapshot is a
directory containing a ``manifest.json`` and a byte-for-byte copy of the
source tree.  A snapshot is only visible after its temporary directory has
been verified and atomically renamed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Optional


MANIFEST_NAME = "manifest.json"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Snapshot:
    path: Path
    kind: str
    is_complete: bool = True


@dataclass
class VerificationResult:
    ok: bool
    files: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    hash_differences: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class RestoreSummary:
    ok: bool
    files: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    hash_differences: list[str] = field(default_factory=list)
    error: str = ""
    master_config_present: bool = False
    account_count: int = 0
    sequence_count: int = 0
    sequence_member_count: int = 0
    sequence_summary: dict[str, int] = field(default_factory=dict)


class ConfigBackupService:
    """Create, verify and safely restore complete configuration snapshots."""

    def __init__(self, config_dir, backup_dir, *, app_version="", daily_limit=30,
                 transaction_limit=20, total_limit_bytes=2 * 1024 ** 3,
                 harden_permissions=True):
        from .secure_backup import validate_restore_path
        from .account_change_lock import get_account_change_lock
        self.backup_dir, self.config_dir = validate_restore_path(backup_dir, config_dir)
        self._lock = get_account_change_lock(self.config_dir)
        self.app_version = app_version
        self.daily_limit = max(0, int(daily_limit))
        self.transaction_limit = max(0, int(transaction_limit))
        self.total_limit_bytes = max(0, int(total_limit_bytes))
        self.harden_permissions = bool(harden_permissions)
        self._permissions_hardened = False
        # A process can terminate between the two directory renames during
        # restore.  Recover that swap before exposing this service to callers.
        self.recover_pending_restore()

    @property
    def daily_dir(self):
        return self.backup_dir / "daily"

    @property
    def transaction_dir(self):
        return self.backup_dir / "transactions"

    def has_daily_snapshot_for_date(self, date=None):
        date = date or datetime.now().strftime("%Y-%m-%d")
        for snapshot in self._snapshots("daily"):
            try:
                manifest = self._read_manifest(snapshot)
                if manifest.get("created_date") == date:
                    return True
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return False

    def create_daily_snapshot(self, *, now=None, copy_hook: Optional[Callable] = None):
        return self._create_snapshot("daily", now=now, copy_hook=copy_hook)

    def create_transaction_snapshot(self, *, now=None, copy_hook: Optional[Callable] = None):
        return self._create_snapshot("transaction", now=now, copy_hook=copy_hook)

    # Thin aliases make the service easy to adapt while the core transaction
    # service is being integrated by the account configuration work.
    snapshot_daily = create_daily_snapshot
    snapshot_transaction = create_transaction_snapshot

    def verify_snapshot(self, snapshot_path) -> VerificationResult:
        path = Path(snapshot_path)
        try:
            manifest = self._read_manifest(path)
            if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), list):
                raise ValueError('invalid snapshot manifest shape')
            if manifest.get("complete") is not True:
                return VerificationResult(False, error="snapshot is not complete")
            expected = {}
            canonical_names = set()
            for item in manifest['files']:
                if not isinstance(item, dict) or not isinstance(item.get('path'), str):
                    raise ValueError('invalid snapshot file entry')
                name = item['path']
                parts = PurePosixPath(name).parts
                if (not parts or PurePosixPath(name).is_absolute() or '..' in parts or
                        '\\' in name or ':' in name or PurePosixPath(name).as_posix() != name or
                        name.casefold() in canonical_names or name == MANIFEST_NAME):
                    raise ValueError('unsafe or duplicate snapshot file path')
                canonical_names.add(name.casefold())
                expected[name] = item
            root_manifest = path / MANIFEST_NAME
            actual = {p.relative_to(path).as_posix() for p in self._tree_files(path)
                      if p != root_manifest}
            missing = sorted(set(expected) - actual)
            extra = sorted(actual - set(expected))
            differences = []
            for name in sorted(set(expected) & actual):
                item = expected[name]
                current = path / Path(name)
                stat = current.stat()
                if stat.st_size != item.get("length") or self._sha256(current) != item.get("sha256"):
                    differences.append(name)
            return VerificationResult(
                not (missing or extra or differences),
                files=sorted(expected), missing=missing, extra=extra,
                hash_differences=differences,
            )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return VerificationResult(False, error=str(exc))

    def preflight_restore(self, snapshot_path) -> RestoreSummary:
        result = self.verify_snapshot(snapshot_path)
        summary = RestoreSummary(result.ok, result.files, result.missing, result.extra,
                                 result.hash_differences, result.error)
        if not result.ok:
            return summary
        master_path = Path(snapshot_path) / "account_master_config.json"
        if not master_path.is_file():
            # Backups created by releases before the master-config feature
            # remain restorable, but the UI makes that absence explicit.
            if (Path(snapshot_path) / 'published' / 'active.json').exists():
                summary.ok = False
                summary.error = 'active graph exists without master configuration'
            return summary
        summary.master_config_present = True
        try:
            tree = Path(snapshot_path)
            integrity_service = self._tree_integrity(tree)
            integrity = integrity_service.check(record_incident=False, resolve_incidents=False)
            if not integrity.ok or not integrity.master:
                summary.ok = False
                summary.error = "invalid account configuration in snapshot: " + "; ".join(
                    integrity.errors or [integrity_service.describe(integrity)])
                return summary
            self._validate_active_tree(tree, integrity.master)
            profiles = integrity.master.get("profiles", {})
            sequences = integrity.master.get("sequences", {})
            summary.account_count = len(profiles)
            summary.sequence_count = len(sequences)
            summary.sequence_summary = {str(name): len(members) for name, members in sequences.items()}
            summary.sequence_member_count = sum(summary.sequence_summary.values())
            return summary
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            summary.ok = False
            summary.error = f"cannot inspect master configuration in snapshot: {exc}"
            return summary

    # Explicit names used by recovery controllers and UI adapters.
    summarize_restore = preflight_restore

    def restore(self, snapshot_path, *, confirmed=False, create_rollback=True):
        """Copy across volumes, then commit by renaming only on the target volume."""
        if not confirmed:
            raise PermissionError("restore requires explicit confirmation")
        from .account_config_bundle import AccountConfigBundleService
        from .secure_backup import validate_restore_path, harden_directory_permissions
        with self._lock:
            AccountConfigBundleService.require_idle_executor()
            self.recover_pending_restore()
            source, _ = validate_restore_path(
                snapshot_path, self.config_dir, source_root=self.backup_dir,
                target_dir=self.config_dir)
            # Retain this exact manifest, closing a source+manifest copy race.
            manifest_bytes = (source / MANIFEST_NAME).read_bytes()
            summary = self.preflight_restore(source)
            if not summary.ok:
                raise ValueError(summary.error or "snapshot verification failed")
            self.config_dir.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=self.config_dir.parent))
            old = self.config_dir.with_name(self.config_dir.name + f".rollback-{uuid.uuid4().hex}")
            journal = {"version": 2, "phase": "prepared", "config_dir": str(self.config_dir),
                       "staging": str(staging), "old": str(old), "source": str(source),
                       "had_config": self.config_dir.exists()}
            committed = False
            try:
                if self.harden_permissions:
                    harden_directory_permissions(staging)
                self._write_restore_journal(journal)
                # A pending journal protects both the source and the rollback
                # snapshot from retention, including another cleanup instance.
                if create_rollback and self.config_dir.exists():
                    self.create_transaction_snapshot()
                self._copy_tree(source, staging, exclude_manifest=True)
                (staging / MANIFEST_NAME).write_bytes(manifest_bytes)
                checked = self.preflight_restore(staging)
                if not checked.ok:
                    raise RuntimeError(checked.error or "staged restore verification failed")
                (staging / MANIFEST_NAME).unlink()
                journal['phase'] = 'verified'
                self._write_restore_journal(journal)
                if self.config_dir.exists():
                    os.replace(self.config_dir, old)
                os.replace(staging, self.config_dir)
                self._recover_account_tree()
                if not self._account_tree_valid(self.config_dir):
                    raise RuntimeError("restored account configuration failed final integrity check")
                # Only this durable marker commits the directory transaction.
                journal['phase'] = 'activated'
                self._write_restore_journal(journal)
                committed = True
            except Exception:
                try:
                    self.recover_pending_restore()
                except Exception as recovery_error:
                    logger.error('restore rollback pending: %s', recovery_error)
                if not self.restore_journal_path.exists() and staging.exists():
                    shutil.rmtree(staging)
                raise
            finally:
                if committed:
                    try:
                        self.recover_pending_restore()
                    except Exception as maintenance_error:
                        # Configuration committed successfully; keep the journal
                        # and old directory for the next cleanup/startup retry.
                        logger.warning('restore committed; cleanup pending: %s', maintenance_error)
            return summary

    def rollback(self, snapshot_path, *, confirmed=False):
        return self.restore(snapshot_path, confirmed=confirmed, create_rollback=False)

    @property
    def restore_journal_path(self):
        # Outside configs, so startup can discover it even after configs was
        # renamed and the warehouse setting is temporarily unavailable.
        return self.config_dir.parent / f'.{self.config_dir.name}-restore' / 'journal.json'

    def _pending_restore_journal(self):
        if self.restore_journal_path.exists():
            return self.restore_journal_path
        legacy = self.backup_dir / '.restore-journal.json'
        return legacy if legacy.exists() else None

    def recover_pending_restore(self):
        """Roll back uncommitted swaps; finish cleanup after a durable commit.

        Invalid journals raise and retain evidence instead of allowing a new
        restore to overwrite the only recovery record.
        """
        from .secure_backup import validate_restore_path
        with self._lock:
            journal_path = self._pending_restore_journal()
            if journal_path is None:
                return False
            validate_restore_path(journal_path, self.config_dir)
            journal = json.loads(journal_path.read_text(encoding='utf-8'))
            config = Path(journal['config_dir'])
            staging = Path(journal['staging'])
            old = Path(journal['old'])
            if config != self.config_dir:
                raise RuntimeError('restore journal targets another config directory')
            allowed_parent = self.backup_dir if journal.get('version') == 1 else config.parent
            validate_restore_path(staging, config)
            validate_restore_path(old, config)
            if staging.parent != allowed_parent or not staging.name.startswith('.restore-'):
                raise RuntimeError('restore journal has an unsafe staging path')
            if old.parent != config.parent or not old.name.startswith(config.name + '.rollback-'):
                raise RuntimeError('restore journal has an unsafe rollback path')
            phase = journal.get('phase')
            if phase not in {'prepared', 'verified', 'old_moved', 'new_moved', 'activated', 'mirrored'}:
                raise RuntimeError('unknown restore journal phase')
            committed = phase in {'new_moved', 'activated', 'mirrored'}
            if committed and config.exists():
                if not self._account_tree_valid(config):
                    if not old.exists():
                        raise RuntimeError('committed restore is invalid and rollback directory is missing')
                    committed = False
            else:
                committed = False
            if not committed:
                if old.exists():
                    if staging.exists():
                        shutil.rmtree(staging)
                    if config.exists():
                        # Legacy staging might be across volumes; use a new,
                        # target-sibling discard path and persist it first.
                        if staging.parent != config.parent:
                            staging = config.parent / f'.restore-{uuid.uuid4().hex}'
                            journal.update(version=2, staging=str(staging))
                            self._write_restore_journal(journal)
                        os.replace(config, staging)
                    os.replace(old, config)
                elif not config.exists() and journal.get('had_config', True):
                    raise RuntimeError('restore journal could not recover config directory')
                elif not journal.get('had_config', True) and config.exists():
                    os.replace(config, staging)
            for path in (old, staging):
                if path.exists():
                    shutil.rmtree(path)
                    if path.exists():
                        raise OSError('restore cleanup made no progress')
            journal_path.unlink(missing_ok=True)
            self.restore_journal_path.unlink(missing_ok=True)
            return True

    def _write_restore_journal(self, journal):
        from .config_integrity import _atomic_write_json_unchecked
        from .secure_backup import harden_directory_permissions, validate_restore_path
        validate_restore_path(self.restore_journal_path, self.config_dir)
        if self.harden_permissions:
            harden_directory_permissions(self.restore_journal_path.parent)
        _atomic_write_json_unchecked(self.restore_journal_path, journal)

    def _recover_account_tree(self):
        if (self.config_dir / 'account_master_config.json').exists():
            from .account_config_bundle import AccountConfigBundleService
            AccountConfigBundleService(
                integrity_service=self._tree_integrity(self.config_dir)).recover_incomplete_transactions()

    @staticmethod
    def _tree_integrity(tree):
        from .config_integrity import ConfigIntegrityService, ConfigPaths
        tree = Path(tree)
        return ConfigIntegrityService(paths=ConfigPaths(
            root=tree.parent, config_dir=tree, master=tree / 'account_master_config.json',
            working=tree / 'daily_profiles.json', runtime=tree / 'account_runtime_state.json',
            incidents=tree.parent / '.backup-preflight-incidents',
            multi_account_task=tree / 'MultiAccountDailyTask.json'))

    @staticmethod
    def _validate_active_tree(tree, master):
        from .account_publish_service import AccountPublishService
        from .config_integrity import normalize_master
        publisher = AccountPublishService(tree, config_dir=tree)
        if not publisher.active_path.exists():
            return  # Supported legacy snapshots without an active graph.
        active = publisher.load_active()
        published = json.loads((active.bundle_dir / 'account_master_config.json').read_text(encoding='utf-8'))
        if normalize_master(published) != master:
            raise ValueError('active graph differs from legacy account configuration')

    @classmethod
    def _account_tree_valid(cls, config_dir):
        config_dir = Path(config_dir)
        if not (config_dir / 'account_master_config.json').is_file():
            return not (config_dir / 'published' / 'active.json').exists()
        try:
            integrity = cls._tree_integrity(config_dir).check(
                record_incident=False, resolve_incidents=False)
            if not integrity.ok:
                return False
            cls._validate_active_tree(config_dir, integrity.master)
            return True
        except Exception:
            return False

    def cleanup(self, *, protected=()):
        """Bound retention work and stop visibly when deletion makes no progress."""
        with self._lock:
            if self._pending_restore_journal() is not None:
                return
            protected = set(protected)
            for kind, limit in (('daily', self.daily_limit), ('transaction', self.transaction_limit)):
                snapshots = sorted(self._snapshots(kind), key=self._snapshot_sort_key)
                excess = max(0, len(snapshots) - limit)
                candidates = [path for path in snapshots if path not in protected]
                for item in candidates[:excess]:
                    if not self._delete_snapshot(item):
                        return
            while True:
                daily = sorted(self._snapshots('daily'), key=self._snapshot_sort_key)
                transactions = sorted(self._snapshots('transaction'), key=self._snapshot_sort_key)
                if self._snapshot_size(daily + transactions) <= self.total_limit_bytes:
                    return
                candidates = [path for path in daily + transactions if path not in protected]
                if not candidates or not self._delete_snapshot(candidates[0]):
                    return

    @staticmethod
    def _delete_snapshot(path):
        try:
            shutil.rmtree(path)
            if path.exists():
                raise OSError('directory still exists')
            return True
        except OSError as error:
            logger.warning('backup cleanup stopped for %s: %s', path.name, error)
            return False

    def _create_snapshot(self, kind, *, now=None, copy_hook=None):
        with self._lock:
            return self._create_snapshot_locked(kind, now=now, copy_hook=copy_hook)

    def _create_snapshot_locked(self, kind, *, now=None, copy_hook=None):
        if not self.config_dir.is_dir():
            raise FileNotFoundError(self.config_dir)
        target_root = self.daily_dir if kind == "daily" else self.transaction_dir
        target_root.mkdir(parents=True, exist_ok=True)
        if self.harden_permissions and not self._permissions_hardened:
            from .secure_backup import harden_directory_permissions
            harden_directory_permissions(self.backup_dir)
            self._permissions_hardened = True
        timestamp = time.time() if now is None else float(now)
        stamp = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y%m%dT%H%M%S")
        snapshot_id = f"{stamp}-{time.time_ns()}-{uuid.uuid4().hex[:8]}"
        temp_path = target_root / f".{snapshot_id}.tmp"
        final_path = target_root / snapshot_id
        temp_path.mkdir()
        try:
            self._copy_tree(self.config_dir, temp_path, copy_hook=copy_hook,
                            exclude_paths=(self.backup_dir,))
            manifest = self._manifest(temp_path, kind, timestamp)
            (temp_path / MANIFEST_NAME).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            verification = self.verify_snapshot(temp_path)
            if not verification.ok:
                raise RuntimeError(verification.error or "snapshot verification failed")
            os.replace(str(temp_path), str(final_path))
            self.cleanup(protected=(final_path,))
            return Snapshot(final_path, kind)
        except Exception:
            shutil.rmtree(temp_path, ignore_errors=True)
            raise

    def _manifest(self, path, kind, timestamp):
        files = []
        for item in sorted(path.rglob("*")):
            if not item.is_file():
                continue
            relative = item.relative_to(path).as_posix()
            files.append({
                "path": relative,
                "length": item.stat().st_size,
                "mtime": item.stat().st_mtime,
                "sha256": self._sha256(item),
            })
        created = datetime.fromtimestamp(timestamp, timezone.utc)
        return {
            "format": 1,
            "kind": kind,
            "complete": True,
            "app_version": self.app_version,
            "created_at": created.isoformat(),
            "created_date": created.astimezone().strftime("%Y-%m-%d"),
            "files": files,
        }

    @staticmethod
    def _read_manifest(path):
        from .secure_backup import validate_restore_path
        validate_restore_path(Path(path) / MANIFEST_NAME, Path(path).with_name('.manifest-path-check'))
        with (Path(path) / MANIFEST_NAME).open("r", encoding="utf-8") as stream:
            return json.load(stream)

    @staticmethod
    def _sha256(path):
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _tree_files(root, *, include_dirs=False):
        """Walk without traversing symlinks or Windows junctions."""
        root = Path(root)
        from .secure_backup import validate_restore_path
        validate_restore_path(root, root.with_name(root.name + '.path-check'))
        def on_error(error):
            raise error
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=on_error):
            for name in dirs + files:
                item = Path(directory) / name
                if item.is_symlink() or item.is_junction():
                    raise ValueError('snapshot tree contains a symlink or junction')
            for name in files:
                yield Path(directory) / name
            if include_dirs:
                for name in dirs:
                    yield Path(directory) / name

    @staticmethod
    def _copy_tree(source, target, *, copy_hook=None, exclude_manifest=False, exclude_paths=()):
        source, target = Path(source), Path(target)
        target.mkdir(parents=True, exist_ok=True)
        for item in ConfigBackupService._tree_files(source, include_dirs=True):
            relative = item.relative_to(source)
            if exclude_manifest and relative.as_posix() == MANIFEST_NAME:
                continue
            destination = target / relative
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            (copy_hook or shutil.copy2)(item, destination)

    def _snapshots(self, kind):
        root = self.daily_dir if kind == "daily" else self.transaction_dir
        if not root.is_dir():
            return []
        return [p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and not p.is_junction()
                and not p.name.startswith(".")
                and (p / MANIFEST_NAME).is_file()]

    @staticmethod
    def _snapshot_sort_key(path):
        try:
            return ConfigBackupService._read_manifest(path).get("created_at", "")
        except Exception:
            return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()

    @staticmethod
    def _snapshot_size(snapshots: Iterable[Path]):
        total = 0
        for root in snapshots:
            for item in root.rglob("*"):
                if item.is_file():
                    try:
                        total += item.stat().st_size
                    except OSError:
                        pass
        return total


# Name used by early integration adapters.
ConfigBackupEngine = ConfigBackupService


def create_daily_snapshot(config_dir, backup_dir, **kwargs):
    now, copy_hook = kwargs.pop("now", None), kwargs.pop("copy_hook", None)
    return ConfigBackupService(config_dir, backup_dir, **kwargs).create_daily_snapshot(
        now=now, copy_hook=copy_hook)


def create_transaction_snapshot(config_dir, backup_dir, **kwargs):
    now, copy_hook = kwargs.pop("now", None), kwargs.pop("copy_hook", None)
    return ConfigBackupService(config_dir, backup_dir, **kwargs).create_transaction_snapshot(
        now=now, copy_hook=copy_hook)


def verify_backup(config_dir, backup_dir, snapshot_path):
    return ConfigBackupService(config_dir, backup_dir).verify_snapshot(snapshot_path)


def restore_backup(config_dir, backup_dir, snapshot_path, *, confirmed=False):
    return ConfigBackupService(config_dir, backup_dir).restore(snapshot_path, confirmed=confirmed)
