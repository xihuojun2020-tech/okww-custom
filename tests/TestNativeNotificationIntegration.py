"""Production notification wiring with synthetic accounts and fake transports."""
import unittest


class TestNativeNotificationIntegration(unittest.TestCase):
    def probe(self, body, *, stdin=None):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        return TestAccountManagementEntry().run_probe(body, stdin=stdin)

    def test_configuration_child_hides_secrets_saves_and_clears_without_models_or_http(self):
        output = self.probe('''
            import importlib.abc,json
            class Forbidden(importlib.abc.MetaPathFinder):
                def find_spec(self,fullname,path=None,target=None):
                    if fullname.split('.')[0] in {'ok','PySide6','qfluentwidgets','onnxocr','requests','httpx'}:
                        raise ImportError('forbidden configuration import: '+fullname)
            sys.meta_path.insert(0,Forbidden())
            from tests.fixture_support import make_account_environment
            data=root/'data';make_account_environment(data)
            (data/'configs').mkdir(exist_ok=True)
            (data/'configs/Language.json').write_text('{"Language":"en_US"}')
            from src.runtime.native_configuration import main
            manifest=Path(sys.argv[1])/'gamepacks/wuthering_waves_native/manifest.json'
            assert main(['--data-dir',str(data),'--version','notification-test','--manifest',str(manifest)])==0
            stored=json.loads((data/'configs/Native Notifications.json').read_text(encoding='utf-8'))
            assert stored['Discord Webhook']=='' and stored['Telegram Bot Token']=='fixture-secret-token'
            assert not (data/'runs.sqlite').exists()
            assert not any(name.split('.')[0] in {'ok','PySide6','qfluentwidgets','onnxocr','requests','httpx'}
                           for name in sys.modules)
        ''', stdin='\n'.join([
            '{"command":"set-config","scope":"global","id":"Native Notifications","values":{"Discord Webhook":"https://discord.test/fixture-secret-webhook","Telegram Bot Token":"fixture-secret-token"}}',
            '{"command":"get-schema"}',
            '{"command":"set-config","scope":"global","id":"Native Notifications","values":{"Discord Webhook":""}}'])+'\n')
        import json
        replies = [json.loads(line) for line in output.splitlines() if line.startswith('{')]
        replies = [item for item in replies if item.get('event')=='configuration-response']
        self.assertEqual(len(replies), 3)
        self.assertTrue(all(item['ok'] for item in replies), output)
        self.assertNotIn('fixture-secret', output)
        for index, reply in enumerate(replies):
            self.assertEqual(len(reply['schema']['globals']), 6)
            value = next(item for item in reply['schema']['globals'] if item['id']=='Native Notifications')
            self.assertEqual(value['current_config']['Discord Webhook'], '')
            self.assertEqual(value['current_config']['Telegram Bot Token'], '')
            self.assertEqual(value['config_type']['Discord Webhook']['configured'], index<2)
            self.assertTrue(value['config_type']['Telegram Bot Token']['configured'])

    def test_production_notification_and_notify_log_deliver_once_mask_copy_and_plugin_close(self):
        self.probe('''
            import json,threading,cv2,numpy as np
            from types import SimpleNamespace
            from tests.TestNativeWWOneTime import BlockApplicationImports
            sys.meta_path.insert(0,BlockApplicationImports())
            from tests.fixture_support import make_account_environment
            data=root/'data';make_account_environment(data)
            (data/'configs').mkdir(exist_ok=True)
            (data/'configs/Language.json').write_text('{"Language":"en_US"}')
            from src.runtime.native_configuration import create_configuration_host
            manifest=Path(sys.argv[1])/'gamepacks/wuthering_waves_native/manifest.json'
            events=[]
            host=create_configuration_host(data,'notification-test',manifest,events.append)
            from src.runtime.native_notifications import NativeNotifications,DEFAULTS
            from src.runtime.native_notification_hub import NativeNotificationHub
            calls=[];completed=threading.Event()
            def transport(url,**kwargs):
                calls.append(kwargs)
                return SimpleNamespace(status_code=204)
            def observe(event):
                events.append(event)
                if event['event']=='notification-delivery' and len([x for x in events if x['event']=='notification-delivery'])==2:
                    completed.set()
            host.context.events=observe
            http=NativeNotifications(dict(DEFAULTS,**{'Discord Notification':True,
                'Discord Webhook':'https://discord.test/synthetic-secret'}),transport=transport)
            hub=NativeNotificationHub(host.context,http);host.notifications=hub
            frame=np.full((1080,1920,3),201,np.uint8);original=frame.copy()
            task=host.task
            task.notification('fixture notification',images=[frame])
            task.log_info('fixture log',notify=True,images=[frame])
            assert completed.wait(5),'notification completion not observed'
            assert len(calls)==2,calls
            from src.runtime.account_task_support import native_blur_area
            box=native_blur_area(1920,1080)
            for call in calls:
                assert len(call['files'])==1
                png=call['files'][0][1][1]
                image=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_COLOR)
                assert not image[box.y:box.y+box.height,box.x:box.x+box.width].any()
                assert image[0,0].tolist()==[201,201,201]
            assert np.array_equal(frame,original),'notification mutated source frame'
            deliveries=[x for x in events if x['event']=='notification-delivery']
            assert len(deliveries)==2 and all(x['results'][0]['status']=='delivered' for x in deliveries)
            from gameframe.packages import PackageManifest
            plugin=PackageManifest.read(manifest.parent).load()
            plugin._notifications=hub
            plugin.close()
            assert plugin._notifications is None
            assert not any(thread.is_alive() for thread in http._executor._threads)
            try:http.submit('closed','closed')
            except RuntimeError:pass
            else:raise AssertionError('closed notification executor accepted work')
        ''')

    def test_missing_credentials_reports_failure_without_transport_or_secret_echo(self):
        self.probe('''
            import threading,json
            from types import SimpleNamespace
            from gameframe.api import TaskContext
            from src.runtime.native_notifications import NativeNotifications,DEFAULTS
            from src.runtime.native_notification_hub import NativeNotificationHub
            from unittest.mock import Mock
            calls=[];events=[];completed=threading.Event()
            def observe(event):events.append(event);completed.set()
            context=TaskContext(None,{},root,threading.Event(),'notification-test',observe)
            http=NativeNotifications(dict(DEFAULTS,**{'Telegram Notification':True}),
                transport=lambda *args,**kwargs:calls.append(True))
            hub=NativeNotificationHub(context,http)
            try:
                hub.notify('fixture','missing credentials')
                assert completed.wait(5)
                assert not calls
                assert events[0]['results']==[{'route':'telegram','status':'failed','failure':'configuration','completed_requests':0}],events
            finally:hub.close()
        ''')

    def test_secret_qt_save_and_clear_are_explicit_and_never_show_existing_value(self):
        self.probe('''
            from PySide6.QtWidgets import QApplication,QLineEdit,QPushButton
            from unittest.mock import patch
            from src.gui.NativeConfigurationTab import NativeConfigurationTab
            app=QApplication([])
            manifest=Path(sys.argv[1])/'gamepacks/wuthering_waves_native/manifest.json'
            with patch.object(NativeConfigurationTab,'_start'):
                tab=NativeConfigurationTab(root/'data','notification-test',manifest)
                calls=[];tab._set=lambda *args:calls.append(args)
                body=tab._widget('global','Native Notifications','Discord Webhook','', '',
                                 {'secret':True,'configured':True},{})
                field=body.findChild(QLineEdit)
                assert field.echoMode()==QLineEdit.Password and field.text()==''
                assert field.placeholderText()
                apply,clear=body.findChildren(QPushButton)
                apply.click();field.editingFinished.emit()
                assert not calls,'blank edit unexpectedly cleared saved secret'
                field.setText('new-fixture-secret');field.editingFinished.emit()
                assert not calls,'secret edit auto-saved'
                apply.click()
                assert calls[-1]==('global','Native Notifications','Discord Webhook','new-fixture-secret')
                clear.click()
                assert calls[-1]==('global','Native Notifications','Discord Webhook','')
                tab.shutdown();body.deleteLater();tab.deleteLater();app.processEvents()
        ''')

    def test_diagnostic_sanitization_redacts_old_and_native_notification_destinations(self):
        self.probe('''
            import json
            from src.runtime.diagnostic_export import sanitize_data,sanitize_file
            values={key:'synthetic-private-'+str(index) for index,key in enumerate([
                'Discord Webhook','Telegram Bot Token','Enterprise WeChat Webhook URL',
                'QQ Bot API Token','Telegram Chat ID','QQ Bot API Channel ID',
                'QQ Desktop Nickname','WeChat Desktop Nickname','QQ Nickname','WeChat Nickname'])}
            cleaned=sanitize_data({'Notification':values,'Native Notifications':values})
            for section in cleaned.values():
                for key in values:assert section[key]=='[REDACTED]',(key,section[key])
            for name in ('Notification.json','Native Notifications.json'):
                path=root/name;path.write_text(json.dumps(values),encoding='utf-8')
                prepared=json.loads(sanitize_file(path))
                assert all(value=='[REDACTED]' for value in prepared.values()),prepared
        ''')

    def test_queued_http_keeps_destination_at_submission(self):
        self.probe('''
            import threading
            from types import SimpleNamespace
            from src.runtime.native_notifications import NativeNotifications,DEFAULTS
            entered=threading.Event();release=threading.Event();calls=[]
            def transport(url,**kwargs):
                calls.append(url)
                if len(calls)==1:
                    entered.set()
                    assert release.wait(5),'fixture release missing'
                return SimpleNamespace(status_code=204)
            config=dict(DEFAULTS,**{'Discord Notification':True,'Discord Webhook':'https://discord.test/old-fixture'})
            http=NativeNotifications(config,transport=transport)
            try:
                first=http.submit('first','first')
                assert entered.wait(5)
                second=http.submit('second','second')
                config['Discord Webhook']='https://discord.test/new-fixture'
                release.set()
                assert first.result(timeout=5)[0]['status']=='delivered'
                assert second.result(timeout=5)[0]['status']=='delivered'
                assert calls==['https://discord.test/old-fixture']*2,calls
            finally:release.set();http.close()
        ''')
