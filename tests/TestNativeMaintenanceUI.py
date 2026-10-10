"""Real Qt maintenance coordination with synthetic data and a no-device owner."""

import unittest


class TestNativeMaintenanceUI(unittest.TestCase):
    def test_owner_stop_restore_rebind_close_and_committed_failure(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        TestAccountManagementEntry().run_probe('''
            import time, threading
            from contextlib import ExitStack
            from unittest.mock import patch
            from src.runtime.framework_overlay import install_framework_overlay
            install_framework_overlay(Path(sys.argv[1]))
            from tests.fixture_support import make_account_environment
            from PySide6.QtCore import QProcess
            from PySide6.QtWidgets import QApplication
            from ok.device.DeviceManager import DeviceManager
            from ok.task.TaskExecutor import TaskExecutor
            from src.management import AccountManagementService
            from src.gui.ManagementWindow import ManagementWindow
            from src.native_maintenance import MaintenanceCommittedError
            from src.runtime.account_runtime_bootstrap import get_account_runtime
            from src.account_repository import get_default_repository
            make_account_environment(root / 'data')
            app = QApplication([])
            package = Path(sys.argv[1]) / 'gamepacks/wuthering_waves_native'
            service = AccountManagementService(root / 'data', 'maintenance-ui-test', package_root=package)
            def until(condition):
                deadline = time.monotonic() + 10
                while not condition():
                    app.processEvents()
                    if time.monotonic() > deadline:
                        raise AssertionError(window.status.text())
                    time.sleep(.005)
            def settle():
                until(lambda: not window._operations_busy())
            with ExitStack() as stack:
                stack.enter_context(patch.object(DeviceManager, '__init__', side_effect=AssertionError('device')))
                stack.enter_context(patch.object(TaskExecutor, '__init__', side_effect=AssertionError('executor')))
                stack.enter_context(patch('src.native_schedule.NativeSchedule._service', side_effect=AssertionError('scheduler')))
                window = ManagementWindow(service)
                window.show()
                until(lambda: window.configuration_tab.schema is not None)
                settle()
                assert window.tabs.count() == 10
                ready = []
                window.configuration_tab.schema_changed.connect(lambda schema: ready.append(schema))
                completed, errors = [], []
                work = lambda: completed.append('must-not-run')
                with patch.object(window.configuration_tab, 'shutdown', side_effect=RuntimeError('stop unconfirmed')):
                    window._maintain(work, completed.append, errors.append, False)
                assert not completed and 'stop unconfirmed' in str(errors[-1])
                assert not window._pending_maintenance and window.tabs.isEnabled()
                assert window.configuration_tab.process.state() == QProcess.Running
                for operation in (window.account_tab.account_tab.operation,
                                  window.account_tab.sequence_tab.operation,
                                  window.evidence_tab.load_operation):
                    gate = threading.Event()
                    operation.start(lambda: gate.wait(5), lambda _: None, errors.append)
                    window._maintain(work, completed.append, errors.append, False)
                    assert not completed and '已有操作' in str(errors[-1])
                    assert window.configuration_tab.process.state() == QProcess.Running
                    gate.set()
                    settle()
                def ordinary_failure():
                    raise RuntimeError('ordinary fixture')
                window._maintain(ordinary_failure, completed.append, errors.append, False)
                until(lambda: len(ready) == 1)
                settle()
                assert 'ordinary fixture' in window.status.text()
                assert '已重新加载' in window.status.text()
                assert window.account_tab.isEnabled() and not window._maintenance_committed_failure
                maintenance = window.maintenance_tab.service
                window._maintain(maintenance.create_snapshot, completed.append, errors.append, False)
                until(lambda: len(ready) == 2)
                settle()
                snapshot = completed[-1]
                assert maintenance.verify_snapshot(snapshot.path).ok
                marker = root / 'data/configs/post-snapshot.json'
                marker.write_text('{}')
                preview = maintenance.preview_restore(snapshot.path)
                old_runtime, old_accounts, evidence = service.runtime, window.account_tab, window.evidence_tab
                original_errors = len(errors)
                window._maintain(lambda: maintenance.restore(snapshot.path, preview, confirmed=True),
                                 completed.append, errors.append, True)
                until(lambda: len(ready) == 3)
                settle()
                assert len(errors) == original_errors and not marker.exists()
                assert service.runtime is maintenance.runtime and service.runtime is not old_runtime
                assert window.account_tab is not old_accounts
                assert window.account_tab.account_tab.editor.repository is service.runtime.repository
                assert window.account_tab.sequence_tab.service.repository is service.runtime.repository
                assert window.evidence_tab is evidence
                assert evidence.account_provider() is service.runtime.repository
                assert window.tabs.count() == 10
                gate, entered = threading.Event(), threading.Event()
                def gated_snapshot():
                    entered.set()
                    gate.wait(5)
                    return maintenance.create_snapshot()
                before_completed = len(completed)
                with patch.object(window.configuration_tab, 'reload', wraps=window.configuration_tab.reload) as reload:
                    window._maintain(gated_snapshot, completed.append, errors.append, False)
                    until(entered.is_set)
                    window.close()
                    assert window.isVisible() and window._closing
                    assert window.configuration_tab.process.state() == QProcess.NotRunning
                    gate.set()
                    until(lambda: not window.isVisible())
                    assert len(completed) == before_completed + 1
                    reload.assert_not_called()
                window = ManagementWindow(service)
                window.show()
                until(lambda: window.configuration_tab.schema is not None)
                settle()
                maintenance = window.maintenance_tab.service
                marker.write_text('{}')
                preview = maintenance.preview_restore(snapshot.path)
                with patch('src.runtime.account_runtime_bootstrap.initialize_account_runtime',
                           side_effect=RuntimeError('committed reload fixture')):
                    window._maintain(lambda: maintenance.restore(snapshot.path, preview, confirmed=True),
                                     completed.append, errors.append, True)
                    until(lambda: not window._pending_maintenance)
                assert isinstance(errors[-1], MaintenanceCommittedError)
                assert not marker.exists() and get_account_runtime() is None and get_default_repository() is None
                assert window._maintenance_committed_failure
                assert not window.account_tab.isEnabled() and not window.first_button.isEnabled()
                assert not window.import_button.isEnabled() and not window.review_button.isEnabled()
                assert not window.configuration_tab.isEnabled() and not window.maintenance_tab.isEnabled()
                assert window.configuration_tab.process.state() == QProcess.NotRunning
                assert '磁盘已提交' in window.status.text()
                before_completed = len(completed)
                window._maintain(work, completed.append, errors.append, False)
                assert len(completed) == before_completed
                window.close()
                assert not window.isVisible()
                window.evidence_service.close()
                print('maintenance-coordination-pass')
        ''')


if __name__ == '__main__':
    unittest.main()
