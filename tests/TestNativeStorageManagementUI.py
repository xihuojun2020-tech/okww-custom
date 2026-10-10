"""Installed management owner rebinds output readers after a real migration."""
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestNativeStorageManagementUI(unittest.TestCase):
    def test_real_migration_rebind_restart_and_committed_failure(self):
        from scripts.build_native_gamepack import build_native_gamepack
        from gameframe.packages import install_archive
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            installed=install_archive(build_native_gamepack(base/'native.zip'),base/'packages')
            output=TestAccountManagementEntry().run_probe('''
                import json,time
                from contextlib import ExitStack
                from unittest.mock import patch
                from PySide6.QtCore import QProcess
                from PySide6.QtWidgets import QApplication,QMessageBox
                from ok.device.DeviceManager import DeviceManager
                from ok.task.TaskExecutor import TaskExecutor
                from src.management import AccountManagementService
                from src.gui.ManagementWindow import ManagementWindow
                from src.evidence.service import get_evidence_service
                app=QApplication([])
                package=Path(sys.argv[1]).parent
                version=json.loads((package/'manifest.json').read_text(encoding='utf-8'))['version']
                data=root/'data'
                service=AccountManagementService(data,version,package_root=package)
                source,preview=service.preview_first_account(display_name='A1',phone='19910000001',
                    nickname='目录迁移合成账号',sequence_ids=('序列1',))
                service.create_first_account(source,preview,confirm=True)
                def until(condition):
                    deadline=time.monotonic()+12
                    while not condition():
                        app.processEvents()
                        if time.monotonic()>deadline: raise AssertionError(window.status.text())
                        time.sleep(.005)
                def settle(): until(lambda:not window._operations_busy())
                with ExitStack() as stack:
                    stack.enter_context(patch.object(DeviceManager,'__init__',side_effect=AssertionError('device created')))
                    stack.enter_context(patch.object(TaskExecutor,'__init__',side_effect=AssertionError('executor created')))
                    stack.enter_context(patch('src.native_schedule.NativeSchedule._service',side_effect=AssertionError('scheduler action')))
                    window=ManagementWindow(service); window.show()
                    until(lambda:window.configuration_tab.schema is not None); settle()
                    assert window.tabs.count()==10
                    old_evidence=window.evidence_service
                    old_tab=window.evidence_tab; old_diagnostics=window.diagnostics_tab
                    old_maintenance=window.maintenance_tab
                    old_pid=window.configuration_tab.process.processId()
                    paths=window.storage_tab.service.paths()
                    old_shot=paths['screenshots']/'storage-test.png'; old_shot.write_bytes(b'screenshot fixture')
                    report=paths['diagnostics']/'storage-report.txt'; report.write_text('diagnostic fixture')
                    backup=paths['backups']/'storage-backup.json'; backup.parent.mkdir(parents=True,exist_ok=True)
                    backup.write_text('backup fixture')
                    runtime=data/'okww监控室/runtime/control.json'; runtime.parent.mkdir(parents=True,exist_ok=True)
                    runtime.write_text('control remains')
                    schemas=[]
                    window.configuration_tab.schema_changed.connect(lambda schema:schemas.append(schema))
                    tab=window.storage_tab
                    def preview_target(target):
                        tab.destination.setText(str(target)); tab.preview_button.click()
                        until(lambda:not tab.operation.busy)
                        assert tab.migrate_button.isEnabled(),tab.status.text()
                    preview_target(root/'outputs')
                    with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes): tab.migrate_button.click()
                    until(lambda:len(schemas)==1); settle()
                    current=window.storage_tab.service.paths()
                    assert old_shot.exists() and report.exists() and backup.exists()
                    assert (current['screenshots']/'storage-test.png').read_bytes()==b'screenshot fixture'
                    assert (current['diagnostics']/'storage-report.txt').read_text()=='diagnostic fixture'
                    assert (current['backups']/'storage-backup.json').read_text()=='backup fixture'
                    assert runtime.read_text()=='control remains'
                    assert window.evidence_service is not old_evidence
                    assert get_evidence_service() is window.evidence_service
                    assert window.evidence_service.repository.root==current['CompletionEvidence']
                    assert window.evidence_tab is not old_tab and window.evidence_tab.repository.root==current['CompletionEvidence']
                    assert window.diagnostics_tab is not old_diagnostics and window.diagnostics_tab.root==current['diagnostics']
                    assert window.maintenance_tab is not old_maintenance
                    assert window.maintenance_tab.service.paths()['backups']==current['backups']
                    assert window.configuration_tab.process.state()==QProcess.Running
                    assert window.configuration_tab.process.processId()!=old_pid
                    assert window.tabs.count()==10 and not window._maintenance_committed_failure
                    assert '已重新加载' in window.status.text(),window.status.text()
                    window.diagnostics_tab.open_details()
                    details=window.diagnostics_tab._details
                    until(lambda:bool(details.snapshot)); settle()
                    assert details.root==current['diagnostics'] and details.isEnabled() and details.isVisible()
                    preview_target(root/'outputs-second')
                    old_accounts=window.account_tab
                    with patch('src.evidence.service.rebind_evidence_service',side_effect=RuntimeError('postcommit rebind fixture')), \\
                            patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):
                        tab.migrate_button.click()
                        until(lambda:not window._pending_maintenance); settle()
                    selected=json.loads((data/'configs/runtime_storage.json').read_text(encoding='utf-8'))
                    assert selected['root']==str(root/'outputs-second')
                    assert (root/'outputs-second/okww监控室/screenshots/storage-test.png').exists()
                    assert old_shot.exists() and (current['screenshots']/'storage-test.png').exists()
                    assert window._maintenance_committed_failure and window.account_tab is old_accounts
                    assert not old_accounts.isEnabled() and not window.configuration_tab.isEnabled()
                    assert not window.storage_tab.isEnabled() and not window.maintenance_tab.isEnabled()
                    assert not window.evidence_tab.isEnabled() and not window.diagnostics_tab.isEnabled()
                    assert not details.isEnabled()
                    assert window.configuration_tab.process.state()==QProcess.NotRunning
                    assert len(schemas)==1
                    assert '磁盘已提交' in window.status.text() and 'postcommit rebind fixture' in window.status.text()
                    assert '输出目录已提交' in tab.status.text() and '未提交' not in tab.status.text(),tab.status.text()
                    assert '未保存' not in window.status.text()
                    assert window.tabs.count()==10
                    window.close(); until(lambda:not window.isVisible())
                    window.evidence_service.close()
                payload=Path(sys.argv[1]).resolve()
                assert all(Path(module.__file__).resolve().is_relative_to(payload)
                    for name,module in sys.modules.items() if name.startswith('src.') and getattr(module,'__file__',None))
                print('native-storage-management-pass')
            ''',source_root=installed.root/'payload',core_root=ROOT)
            self.assertIn('native-storage-management-pass',output)
