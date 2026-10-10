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
    def run_probe(self, body, *, stdin=None, source_root=ROOT):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'management_probe.py'
            script.write_text('import sys\nfrom pathlib import Path\nsys.path.insert(0, sys.argv[1])\n'
                              'root = Path(sys.argv[2])\n' + textwrap.dedent(body), encoding='utf-8')
            environment = dict(os.environ, QT_QPA_PLATFORM='offscreen')
            result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(script), str(source_root), directory],
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
                assert window.tabs.count() == 2
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
                    assert window.tabs.count() == 2
                    assert not window.evidence_tab.capture_button.isEnabled()
                    assert not window.account_tab.account_tab.read_feature_button.isEnabled()
                    original_show(window)
                with patch.object(DeviceManager, '__init__', side_effect=AssertionError('device constructed')), \\
                     patch.object(TaskExecutor, '__init__', side_effect=AssertionError('executor constructed')), \\
                     patch.object(ManagementWindow, 'show', verified_show):
                    assert manage(root / 'data', 'artifact-test') == 0
                assert not any(name.split('.')[0] in {'config','main','custom_ok'} for name in sys.modules)
            ''', source_root=payload, stdin='{"command":"stop"}\n')
            self.assertIn('management-ready', output)


if __name__ == '__main__':
    unittest.main()
