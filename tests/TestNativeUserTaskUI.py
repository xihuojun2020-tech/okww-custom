"""Real Qt editor/configuration child publishes scripts without a game device."""

import unittest
from pathlib import Path


class TestNativeUserTaskUI(unittest.TestCase):
    def test_editor_save_rename_conflict_invalid_code_and_delete(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        TestAccountManagementEntry().run_probe('''
            import time
            from src.management import AccountManagementService
            service = AccountManagementService(root / 'data', 'user-task-ui-test')
            source, preview = service.preview_first_account(display_name='A1', phone='19910000001',
                nickname='用户任务合成账号', sequence_ids=('序列1',))
            service.create_first_account(source, preview, confirm=True)
            from PySide6.QtWidgets import QApplication, QMessageBox
            from unittest.mock import patch
            from src.gui.NativeConfigurationTab import NativeConfigurationTab
            from src.gui.NativeUserTaskTab import NativeUserTaskTab
            from src.runtime.native_user_tasks import NativeUserTaskStore
            app = QApplication([])
            configuration = NativeConfigurationTab(root / 'data', 'user-task-ui-test',
                Path(sys.argv[1]) / 'gamepacks/wuthering_waves_native/manifest.json')
            editor = NativeUserTaskTab(configuration)
            editor.show()
            def until(condition):
                deadline = time.monotonic() + 15
                while not condition():
                    app.processEvents()
                    if time.monotonic() > deadline:
                        raise AssertionError(editor.status.text() + configuration.status.text())
                    time.sleep(.005)
            def settle():
                until(lambda: not editor.busy and not configuration._pending)
            until(lambda: configuration.schema is not None)
            settle()
            assert not editor._rows
            editor.save()
            settle()
            identity = editor._source_id
            assert identity is not None and len(editor._rows) == 1, editor.status.text()
            store = NativeUserTaskStore(root / 'data')
            first = store.read(identity)
            assert first['id'] in {row['id'] for row in configuration.schema['tasks']}
            filename = root / 'data/configs' / ('user_' + identity + '.json')
            assert filename.is_file()
            editor.class_name.setText('RenamedTask')
            editor.code.setPlainText(first['code'].replace('UserTask', 'RenamedTask'))
            editor.save()
            settle()
            renamed = store.read(identity)
            assert renamed['id'] == first['id'] and renamed['class_name'] == 'RenamedTask'
            assert filename.is_file()
            editor.code.setPlainText('this is invalid Python!')
            editor.save()
            settle()
            assert store.read(identity)['catalog_revision'] == renamed['catalog_revision']
            assert '操作失败' in editor.status.text()
            editor.code.setPlainText(renamed['code'])
            editor._remember()
            external = store.save(renamed['code'].replace('我的任务', '外部修改'), 'RenamedTask',
                source_id=identity, expected_revision=renamed['catalog_revision'],
                required_capabilities=renamed['required_capabilities'])
            old_revision = editor._catalog_revision
            editor.refresh()
            settle()
            assert editor._catalog_revision == old_revision, 'list refresh silently accepted stale code'
            editor.save()
            settle()
            assert '其他编辑' in editor.status.text()
            assert store.read(identity)['catalog_revision'] == external['catalog_revision']
            editor.sources.setCurrentRow(-1)
            editor.sources.setCurrentRow(0)
            settle()
            assert editor._catalog_revision == external['catalog_revision']
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                editor.delete()
                settle()
            assert store.list() == [] and filename.is_file()
            assert first['id'] not in {row['id'] for row in configuration.schema['tasks']}
            configuration.shutdown()
            editor.close()
            assert not any(name == 'ok' or name.startswith('ok.') for name in sys.modules)
        ''')

    def test_saved_revision_survives_owner_apply_failure(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from src.runtime.native_configuration import ConfigurationService
        host = SimpleNamespace(context=SimpleNamespace(data_dir=Path('.')),
            applied_revision='old-running', applied_character_revision='old-characters',
            reload_user_tasks=lambda: (_ for _ in ()).throw(
                ValueError('owner candidate failed')))
        service = ConfigurationService(host)
        result = {'catalog_revision': 'new-saved', 'source_id': 'source'}
        with patch('src.runtime.native_user_tasks.NativeUserTaskStore') as store:
            store.return_value.save.return_value = result
            response = service.request({'command':'user-task-save', 'code':'code',
                'class_name':'UserTask', 'required_capabilities':[]})
        self.assertFalse(response['ok'])
        self.assertEqual(response['result']['catalog_revision'], 'new-saved')
        self.assertFalse(response['result']['applied'])
        self.assertEqual(response['result']['applied_revision'], 'old-running')
        self.assertEqual(response['applied_revision'], 'old-running')

    def test_configuration_pending_blocks_maintenance_and_close(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        TestAccountManagementEntry().run_probe('''
            import time
            from src.management import AccountManagementService
            service = AccountManagementService(root / 'data', 'pending-ui-test',
                package_root=Path(sys.argv[1]) / 'gamepacks/wuthering_waves_native')
            source, preview = service.preview_first_account(display_name='A1', phone='19910000001',
                nickname='合成账号', sequence_ids=('序列1',))
            service.create_first_account(source, preview, confirm=True)
            from PySide6.QtWidgets import QApplication
            from src.gui.ManagementWindow import ManagementWindow
            app=QApplication([])
            window=ManagementWindow(service)
            window.show()
            deadline=time.monotonic()+15
            while window.configuration_tab.schema is None or window._operations_busy():
                app.processEvents()
                assert time.monotonic()<deadline, window.status.text()
                time.sleep(.005)
            configuration=window.configuration_tab
            configuration._pending.add(999)
            completed=[]; errors=[]
            window._maintain(lambda: completed.append('ran'), completed.append, errors.append, False)
            assert not completed and '已有操作' in str(errors[-1])
            window.close()
            assert window.isVisible() and window._closing and not window.tabs.isEnabled()
            configuration._pending.clear()
            configuration.busy_changed.emit(False)
            assert not window.isVisible()
            assert configuration.request('get-schema') is None
            assert not configuration._pending
        ''')


if __name__ == '__main__':
    unittest.main()
