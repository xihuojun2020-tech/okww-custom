# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read existing account state in a separate process without configuration writes."""

import json
import sys
import threading
from pathlib import Path


def overview(data_dir, program_version, *, package_root=None):
    from contextlib import ExitStack
    from gameframe.process_locks import package_lease, data_lease
    from src.native_maintenance import require_no_pending_restore
    from src.storage import resolve_config_backup_dir
    root = Path(data_dir).resolve()
    with ExitStack() as leases:
        if package_root is not None:
            leases.enter_context(package_lease(package_root))
        leases.enter_context(data_lease(root))
        require_no_pending_restore(root, resolve_config_backup_dir(root))
        from src.runtime import combat_api
        combat_api.configure(native=True, data_dir=root)
        from src.account_repository import AccountRepository
        from src.config_integrity import ConfigIntegrityService, ConfigIntegrityBlocked
        integrity = ConfigIntegrityService(root, program_version=program_version)
        result = integrity.check(record_incident=False, resolve_incidents=False)
        if not result.ok:
            raise ConfigIntegrityBlocked(integrity.describe(result))
        repository = AccountRepository(root, integrity_service=integrity)
        from src.evidence.repository import EvidenceRepository
        from src.runtime.native_live_status import NativeLiveReader
        from src.gui.NativeExecutionOverviewDialog import NativeExecutionOverviewDialog
        from src.gui.CodexTheme import apply_codex_light_theme
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt, QMetaObject, QThreadPool
        app = QApplication.instance() or QApplication([])
        from src.runtime.native_language import install_qt_language, load_language
        install_qt_language(app, load_language(root, pack_root=package_root))
        apply_codex_light_theme(app)
        dialog = NativeExecutionOverviewDialog(repository, NativeLiveReader(root),
            timing_repository=EvidenceRepository(root / 'okww监控室/CompletionEvidence'))
        dialog.finished.connect(app.quit)

        def read_commands():
            for line in sys.stdin:
                try:
                    message = json.loads(line)
                except ValueError as error:
                    print(json.dumps({'type': 'overview-error', 'error': str(error)}), flush=True)
                    continue
                if message.get('command') == 'stop':
                    QMetaObject.invokeMethod(dialog, 'reject', Qt.QueuedConnection)
                    return

        threading.Thread(target=read_commands, name='OverviewCommands', daemon=True).start()
        dialog.show()
        print(json.dumps({'type': 'overview-ready'}), flush=True)
        try:
            return app.exec()
        finally:
            dialog.timer.stop()
            dialog.overview.timer.stop()
            dialog.watcher.blockSignals(True)
            for timing in dialog._timing_dialogs:
                timing.timer.stop()
            # This dedicated process owns only the overview's read workers.
            # Keep code/data leases until their actual file reads have ended.
            QThreadPool.globalInstance().waitForDone()


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--package-root', type=Path)
    args = parser.parse_args()
    return overview(args.data_dir, args.version, package_root=args.package_root)


if __name__ == '__main__':
    raise SystemExit(main())
