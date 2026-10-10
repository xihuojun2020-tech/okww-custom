"""Actual no-device configuration child and two native Qt character editors."""

import unittest
from pathlib import Path


class TestNativeCharacterUI(unittest.TestCase):
    def test_save_mode_reset_conflict_and_invalid_code_preserve_draft(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        TestAccountManagementEntry().run_probe('''
            import time
            from unittest.mock import patch
            from PySide6.QtCore import QProcess
            from PySide6.QtWidgets import QApplication, QMessageBox
            from src.management import AccountManagementService
            from src.gui.NativeConfigurationTab import NativeConfigurationTab
            from src.gui.NativeCharacterCodeTab import NativeCharacterCodeTab
            app = QApplication([])
            service = AccountManagementService(root / 'data', 'character-ui')
            source, preview = service.preview_first_account(display_name='A1', phone='19910000001',
                nickname='角色编辑合成账号', sequence_ids=('序列1',))
            service.create_first_account(source, preview, confirm=True)
            manifest = Path(sys.argv[1]) / 'gamepacks/wuthering_waves_native/manifest.json'
            configuration = NativeConfigurationTab(root / 'data', 'character-ui', manifest)
            first, second = NativeCharacterCodeTab(configuration), NativeCharacterCodeTab(configuration)
            def wait(predicate):
                deadline = time.monotonic() + 15
                while not predicate():
                    app.processEvents()
                    if time.monotonic() >= deadline:
                        raise AssertionError((configuration.status.text(), first.status.text(), second.status.text()))
                    time.sleep(.005)
            code = ('from src.char.Mortefi import Mortefi as Builtin\\n'
                    'class Mortefi(Builtin):\\n'
                    '    def do_perform(self): return "v1"\\n')
            try:
                wait(lambda: first._rows and second._rows and not first.busy and not second.busy)
                for tab in (first, second):
                    index = next(i for i, item in enumerate(tab._rows) if item['class_name']=='Mortefi')
                    tab.characters.setCurrentRow(index)
                    wait(lambda: tab._record is not None and not tab.busy)
                old_revision = second._revision
                first.mode.setCurrentIndex(1)
                assert not first.busy and not first._record['has_custom']
                assert not first.code.isReadOnly()
                first.code.setPlainText(code)
                assert first.code.extraSelections()
                first.save()
                wait(lambda: not first.busy)
                assert first._record['use_custom'] and first._record['custom_code']==code, first.status.text()
                assert configuration.applied_character_revision==first._revision
                second.refresh()
                wait(lambda: not second.busy)
                assert second._revision==old_revision
                second.mode.setCurrentIndex(1)
                second.code.setPlainText(code.replace('v1','v2'))
                second.save()
                wait(lambda: not second.busy)
                assert '操作失败' in second.status.text() and 'v2' in second.code.toPlainText()
                first.code.setPlainText('invalid syntax!')
                first.save()
                wait(lambda: not first.busy)
                assert first.code.toPlainText()=='invalid syntax!' and '操作失败' in first.status.text()
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                    first.mode.setCurrentIndex(0)
                    wait(lambda: not first.busy)
                    assert first.code.isReadOnly() and not first._record['use_custom']
                    assert first._record['has_custom']
                    first.mode.setCurrentIndex(1)
                    wait(lambda: not first.busy)
                    assert first.code.toPlainText()==code and not first.code.isReadOnly()
                    first.copy_prompt()
                    assert code in app.clipboard().text() and 'Mortefi' in app.clipboard().text()
                    first.reset()
                    wait(lambda: not first.busy)
                    assert not first._record['has_custom'] and not first._record['use_custom']
                    assert first.code.isReadOnly()
                assert not configuration._pending
            finally:
                configuration.shutdown()
            assert configuration.process.state()==QProcess.NotRunning
            print('native-character-ui-pass')
        ''', core_root=Path(__file__).resolve().parents[1])

    def test_draft_mode_and_failed_mode_request_restore_editor_state(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        TestAccountManagementEntry().run_probe('''
            from unittest.mock import patch
            from PySide6.QtCore import QObject, Signal
            from PySide6.QtWidgets import QApplication, QMessageBox
            from src.gui.NativeCharacterCodeTab import NativeCharacterCodeTab
            app=QApplication([])
            class Configuration(QObject):
                schema_changed=Signal(dict)
                response_received=Signal(dict)
                lifecycle_failed=Signal(str)
                applied_character_revision='old-owner'
                def __init__(self):
                    super().__init__(); self.calls=[]
                def request(self,command,**values):
                    self.calls.append((command,values)); return len(self.calls)
            configuration=Configuration()
            editor=NativeCharacterCodeTab(configuration)
            builtin='class Mortefi: pass'
            record=dict(class_name='Mortefi',display_name='Mortefi',saved_revision='original-token',
                builtin_code=builtin,custom_code=None,has_custom=False,use_custom=False)
            editor._loaded(record)
            editor.mode.setCurrentIndex(1)
            editor.code.setPlainText('unsaved draft')
            with patch.object(QMessageBox,'question',return_value=QMessageBox.No):
                editor.mode.setCurrentIndex(0)
            assert editor.mode.currentIndex()==1 and not editor.code.isReadOnly()
            assert editor.code.toPlainText()=='unsaved draft' and not configuration.calls
            editor.save()
            assert configuration.calls[-1][0]=='character-save'
            configuration.response_received.emit(dict(request_id=editor._request,command='character-save',
                ok=False,error=dict(message='invalid code')))
            assert editor.mode.currentIndex()==1 and editor.code.toPlainText()=='unsaved draft'
            assert editor._revision=='original-token'
            # A failed persisted mode change must not claim the mode succeeded.
            record.update(custom_code='saved custom',has_custom=True)
            editor._loaded(record)
            editor.mode.setCurrentIndex(1)
            configuration.response_received.emit(dict(request_id=editor._request,command='character-set-mode',
                ok=False,error=dict(message='stale editor')))
            assert editor.mode.currentIndex()==0 and editor.code.isReadOnly()
            assert editor.code.toPlainText()==builtin and editor._revision=='original-token'
            with patch.object(configuration,'request',return_value=None):
                editor.mode.setCurrentIndex(1)
            assert editor.mode.currentIndex()==0 and not editor.busy
            # Disk publication followed by owner failure is a saved result.
            editor.mode.setCurrentIndex(1)
            published={**record,'use_custom':True,'saved_revision':'new-saved','applied':False,
                'applied_character_revision':'old-owner'}
            configuration.response_received.emit(dict(request_id=editor._request,command='character-set-mode',
                ok=False,result=published,error=dict(message='owner rejected')))
            assert editor.mode.currentIndex()==1 and editor.code.toPlainText()=='saved custom'
            assert editor._revision=='new-saved' and '未应用' in editor.status.text()
            assert configuration.applied_character_revision=='old-owner'
        ''', core_root=Path(__file__).resolve().parents[1])


if __name__ == '__main__':
    unittest.main()
