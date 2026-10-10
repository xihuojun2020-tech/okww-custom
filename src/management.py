# SPDX-License-Identifier: AGPL-3.0-or-later
"""Game-pack management extension, launched independently from native execution."""

from pathlib import Path

from src.account_config_bundle import AccountConfigBundleService, BundleImportBlocked
from src.account_config_editor import new_account_payload
from src.runtime.account_runtime_bootstrap import initialize_account_runtime
from src.storage import resolve_config_backup_dir


class AccountManagementService:
    def __init__(self, data_dir, program_version, *, package_root=None):
        self.root = Path(data_dir).resolve()
        self.package_root = Path(package_root).resolve() if package_root is not None else None
        self.runtime = initialize_account_runtime(
            self.root, program_version, install_start_guard=False,
            backup_dir=resolve_config_backup_dir(self.root))
        self.bundles = AccountConfigBundleService(
            self.root, integrity_service=self.runtime.integrity_service)

    def first_account_available(self):
        paths = self.runtime.integrity_service.paths
        return not paths.master.exists() and not paths.working.exists()

    def preview_first_account(self, **values):
        if not self.first_account_available():
            raise BundleImportBlocked('已有账号配置，请使用完整性检查或导入配置包')
        sequence_ids = values.pop('sequence_ids', ())
        account, tasks = new_account_payload({}, **values)
        label = account['display_name']
        source = {'type': 'okww_account_config', 'version': 1,
                  'profiles': {label: {**account, 'task_config': tasks}},
                  'sequences': {name: [label] for name in sequence_ids}}
        preview = self.bundles.preflight_import(source)
        if preview.errors:
            raise BundleImportBlocked('; '.join(preview.errors))
        # Freeze the first-anchor converter's generated config ID before the
        # import repeats preflight and checks that the reviewed bundle is stable.
        source['master'] = preview.candidate_master
        preview = self.bundles.preflight_import(source)
        return source, preview

    def create_first_account(self, source, preview, *, confirm=False):
        if not self.first_account_available():
            raise BundleImportBlocked('已有账号配置，请重新查看配置')
        return self.bundles.import_bundle(source, confirm=confirm, preflight=preview)


def manage(data_dir, program_version, *, package_root=None):
    """Open existing Qt business widgets without constructing an OK app or device."""
    from src.runtime import combat_api
    combat_api.configure(native=False, data_dir=data_dir)
    service = AccountManagementService(data_dir, program_version, package_root=package_root)
    from src.gui.ManagementWindow import run_management_window
    return run_management_window(service)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='鸣潮账号与完成证据管理')
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--package-root', type=Path)
    args = parser.parse_args()
    return manage(args.data_dir, args.version, package_root=args.package_root)


if __name__ == '__main__':
    raise SystemExit(main())
