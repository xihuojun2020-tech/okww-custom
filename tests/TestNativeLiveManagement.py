"""Live management routing with real Qt and stdin, without a device."""
import unittest


class TestNativeLiveManagement(unittest.TestCase):
    def test_management_evidence_uses_session_storage_authority(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        TestAccountManagementEntry().run_probe('''
            import json
            from PySide6.QtWidgets import QApplication
            from src.management import AccountManagementService
            from src.gui.ManagementWindow import ManagementWindow
            app = QApplication([])
            data = root / 'data'
            output_root = root / 'selected-output'
            output_root.mkdir()
            evidence_root = output_root / 'custom-evidence'
            (data / 'configs').mkdir(parents=True)
            (data / 'configs/runtime_storage.json').write_text(json.dumps({
                'root': str(output_root), 'paths': {'CompletionEvidence': str(evidence_root)}}),
                encoding='utf-8')
            service = AccountManagementService(data, 'evidence-authority-test')
            window = ManagementWindow(service)
            assert window.evidence_service.repository.root == evidence_root.resolve()
            assert not (data / 'okww监控室/CompletionEvidence').exists()
            assert service.root == data.resolve()
            window.close()
            window.evidence_service.close()
        ''')

    def test_stdin_routes_and_disconnects_pending_requests(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        TestAccountManagementEntry().run_probe('''
            import io, json, threading, time
            from types import SimpleNamespace
            from uuid import UUID
            from PySide6.QtCore import QObject, Signal
            from PySide6.QtWidgets import QApplication
            from src.native_management import NativeLiveBridge, read_management_commands
            app = QApplication([])
            messages = []
            bridge = NativeLiveBridge(emit=messages.append)
            class Stop(QObject):
                requested = Signal()
            stop = Stop()
            stopped = []
            stop.requested.connect(lambda: stopped.append(True))
            window = SimpleNamespace(live_bridge=bridge, stop_requested=stop.requested)
            first = bridge.request('inspect-account-feature')
            second = bridge.request('invoke-action', task_id='Task', action_id='Task/key/0')
            third = bridge.request('inspect-account-feature')
            assert str(UUID(first.request_id)) == first.request_id
            assert messages[0]['event'] == 'live-request'
            assert messages[1]['action_id'] == 'Task/key/0'
            stream = io.StringIO('\\n'.join(json.dumps(x) for x in [
                {'command':'live-response', 'response':{'event':'live-response',
                    'request_id':first.request_id,'ok':True,'result':{'code':'123'}}},
                {'command':'live-response', 'response':{'event':'configuration-response',
                    'request_id':second.request_id,'ok':False,
                    'error':{'type':'RuntimeError','message':'no live worker'}}},
                {'command':'stop'}])+'\\n')
            reader = threading.Thread(target=read_management_commands, args=(window,stream))
            reader.start(); reader.join()
            deadline = time.monotonic()+3
            while not stopped and time.monotonic()<deadline:
                app.processEvents(); time.sleep(.01)
            assert first.result() == {'code':'123'}
            for pending, expected in ((second,'no live worker'),(third,'管理窗口正在关闭')):
                try: pending.result()
                except RuntimeError as error: assert str(error)==expected
                else: raise AssertionError('failure was hidden')
            assert not bridge._pending
            assert bridge.request('inspect-account-feature').done()
        ''')

    def test_device_actions_use_live_bridge_only(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        TestAccountManagementEntry().run_probe('''
            import time
            from unittest.mock import patch
            from PySide6.QtWidgets import QApplication, QPushButton
            from src.native_management import NativeLiveBridge
            from src.gui.NativeConfigurationTab import NativeConfigurationTab
            app = QApplication([])
            messages = []
            bridge = NativeLiveBridge(emit=messages.append)
            manifest = Path(sys.argv[1]) / 'gamepacks/wuthering_waves_native/manifest.json'
            with patch.object(NativeConfigurationTab, '_start'):
                tab = NativeConfigurationTab(root/'data','live-test',manifest,live_bridge=bridge)
                app.processEvents()
            definitions = {'type':'button','buttons':[
                {'text':'Live','action_id':'Task/action/0','target':'owner','requires_device':True},
                {'text':'Local','action_id':'Task/action/1','target':'owner','requires_device':False}]}
            local = []
            tab.request = lambda command, **values: local.append((command, values))
            buttons = tab._widget('task','Task','action',None,None,definitions,{})
            live, plain = buttons.findChildren(QPushButton)
            assert live.isEnabled()
            live.click()
            assert messages[0]['command']=='invoke-action' and not local
            assert tab._pending == {messages[0]['request_id']}
            tab._fail_lifecycle('configuration child failed')
            assert tab._pending == {messages[0]['request_id']}
            bridge.receive({'request_id':messages[0]['request_id'],'ok':False,
                'error':{'message':'worker unavailable'}})
            deadline=time.monotonic()+3
            while tab._pending and time.monotonic()<deadline:
                app.processEvents();time.sleep(.01)
            assert not tab._pending and 'worker unavailable' in tab.status.text()
            plain.click()
            assert local == [('invoke-action',{'task_id':'Task','action_id':'Task/action/1'})]
            live.click()
            bridge.receive({'request_id':messages[-1]['request_id'],'ok':True,'schema':{'live':True}})
            app.processEvents()
            assert tab.schema is None and '已执行' in tab.status.text()
            tab.shutdown()
        ''')

    def test_feature_binding_keeps_confirmation_and_revision(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        TestAccountManagementEntry().run_probe('''
            import time
            from types import SimpleNamespace
            from unittest.mock import patch
            from PySide6.QtWidgets import QApplication, QWidget, QLabel, QMessageBox
            from src.native_management import NativeLiveBridge
            from src.gui.BackgroundOperation import BackgroundOperation
            from src.gui.AccountConfigTab import AccountConfigTab
            app=QApplication([])
            widget=QWidget()
            messages=[]; transactions=[]; previews=[]
            bridge=NativeLiveBridge(emit=messages.append)
            draft=SimpleNamespace(profile_id='profile-1',revision='revision-1',
                account={'display_name':'A1','masked_phone':'199****0001'})
            service=SimpleNamespace(preview=lambda *args:previews.append(args),
                rebind=lambda *args,**values:transactions.append((args,values)))
            tab=SimpleNamespace(operation=BackgroundOperation(widget),draft=draft,
                status=QLabel(widget),view=widget,rebind_service=service,native_live_bridge=bridge)
            tab._submit_action=lambda action,*args,**values:action()
            def finish(code='123'):
                bridge.receive({'request_id':messages[-1]['request_id'],'ok':True,'result':{'code':code}})
                deadline=time.monotonic()+3
                while tab.operation.busy and time.monotonic()<deadline:
                    app.processEvents();time.sleep(.01)
                assert not tab.operation.busy
            with patch.object(QMessageBox,'question',return_value=QMessageBox.No) as confirm:
                AccountConfigTab.read_feature_code(tab);finish()
                assert confirm.called and not transactions
            with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):
                AccountConfigTab.read_feature_code(tab);finish()
            assert transactions[0][1]['expected_revision']=='revision-1'
            assert transactions[0][1]['confirmed'] is True
            assert transactions[0][1]['new_identity']=={'game_feature_code':'123'}
            with patch.object(QMessageBox,'question') as confirm:
                AccountConfigTab.read_feature_code(tab)
                tab.draft=SimpleNamespace(profile_id='profile-1',revision='revision-2',account=draft.account)
                finish()
                assert not confirm.called and len(transactions)==1
            AccountConfigTab.read_feature_code(tab)
            bridge.receive({'request_id':messages[-1]['request_id'],'ok':False,
                'error':{'message':'no live worker'}})
            deadline=time.monotonic()+3
            while tab.operation.busy and time.monotonic()<deadline:
                app.processEvents();time.sleep(.01)
            assert 'no live worker' in tab.status.text() and len(transactions)==1
        ''')


if __name__ == '__main__':
    unittest.main()
