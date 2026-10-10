# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration maintenance at the native data-owner boundary."""

from contextlib import contextmanager
from pathlib import Path

from gameframe.process_locks import LeaseUnavailable, data_lease
from src.account_change_lock import get_account_change_lock
from src.config_backup import ConfigBackupService
from src.config_integrity import ConfigIntegrityBlocked, ConfigIntegrityService
from src.runtime.account_runtime_bootstrap import reload_account_runtime
from src.storage import resolve_config_backup_dir


class MaintenanceCommittedError(RuntimeError):
    """The disk operation committed, but the fresh runtime could not load."""

    committed = True

    def __init__(self, operation, error):
        self.operation = operation
        super().__init__(f'{operation}已写入磁盘，但账号运行时重载失败：{error}')


def require_no_pending_restore(root, backup_dir):
    """Owners holding SH must never run directory-swap recovery."""
    journals = (Path(root) / '.configs-restore/journal.json',
                Path(backup_dir) / '.restore-journal.json')
    if any(path.exists() for path in journals):
        raise RuntimeError('配置恢复尚未完成，须先取得数据独占锁完成恢复')


def prepare_native_data(data_root, program_version):
    """Recover under EX, then take the first safe daily snapshot for this date."""
    root = Path(data_root).resolve()
    backups = resolve_config_backup_dir(root)
    try:
        with data_lease(root, exclusive=True):
            with get_account_change_lock(root / 'configs'):
                service = ConfigBackupService(root / 'configs', backups,
                                              app_version=str(program_version))
                if not (root / 'configs').is_dir():
                    return {'status': 'not-initialized', 'snapshot': None}
                if service.has_daily_snapshot_for_date():
                    return {'status': 'already-created', 'snapshot': None}
                return {'status': 'created', 'snapshot': service.create_daily_snapshot()}
    except LeaseUnavailable:
        # An existing owner may defer the snapshot, but cannot authorize recovery
        # of a pending directory transaction while it still uses that tree.
        require_no_pending_restore(root, backups)
        return {'status': 'deferred', 'snapshot': None}


class NativeMaintenanceService:
    def __init__(self, data_root, program_version):
        self.root = Path(data_root).resolve()
        self.program_version = str(program_version)
        self.runtime = None

    def paths(self):
        return {'data': self.root, 'configs': self.root / 'configs',
                'backups': resolve_config_backup_dir(self.root),
                'restore_journal': self.root / '.configs-restore/journal.json'}

    @contextmanager
    def _engine(self, *, exclusive=False):
        with data_lease(self.root, exclusive=exclusive):
            with get_account_change_lock(self.root / 'configs'):
                paths = self.paths()
                if not exclusive:
                    require_no_pending_restore(self.root, paths['backups'])
                yield ConfigBackupService(paths['configs'], paths['backups'],
                                          app_version=self.program_version)

    def create_snapshot(self):
        with self._engine(exclusive=True) as engine:
            return engine.create_transaction_snapshot()

    def verify_snapshot(self, path):
        with self._engine() as engine:
            return engine.verify_snapshot(path)

    def preview_restore(self, path):
        with self._engine() as engine:
            return engine.preflight_restore(path)

    def _reload(self, operation):
        self.runtime = None
        try:
            self.runtime = reload_account_runtime(
                self.root, self.program_version,
                backup_dir=resolve_config_backup_dir(self.root))
        except Exception as error:
            raise MaintenanceCommittedError(operation, error) from error

    def restore(self, path, preview, *, confirmed=False):
        with self._engine(exclusive=True) as engine:
            result = engine.restore(path, confirmed=confirmed, preflight=preview)
            self._reload('restore')
            return result

    def preview_sequence_repair(self):
        with self._engine():
            return ConfigIntegrityService(
                self.root, program_version=self.program_version).detect_missing_sequences()

    def repair_sequences(self, preview, *, confirmed=False):
        if not confirmed:
            raise ConfigIntegrityBlocked('explicit confirmation is required to restore legacy sequences')
        with self._engine(exclusive=True) as engine:
            integrity = ConfigIntegrityService(self.root, program_version=self.program_version)
            current = integrity.detect_missing_sequences()
            if not current.get('eligible') or any(
                    current.get(key) != preview.get(key)
                    for key in ('master_fingerprint', 'source', 'sequences')):
                raise ConfigIntegrityBlocked('序列恢复预览已变化，请重新查看并确认')
            engine.create_transaction_snapshot()
            result = integrity.repair_missing_sequences(confirm=True)
            self._reload('repair_sequences')
            return result

    def cleanup(self):
        with self._engine() as engine:
            return engine.cleanup()
