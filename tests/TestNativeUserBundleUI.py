"""Actual Qt bundle previews and JSONL configuration owner, without a device."""

import unittest


class TestNativeUserBundleUI(unittest.TestCase):
    def test_real_preview_import_group_export_asset_update_failure_and_delete(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        TestAccountManagementEntry().run_probe(r'''
            import json
            import time
            from unittest.mock import patch
            from src.management import AccountManagementService
            service = AccountManagementService(root / 'data', 'bundle-ui-test')
            source, account_preview = service.preview_first_account(display_name='A1', phone='19910000001',
                nickname='脚本包合成账号', sequence_ids=('序列1',))
            service.create_first_account(source, account_preview, confirm=True)
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog,
                                           QMessageBox, QPlainTextEdit)
            from src.gui.NativeConfigurationTab import NativeConfigurationTab
            from src.gui.NativeUserTaskTab import NativeUserTaskTab
            from src.runtime.native_user_tasks import NativeUserTaskStore
            from tests.TestNativeUserTaskBundles import TestNativeUserTaskBundles, SOURCE
            fixture = TestNativeUserTaskBundles()
            fixture.setUp()
            app = QApplication([])
            configuration = NativeConfigurationTab(root / 'data', 'bundle-ui-test',
                Path(sys.argv[1]) / 'gamepacks/wuthering_waves_native/manifest.json')
            editor = NativeUserTaskTab(configuration)
            editor.show()
            replies=[]
            configuration.response_received.connect(replies.append)
            def until(condition):
                deadline=time.monotonic()+15
                while not condition():
                    app.processEvents()
                    assert time.monotonic()<deadline, editor.status.text()+configuration.status.text()
                    time.sleep(.005)
            def settle():
                until(lambda: not editor.busy and not configuration._pending)
            def preview_import(path, *, accept=True):
                seen=[]; errors=[]
                timer=QTimer()
                def handle():
                    dialog=QApplication.activeModalWidget()
                    if not isinstance(dialog,QDialog) or dialog.windowTitle()!='脚本包导入预览':
                        return
                    timer.stop()
                    try:
                        editors=dialog.findChildren(QPlainTextEdit)
                        assert len(editors)==2 and all(item.isReadOnly() for item in editors)
                        manifest_text=editors[0].toPlainText()
                        assert '工具分组' in manifest_text and 'okww-native-user-bundle' in manifest_text
                        tasks=json.loads(editors[1].toPlainText())
                        assert len(tasks)==2 and tasks[0]['class_name']=='Example'
                        buttons=dialog.findChild(QDialogButtonBox)
                        assert buttons.button(QDialogButtonBox.Ok).isEnabled()
                        seen.append(tasks)
                        buttons.button(QDialogButtonBox.Ok if accept else QDialogButtonBox.Cancel).click()
                    except BaseException as error:
                        errors.append(error)
                        seen.append(None)
                        dialog.reject()
                timer.timeout.connect(handle)
                timer.start(5)
                try:
                    with patch.object(QFileDialog,'getOpenFileName',return_value=(str(path),'脚本包')):
                        editor.import_button.click()
                        until(lambda: bool(seen) and not editor.busy and not configuration._pending)
                    assert not errors, repr(errors)
                finally:
                    timer.stop()
            try:
                until(lambda: configuration.schema is not None)
                settle()
                store=NativeUserTaskStore(root/'data')
                archive=fixture.archive()
                original_bytes=archive.read_bytes()
                preview_import(archive,accept=False)
                assert store.list()==[], 'cancelled real preview published tasks'
                preview_import(archive)
                first=store.list()
                assert len(first)==2 and len(editor._rows)==2, editor.status.text()
                original_ids={row['id'] for row in first}
                assert original_ids <= {row['id'] for row in configuration.schema['tasks']}
                assert configuration.applied_revision==store.revision
                assert all('[工具分组]' in editor.sources.item(index).text() for index in range(2))
                editor.sources.setCurrentRow(0)
                settle()
                assert editor._bundle_id==first[0]['bundle_id']
                assert editor.code.isReadOnly() and editor.class_name.isReadOnly() and editor.capabilities.isReadOnly()
                assert not editor.save_button.isEnabled() and not editor.delete_button.isEnabled()
                assert editor.delete_bundle_button.isEnabled()
                assert '只读' in editor.status.text()
                assert all(row['group_name']=='工具分组' for row in configuration.schema['tasks'] if row['id'] in original_ids)
                config_path=root/'data/configs'/('user_'+first[0]['source_id']+'.json')
                assert config_path.is_file()
                exported=root/'ui-export.okscript'
                with patch.object(QFileDialog,'getSaveFileName',return_value=(str(exported),'脚本包')):
                    editor.export_button.click()
                    settle()
                assert exported.is_file() and '已导出' in editor.status.text()
                assert archive.read_bytes()==original_bytes
                preview_import(fixture.archive(pixel=100))
                updated=store.list()
                assert {row['id'] for row in updated}==original_ids
                assert first[0]['source_revision']==updated[0]['source_revision']
                assert first[0]['bundle_revision']!=updated[0]['bundle_revision']
                assert configuration.applied_revision==store.revision
                applied_before=configuration.applied_revision
                old_schema=configuration.schema
                broken=SOURCE+"    def on_create(self):\n        if self.executor.context.run_id != 'user-task-validation':\n            raise RuntimeError('UI owner candidate failure')\n"
                bad_archive=fixture.archive(sources={'One.py':broken,'Two.py':SOURCE.replace('Example','Another')})
                preview_import(bad_archive)
                failed=next(reply for reply in reversed(replies) if reply.get('command')=='user-bundle-import')
                assert not failed['ok'] and not failed['result']['applied']
                assert failed['result']['catalog_revision']==store.list_bundles()[0]['catalog_revision']
                assert failed['applied_revision']==applied_before==configuration.applied_revision
                assert configuration.schema==old_schema
                assert store.revision!=applied_before
                assert '已更新到磁盘' in editor.status.text() and '未应用' in editor.status.text()
                assert bad_archive.is_file()
                editor.refresh()
                settle()
                preview_import(fixture.archive(pixel=120))
                assert configuration.applied_revision==store.list_bundles()[0]['catalog_revision']
                editor.sources.setCurrentRow(-1)
                editor.sources.setCurrentRow(0)
                settle()
                with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):
                    editor.delete_bundle_button.click()
                    settle()
                assert store.list()==[] and editor._rows==[]
                assert config_path.is_file(), 'group deletion removed persisted task config'
                assert not original_ids & {row['id'] for row in configuration.schema['tasks']}
                assert not any(name=='ok' or name.startswith('ok.') for name in sys.modules)
            finally:
                configuration.shutdown()
                editor.close()
                fixture.doCleanups()
        ''')


if __name__ == '__main__':
    unittest.main()
