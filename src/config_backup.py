"""Verified, recoverable snapshots for the application's ``configs`` tree.

The backup format is deliberately boring: every completed snapshot is a
directory containing a ``manifest.json`` and a byte-for-byte copy of the
source tree.  A snapshot is only visible after its temporary directory has
been verified and atomically renamed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional


MANIFEST_NAME = "manifest.json"


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
        self.config_dir = Path(config_dir)
        self.backup_dir = Path(backup_dir)
        self.app_version = app_version
        self.daily_limit = int(daily_limit)
        self.transaction_limit = int(transaction_limit)
        self.total_limit_bytes = int(total_limit_bytes)
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
            if manifest.get("complete") is not True:
                return VerificationResult(False, error="snapshot is not complete")
            expected = {str(item["path"]): item for item in manifest.get("files", [])}
            root_manifest = path / MANIFEST_NAME
            actual = {p.relative_to(path).as_posix() for p in path.rglob("*")
                      if p.is_file() and p != root_manifest}
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
            return summary
        summary.master_config_present = True
        try:
            from .config_integrity import ConfigIntegrityService, ConfigPaths

            tree = Path(snapshot_path)
            paths = ConfigPaths(
                root=tree,
                config_dir=tree,
                master=tree / "account_master_config.json",
                working=tree / "daily_profiles.json",
                runtime=tree / "account_runtime_state.json",
                incidents=tree.parent / ".backup-preflight-incidents",
                multi_account_task=tree / "MultiAccountDailyTask.json",
            )
            integrity_service = ConfigIntegrityService(paths=paths)
            integrity = integrity_service.check(record_incident=False, resolve_incidents=False)
            if not integrity.ok or not integrity.master:
                summary.ok = False
                summary.error = "invalid account configuration in snapshot: " + "; ".join(
                    integrity.errors or [integrity_service.describe(integrity)])
                return summary
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
        """Restore a verified snapshot by swapping complete directories.

        The previous tree is retained as a transaction snapshot before the
        swap.  If staging or the swap fails, the original directory is put
        back and the exception is re-raised for the caller to enter safe mode.
        """
        if not confirmed:
            raise PermissionError("restore requires explicit confirmation")
        summary = self.preflight_restore(snapshot_path)
        if not summary.ok:
            raise ValueError(summary.error or "snapshot verification failed")
        from .secure_backup import validate_restore_path
        validate_restore_path(snapshot_path, self.config_dir, self.backup_dir.parent)
        if create_rollback:
            self.create_transaction_snapshot()
        source = Path(snapshot_path)
        staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=str(self.backup_dir)))
        old = self.config_dir.with_name(self.config_dir.name + f".rollback-{uuid.uuid4().hex}")
        journal = {
            "version": 1,
            "phase": "prepared",
            "config_dir": str(self.config_dir),
            "staging": str(staging),
            "old": str(old),
            "source": str(source),
        }
        try:
            self._copy_tree(source, staging, exclude_manifest=True)
            # Re-verify the staged bytes against the source manifest before
            # touching the live directory.  This closes the check/copy race
            # and catches a short write or source mutation during staging.
            shutil.copy2(source / MANIFEST_NAME, staging / MANIFEST_NAME)
            staged_verification = self.verify_snapshot(staging)
            if not staged_verification.ok:
                raise RuntimeError(staged_verification.error or "staged restore verification failed")
            (staging / MANIFEST_NAME).unlink()
            journal["phase"] = "verified"
            self._write_restore_journal(journal)
            if self.config_dir.exists():
                os.replace(str(self.config_dir), str(old))
            os.replace(str(staging), str(self.config_dir))
            journal["phase"] = "activated"
            self._write_restore_journal(journal)
            # The preflight above already verified the account integrity
            # graph.  Re-run it at the final path after replacement so a
            # failed or raced restore rolls back before the old tree is lost.
            if summary.master_config_present and not self._account_tree_valid(self.config_dir):
                raise RuntimeError("restored account configuration failed final integrity check")
            shutil.rmtree(old, ignore_errors=True)
            journal["phase"] = "mirrored"
            self._write_restore_journal(journal)
            self._clear_restore_journal()
        except Exception:
            # Roll back synchronously whenever the previous tree exists.  The
            # journal remains only if rollback itself cannot be completed,
            # allowing the next startup to recover it.
            try:
                if old.exists():
                    if self.config_dir.exists():
                        if staging.exists():
                            shutil.rmtree(staging)
                        os.replace(str(self.config_dir), str(staging))
                    os.replace(str(old), str(self.config_dir))
                    shutil.rmtree(staging, ignore_errors=True)
                    self._clear_restore_journal()
                elif self.config_dir.exists():
                    shutil.rmtree(staging, ignore_errors=True)
                    self._clear_restore_journal()
            except Exception:
                pass
            raise
        return summary

    def rollback(self, snapshot_path, *, confirmed=False):
        return self.restore(snapshot_path, confirmed=confirmed, create_rollback=False)

    @property
    def restore_journal_path(self):
        return self.backup_dir / ".restore-journal.json"

    def recover_pending_restore(self):
        """Complete or undo an interrupted directory swap, if one exists."""
        journal_path = self.restore_journal_path
        if not journal_path.is_file():
            return False
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            config = Path(journal["config_dir"])
            staging = Path(journal["staging"])
            old = Path(journal["old"])
            expected_config = self.config_dir.resolve()
            expected_backup = self.backup_dir.resolve()
            if config.resolve() != expected_config:
                raise RuntimeError("restore journal targets another config directory")
            if staging.resolve().parent != expected_backup or not staging.name.startswith(".restore-"):
                raise RuntimeError("restore journal has an unsafe staging path")
            if old.resolve().parent != expected_config.parent or not old.name.startswith(
                    expected_config.name + ".rollback-"):
                raise RuntimeError("restore journal has an unsafe rollback path")
            phase = journal.get("phase")
            if phase in {"prepared", "verified"}:
                # No directory rename was committed.  Keep the live config
                # and discard only the staged copy.
                if not config.exists() and old.exists():
                    os.replace(str(old), str(config))
                else:
                    shutil.rmtree(staging, ignore_errors=True)
            elif phase == "old_moved":
                if not config.exists() and staging.exists():
                    os.replace(str(staging), str(config))
                elif not config.exists() and old.exists():
                    os.replace(str(old), str(config))
                if config.exists() and old.exists() and not self._account_tree_valid(config):
                    os.replace(str(config), str(staging))
                    os.replace(str(old), str(config))
                if config.exists():
                    shutil.rmtree(old, ignore_errors=True)
                    shutil.rmtree(staging, ignore_errors=True)
            elif phase in {"new_moved", "activated", "mirrored"}:
                if not config.exists() and old.exists():
                    os.replace(str(old), str(config))
                elif config.exists() and old.exists() and not self._account_tree_valid(config):
                    if staging.exists():
                        shutil.rmtree(staging)
                    os.replace(str(config), str(staging))
                    os.replace(str(old), str(config))
                if config.exists():
                    shutil.rmtree(old, ignore_errors=True)
                    shutil.rmtree(staging, ignore_errors=True)
            else:
                raise RuntimeError(f"unknown restore journal phase: {phase}")
            if not config.exists():
                raise RuntimeError("restore journal could not recover config directory")
            self._clear_restore_journal()
            return True
        except Exception:
            # Leave the journal for a later startup; silently deleting it
            # would make an interrupted restore unrecoverable.
            return False

    def _write_restore_journal(self, journal):
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        temp = self.restore_journal_path.with_name(f".{self.restore_journal_path.name}.{uuid.uuid4().hex}.tmp")
        temp.write_text(json.dumps(journal, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(str(temp), str(self.restore_journal_path))

    def _clear_restore_journal(self):
        try:
            self.restore_journal_path.unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def _account_tree_valid(config_dir):
        """Validate the protected account graph when the snapshot contains it."""
        config_dir = Path(config_dir)
        if not (config_dir / "account_master_config.json").is_file():
            return True
        try:
            from .config_integrity import ConfigIntegrityService
            return ConfigIntegrityService(config_dir).check(
                record_incident=False, resolve_incidents=False).ok
        except Exception:
            return False

    def cleanup(self):
        """Apply count and shared-capacity retention without partial deletion."""
        daily = self._snapshots("daily")
        transactions = self._snapshots("transaction")
        for item in sorted(daily, key=self._snapshot_sort_key)[:-self.daily_limit or None]:
            shutil.rmtree(item, ignore_errors=True)
        transactions = self._snapshots("transaction")
        for item in sorted(transactions, key=self._snapshot_sort_key)[:-self.transaction_limit or None]:
            shutil.rmtree(item, ignore_errors=True)
        # Capacity policy intentionally evicts daily snapshots first, then
        # transactions, and always removes a whole snapshot directory.
        while self._snapshot_size(self._snapshots("daily") + self._snapshots("transaction")) > self.total_limit_bytes:
            daily = sorted(self._snapshots("daily"), key=self._snapshot_sort_key)
            candidates = daily or sorted(self._snapshots("transaction"), key=self._snapshot_sort_key)
            if not candidates:
                break
            shutil.rmtree(candidates[0], ignore_errors=True)

    def _create_snapshot(self, kind, *, now=None, copy_hook=None):
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
            self.cleanup()
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
    def _copy_tree(source, target, *, copy_hook=None, exclude_manifest=False, exclude_paths=()):
        source, target = Path(source), Path(target)
        target.mkdir(parents=True, exist_ok=True)
        try:
            source_resolved, target_resolved = source.resolve(), target.resolve()
        except OSError:
            source_resolved, target_resolved = source.absolute(), target.absolute()
        excluded = []
        for excluded_path in exclude_paths:
            try:
                excluded.append(Path(excluded_path).resolve())
            except OSError:
                excluded.append(Path(excluded_path).absolute())
        for item in source.rglob("*"):
            # A user may configure the backup root below configs/.  Do not
            # copy the temporary snapshot into itself recursively.
            try:
                if item.resolve() == target_resolved or target_resolved in item.resolve().parents:
                    continue
            except OSError:
                pass
            try:
                if any(item.resolve() == excluded_root or excluded_root in item.resolve().parents
                       for excluded_root in excluded):
                    continue
            except OSError:
                pass
            relative = item.relative_to(source)
            if exclude_manifest and relative.as_posix() == MANIFEST_NAME:
                continue
            destination = target / relative
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            elif item.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                if copy_hook:
                    copy_hook(item, destination)
                else:
                    shutil.copy2(item, destination)

    def _snapshots(self, kind):
        root = self.daily_dir if kind == "daily" else self.transaction_dir
        if not root.is_dir():
            return []
        return [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")
                and (p / MANIFEST_NAME).is_file()]

    @staticmethod
    def _snapshot_sort_key(path):
        try:
            return ConfigBackupService._read_manifest(path).get("created_at", "")
        except Exception:
            return path.stat().st_mtime

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
