"""Real first-account and import transactions plus isolated no-device Qt entry."""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestAccountManagementEntry(unittest.TestCase):
    def run_probe(self, body, *, stdin=None, source_root=ROOT, core_root=None):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'management_probe.py'
            script.write_text('import sys\nfrom pathlib import Path\nsys.path.insert(0, sys.argv[1])\n'
                              'if len(sys.argv) > 3: sys.path.append(sys.argv[3])\n'
                              'root = Path(sys.argv[2])\n' + textwrap.dedent(body), encoding='utf-8')
            environment = dict(os.environ, QT_QPA_PLATFORM='offscreen')
            environment['PYTHONPATH'] = os.pathsep.join(str(path) for path in (source_root, core_root) if path is not None)
            command = [sys.executable, '-I', '-B', '-X', 'utf8', str(script), str(source_root), directory]
            if core_root is not None:
                command.append(str(core_root))
            result = subprocess.run(command,
                                    input=stdin, capture_output=True, text=True, encoding='utf-8',
                                    timeout=35, env=environment)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout

    def test_fresh_setup_requires_real_identity_and_explicit_transaction_confirmation(self):
        self.run_probe('''
            from src.management import AccountManagementService
            from src.account_config_bundle import BundleImportBlocked
            from src.account_config_editor import AccountConfigEditor, AccountConfigEditorError
            service = AccountManagementService(root / 'data', 'test-management')
            assert service.first_account_available()
            paths = service.runtime.integrity_service.paths
            assert not paths.master.exists()
            try:
                service.preview_first_account(display_name='A1', phone='invalid', nickname='测试')
            except AccountConfigEditorError:
                pass
            else:
                raise AssertionError('invalid phone accepted')
            source, preview = service.preview_first_account(display_name='A1', phone='19910000001',
                nickname='首个合成账号', alias_enabled=True, alias_text='UTEST0001A',
                sequence_ids=('序列1',), game_feature_code='001234')
            assert preview.ok and preview.account_count == 1
            assert not paths.master.exists()
            try:
                service.create_first_account(source, preview)
            except BundleImportBlocked:
                pass
            else:
                raise AssertionError('unconfirmed setup accepted')
            assert not paths.master.exists()
            result = service.create_first_account(source, preview, confirm=True)
            assert result.ok
            assert service.runtime.require_ready()
            first = service.runtime.repository.list_profiles()[0]
            assert first.account['phone'] == '19910000001'
            assert first.account['alternate_login_name'] == 'UTEST0001A'
            assert first.account['game_feature_code'] == '001234'
            assert first.tasks['Garden Execution Mode'] == 'closed'
            editor = AccountConfigEditor(service.runtime.repository)
            second = editor.create_profile(editor.load_template(), display_name='A3',
                phone='19910000003', nickname='后续合成账号', sequence_ids=('序列1',))
            assert second.account['masked_phone'] == '199****0003'
            assert len(service.runtime.repository.list_profiles()) == 2
            before = paths.master.read_bytes()
            try:
                service.create_first_account(source, preview, confirm=True)
            except BundleImportBlocked:
                pass
            else:
                raise AssertionError('existing master overwritten by first setup')
            assert paths.master.read_bytes() == before
            assert not any(name.split('.')[0] in {'ok','PySide6','qfluentwidgets','config'} for name in sys.modules)
        ''')

    def test_export_import_into_empty_installation_uses_original_verified_bundle_flow(self):
        self.run_probe('''
            from src.management import AccountManagementService
            from src.runtime.account_runtime_bootstrap import _reset_account_runtime_for_tests
            source_service = AccountManagementService(root / 'source', 'test-management')
            source, preview = source_service.preview_first_account(display_name='B2', phone='19910000002',
                nickname='导入合成账号', sequence_ids=('序列2',))
            source_service.create_first_account(source, preview, confirm=True)
            filename = root / 'portable.json'
            source_service.bundles.export_bundle(filename)
            source_id = source_service.runtime.repository.list_profiles()[0].profile_id
            _reset_account_runtime_for_tests()
            destination = AccountManagementService(root / 'destination', 'test-management')
            preview = destination.bundles.preflight_import(filename)
            assert preview.ok and preview.account_count == 1
            assert not destination.runtime.integrity_service.paths.master.exists()
            destination.bundles.import_bundle(filename, confirm=True, preflight=preview)
            destination.runtime.require_ready()
            imported = destination.runtime.repository.list_profiles()[0]
            assert imported.profile_id == source_id
            assert imported.account['phone'] == '19910000002'
            assert destination.runtime.integrity_service.paths.master.parent == root / 'destination' / 'configs'
        ''')

    def test_real_management_window_opens_and_stdin_stop_closes_without_device(self):
        output = self.run_probe('''
            from src.runtime.framework_overlay import install_framework_overlay
            install_framework_overlay(Path(sys.argv[1]))
            from unittest.mock import patch
            from ok.device.DeviceManager import DeviceManager
            from ok.task.TaskExecutor import TaskExecutor
            from src.management import manage
            with patch.object(DeviceManager, '__init__', side_effect=AssertionError('management created device')), \\
                 patch.object(TaskExecutor, '__init__', side_effect=AssertionError('management created executor')):
                assert manage(root / 'data', 'test-management') == 0
            assert not (root / 'data/configs/accounts_master.json').exists()
        ''', stdin='{"command":"stop"}\n')
        self.assertIn('management-ready', output)

    def test_ready_account_and_completion_widgets_open_without_game_capture_or_executor(self):
        output = self.run_probe('''
            from src.runtime.framework_overlay import install_framework_overlay
            install_framework_overlay(Path(sys.argv[1]))
            from unittest.mock import patch
            from ok.device.DeviceManager import DeviceManager
            from ok.task.TaskExecutor import TaskExecutor
            from src.management import AccountManagementService, manage
            service = AccountManagementService(root / 'data', 'test-management')
            source, preview = service.preview_first_account(display_name='A1', phone='19910000001',
                nickname='管理合成账号', sequence_ids=('序列1',))
            service.create_first_account(source, preview, confirm=True)
            from src.gui.ManagementWindow import ManagementWindow
            original_show = ManagementWindow.show
            def verified_show(window):
                assert window.tabs.count() == 3
                assert not window.account_tab.account_tab.read_feature_button.isEnabled()
                assert not window.evidence_tab.capture_button.isEnabled()
                assert window.evidence_tab.executor is None
                assert window.evidence_service.repository.root == root / 'data/okww监控室/CompletionEvidence'
                original_show(window)
            with patch.object(DeviceManager, '__init__', side_effect=AssertionError('management created device')), \\
                 patch.object(TaskExecutor, '__init__', side_effect=AssertionError('management created executor')), \\
                 patch.object(ManagementWindow, 'show', verified_show):
                assert manage(root / 'data', 'test-management') == 0
        ''', stdin='{"command":"stop"}\n')
        self.assertIn('management-ready', output)

    def test_diagnostics_management_reads_local_state_and_explicit_buttons_own_external_actions(self):
        self.run_probe('''
            from src.runtime.framework_overlay import install_framework_overlay
            install_framework_overlay(Path(sys.argv[1]))
            import importlib.abc
            import time
            import threading
            from contextlib import ExitStack
            from unittest.mock import patch
            from PySide6.QtWidgets import QApplication, QPushButton, QDialog, QMessageBox
            class BlockCheckout(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname.split('.')[0] in {'config','main','custom_ok'}:
                        raise ImportError('management imported ' + fullname)
            sys.meta_path.insert(0, BlockCheckout())
            from src.management import AccountManagementService
            from src.gui.ManagementWindow import ManagementWindow
            from src.runtime import diagnostic_lifecycle
            app = QApplication([])
            service = AccountManagementService(root / 'data', 'diagnostics-management-test')
            def settle(operation):
                deadline = time.monotonic() + 3
                while operation.busy and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(.005)
                assert not operation.busy
                app.processEvents()
            with ExitStack() as stack:
                names = ('subprocess.Popen', 'src.runtime.diagnostic_policy.ensure_task',
                    'src.runtime.diagnostic_policy.save_credentials', 'src.runtime.diagnostic_policy.connect',
                    'src.runtime.diagnostic_lifecycle.start_diagnostics',
                    'src.runtime.diagnostic_lifecycle.wake_uploader',
                    'src.runtime.diagnostic_lifecycle.start_automatic_archive_upload',
                    'src.runtime.diagnostic_archive_retention.maintenance_loop',
                    'src.runtime.diagnostic_archive.send_archive', 'src.runtime.diagnostic_archive.connect',
                    'src.runtime.diagnostic_archive_retention.connect', 'src.runtime.diagnostic_uploader.connect')
                spies = [stack.enter_context(patch(name, side_effect=AssertionError(name))) for name in names]
                wake_card = stack.enter_context(patch('src.gui.DiagnosticStatusCard.wake_uploader',
                                                     side_effect=AssertionError('implicit card upload')))
                wake_details = stack.enter_context(patch('src.gui.DiagnosticDetails.wake_uploader',
                                                        side_effect=AssertionError('implicit backfill upload')))
                window = ManagementWindow(service)
                window.show()
                card = window.diagnostics_tab
                settle(card.operation)
                assert window.tabs.count() == 1
                assert card.root == root / 'data/okww监控室/diagnostics'
                assert card.source_root == service.root
                assert card.program_version == 'diagnostics-management-test'
                assert card.local_only
                capture = next(button for button in card.findChildren(QPushButton)
                               if button.text() == '测试错误截图')
                assert not capture.isEnabled()
                card.open_details()
                details = card._details
                settle(details.operation)
                assert details.index.source == service.root and details.local_only
                card.save()
                settle(card.operation)
                with patch('src.gui.DiagnosticDetails.QDialog.exec', return_value=QDialog.Accepted), \
                     patch('src.gui.DiagnosticDetails.QMessageBox.question', return_value=QMessageBox.Yes), \
                     patch('src.gui.DiagnosticDetails.backfill_preview', return_value=[]) as preview, \
                     patch('src.gui.DiagnosticDetails.enqueue_backfill', return_value=['queued']) as enqueue:
                    details.backfill()
                    settle(details.operation)
                    assert preview.call_args.args[0] == service.root
                    assert enqueue.call_args.args == (card.root, [], 'diagnostics-management-test')
                for spy in spies:
                    spy.assert_not_called()
                wake_card.assert_not_called()
                wake_details.assert_not_called()
                assert diagnostic_lifecycle._session is None
                with patch('src.runtime.diagnostic_archive.manual_upload', return_value='synthetic.zip') as upload:
                    card.retry()
                    settle(card.operation)
                    upload.assert_called_once_with(card.root)
                with patch('src.gui.DiagnosticStatusCard.bounded_probe', return_value={}) as probe:
                    card.test_connection()
                    settle(card.operation)
                    assert probe.call_count == 1
                marker = threading.Event()
                card.operation.start(lambda: marker.wait(2), lambda _: None, lambda error: None)
                window.close()
                assert window.isVisible() and window._closing
                marker.set()
                settle(card.operation)
                assert not window.isVisible()
                window.evidence_service.close()
        ''')

    def test_installed_native_archive_management_has_no_checkout_config_or_overlay_dependency(self):
        from scripts.build_native_gamepack import build_native_gamepack
        from gameframe.packages import install_archive
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            archive = build_native_gamepack(temporary / 'native.zip')
            installed = install_archive(archive, temporary / 'installed')
            self.assertIn('ok-script==1.0.190',
                          (installed.root / 'requirements-management.txt').read_text(encoding='utf-8'))
            payload = installed.root / 'payload'
            self.assertFalse((payload / 'config.py').exists())
            self.assertFalse((payload / 'main.py').exists())
            self.assertFalse((payload / 'custom_ok').exists())
            output = self.run_probe('''
                import importlib.abc
                class ForbidCheckout(importlib.abc.MetaPathFinder):
                    def find_spec(self, fullname, path=None, target=None):
                        if fullname.split('.')[0] in {'config', 'main', 'custom_ok'}:
                            raise ImportError('management imported checkout module ' + fullname)
                sys.meta_path.insert(0, ForbidCheckout())
                from unittest.mock import patch
                from ok.device.DeviceManager import DeviceManager
                from ok.task.TaskExecutor import TaskExecutor
                from src.management import AccountManagementService, manage
                assert Path(sys.modules['src.management'].__file__).is_relative_to(Path(sys.argv[1]))
                service = AccountManagementService(root / 'data', 'artifact-test')
                source, preview = service.preview_first_account(display_name='A1', phone='19910000001',
                    nickname='载荷合成账号', sequence_ids=('序列1',))
                service.create_first_account(source, preview, confirm=True)
                from src.gui.ManagementWindow import ManagementWindow
                original_show = ManagementWindow.show
                def verified_show(window):
                    assert window.tabs.count() == 3
                    assert not window.evidence_tab.capture_button.isEnabled()
                    assert not window.account_tab.account_tab.read_feature_button.isEnabled()
                    original_show(window)
                with patch.object(DeviceManager, '__init__', side_effect=AssertionError('device constructed')), \\
                     patch.object(TaskExecutor, '__init__', side_effect=AssertionError('executor constructed')), \\
                     patch.object(ManagementWindow, 'show', verified_show):
                    assert manage(root / 'data', 'artifact-test') == 0
                assert not any(name.split('.')[0] in {'config','main','custom_ok'} for name in sys.modules)
            ''', source_root=payload, core_root=ROOT, stdin='{"command":"stop"}\n')
            self.assertIn('management-ready', output)

    def test_installed_plugin_management_root_configuration_shutdown_and_update_are_explicit(self):
        import shutil
        from scripts.build_native_gamepack import build_native_gamepack
        from gameframe.packages import install_archive
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            installed = install_archive(build_native_gamepack(temporary / 'native.zip'), temporary / 'installed')
            core_root = temporary / 'core'
            shutil.copytree(ROOT / 'gameframe', core_root / 'gameframe', ignore=shutil.ignore_patterns('__pycache__'))
            self.run_probe('''
                import importlib.abc
                import importlib.util
                import time
                import threading
                from contextlib import ExitStack
                from unittest.mock import patch
                from PySide6.QtWidgets import QApplication
                from PySide6.QtCore import QProcess
                class ForbidCheckout(importlib.abc.MetaPathFinder):
                    def find_spec(self, fullname, path=None, target=None):
                        if fullname.split('.')[0] in {'config','main','custom_ok'}:
                            raise ImportError('installed management imported ' + fullname)
                sys.meta_path.insert(0, ForbidCheckout())
                package_root = Path(sys.argv[1]).parent
                spec = importlib.util.spec_from_file_location('installed_plugin', package_root / 'plugin.py')
                plugin = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(plugin)
                package = plugin.create_package()
                command = package.management_command(root / 'data')
                assert command['command'][-2:] == ['--package-root', str(package_root)]
                assert str(Path(sys.argv[3])) in command['env']['PYTHONPATH']
                from src.management import AccountManagementService
                from src.gui.ManagementWindow import ManagementWindow
                from src.runtime import combat_api, diagnostic_lifecycle
                from ok.device.DeviceManager import DeviceManager
                from ok.task.TaskExecutor import TaskExecutor
                app = QApplication([])
                service = AccountManagementService(root / 'data', 'installed-management-test', package_root=package_root)
                source, preview = service.preview_first_account(display_name='A1', phone='19910000001',
                    nickname='配置载荷合成账号', sequence_ids=('序列1',))
                with patch('src.secure_backup.harden_directory_permissions', side_effect=lambda path: Path(path)):
                    service.create_first_account(source, preview, confirm=True)
                with ExitStack() as stack:
                    names = ('subprocess.Popen', 'src.runtime.diagnostic_policy.ensure_task',
                        'src.runtime.diagnostic_policy.connect', 'src.runtime.diagnostic_policy.save_credentials',
                        'src.runtime.diagnostic_lifecycle.start_diagnostics',
                        'src.runtime.diagnostic_archive.send_archive',
                        'src.update.native_gamepack_service.NativeGamePackUpdateService.check',
                        'src.update.native_gamepack_service.NativeGamePackUpdateService.download')
                    spies = [stack.enter_context(patch(name, side_effect=AssertionError(name))) for name in names]
                    stack.enter_context(patch.object(DeviceManager, '__init__', side_effect=AssertionError('created device')))
                    stack.enter_context(patch.object(TaskExecutor, '__init__', side_effect=AssertionError('created executor')))
                    window = ManagementWindow(service)
                    window.show()
                    assert window.tabs.count() == 7
                    assert window.update_tab.package_root == package_root
                    assert window.configuration_tab is not None
                    deadline = time.monotonic() + 10
                    while window.configuration_tab.schema is None and time.monotonic() < deadline:
                        app.processEvents()
                        if window.configuration_tab.process.state() == QProcess.NotRunning:
                            break
                        time.sleep(.01)
                    assert window.configuration_tab.schema is not None, window.configuration_tab.status.text()
                    assert len(window.configuration_tab.schema['tasks']) == 29
                    assert not combat_api.is_native()
                    assert diagnostic_lifecycle._session is None
                    with patch.object(window.configuration_tab, 'reload', wraps=window.configuration_tab.reload) as reload:
                        window.refresh()
                        window.configuration_tab.management_requested.emit()
                        reload.assert_not_called()
                    assert window.tabs.currentWidget() is window.account_tab
                    with patch.object(window.configuration_tab, 'reload', side_effect=RuntimeError('test reload stop timeout')):
                        window._done(None)
                        assert 'test reload stop timeout' in window.status.text()
                    # Refresh queues an account read in the reused evidence page.
                    # Drain it before exercising the explicit child-stop failure.
                    deadline = time.monotonic() + 10
                    while window._operations_busy() and time.monotonic() < deadline:
                        app.processEvents()
                        time.sleep(.01)
                    assert not window._operations_busy()
                    with patch.object(window.configuration_tab, 'shutdown', side_effect=RuntimeError('test configuration timeout')):
                        window.close()
                        assert window.isVisible()
                        assert 'test configuration timeout' in window.status.text()
                    marker = threading.Event()
                    window.update_tab.operation.start(lambda: marker.wait(2), lambda _: None, lambda error: None)
                    window.close()
                    assert window.isVisible()
                    assert window.configuration_tab.process.state() == QProcess.Running
                    marker.set()
                    while window._operations_busy() and time.monotonic() < deadline:
                        app.processEvents()
                        time.sleep(.01)
                    app.processEvents()
                    assert window.configuration_tab.process.state() == QProcess.NotRunning
                    assert not window.isVisible()
                    for spy in spies:
                        spy.assert_not_called()
                    window.evidence_service.close()
            ''', source_root=installed.root / 'payload', core_root=core_root)


if __name__ == '__main__':
    unittest.main()
