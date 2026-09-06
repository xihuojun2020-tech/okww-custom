"""One account-runtime bootstrap shared by GUI, CLI, scheduler and tasks."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.account_publish_service import AccountPublishService
from src.account_repository import AccountRepository, set_default_repository
from src.config_integrity import (
    ConfigIntegrityService,
    get_default_service,
    install_task_start_guard,
    set_default_service,
)
from src.observability import install_redaction_filters, register_sensitive_values

from .sequence_snapshot_service import SequenceSnapshotService


_LOCK = threading.RLock()
_RUNTIME: "AccountRuntime | None" = None


@dataclass(frozen=True)
class AccountRuntime:
    root: Path
    program_version: str
    integrity_service: Any
    repository: Any
    publish_service: Any
    sequence_snapshot_service: Any
    integrity_result: Any

    def require_ready(self) -> bool:
        return bool(self.integrity_service.guard_task_start())


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def initialize_account_runtime(root=None, program_version=None, *,
                               install_start_guard=True, controller_cls=None) -> AccountRuntime:
    """Initialize once, recovering publication state before integrity checks."""
    global _RUNTIME
    resolved = Path(root or _default_root()).resolve()
    if program_version is None:
        from config import version
        program_version = version
    with _LOCK:
        if _RUNTIME is not None:
            if _RUNTIME.root != resolved:
                raise RuntimeError("account runtime is already initialized for another root")
            return _RUNTIME
        install_redaction_filters()
        from src.config_backup import ConfigBackupService
        from src.storage import get_config_backup_dir
        ConfigBackupService(resolved / 'configs', get_config_backup_dir(resolved))
        from src.account_config_bundle import AccountConfigBundleService
        # Recover legacy/runtime writes before either mirrors or integrity checks.
        AccountConfigBundleService(resolved).recover_incomplete_transactions()
        publish_service = AccountPublishService(resolved, program_version=str(program_version))
        publish_service.recover_incomplete_transactions()
        integrity_service = ConfigIntegrityService(
            resolved, program_version=str(program_version))
        integrity_result = integrity_service.check()
        master = getattr(integrity_result, "master", None) or {}
        profiles = master.get("profiles", {}) if isinstance(master, dict) else {}
        sensitive = []
        for profile_id, profile in profiles.items():
            sensitive.append(profile_id)
            if not isinstance(profile, dict):
                continue
            sensitive.extend(profile.get(key) for key in (
                "display_name", "phone", "masked_phone", "nickname",
                "alternate_login_name", "game_feature_code",
            ))
            aliases = profile.get("account_aliases", ())
            if isinstance(aliases, (list, tuple, set)):
                sensitive.extend(aliases)
        register_sensitive_values(sensitive)
        repository = AccountRepository(
            paths=integrity_service.paths,
            integrity_service=integrity_service,
        )
        try:
            if install_start_guard:
                if controller_cls is None:
                    from ok.gui.StartController import StartController
                    controller_cls = StartController
                if not install_task_start_guard(integrity_service, controller_cls):
                    raise RuntimeError("StartController integrity hook could not be installed")
            set_default_service(integrity_service)
            set_default_repository(repository)
            _RUNTIME = AccountRuntime(
                resolved,
                str(program_version),
                integrity_service,
                repository,
                publish_service,
                SequenceSnapshotService(repository),
                integrity_result,
            )
            return _RUNTIME
        except Exception:
            set_default_service(None)
            set_default_repository(None)
            raise


def get_account_runtime() -> AccountRuntime | None:
    return _RUNTIME


def require_account_runtime_ready() -> AccountRuntime:
    runtime = _RUNTIME
    if runtime is None:
        runtime = initialize_account_runtime()
    runtime.require_ready()
    return runtime


def require_account_runtime_for_task(task) -> AccountRuntime | None:
    """Guard a real framework task while keeping incomplete test doubles inert."""
    service = getattr(task, "integrity_service", None) or get_default_service()
    if service is not None:
        service.guard_task_start()
        task.integrity_service = service
        return _RUNTIME
    if not hasattr(task, "executor") and not hasattr(task, "app"):
        return None
    runtime = require_account_runtime_ready()
    task.integrity_service = runtime.integrity_service
    return runtime


def _reset_account_runtime_for_tests() -> None:
    global _RUNTIME
    with _LOCK:
        _RUNTIME = None
        set_default_service(None)
        set_default_repository(None)


__all__ = [
    "AccountRuntime",
    "get_account_runtime",
    "initialize_account_runtime",
    "require_account_runtime_for_task",
    "require_account_runtime_ready",
]
