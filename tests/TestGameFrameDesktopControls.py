"""Native launcher controls use one existing owner, with no desktop input."""

import json
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class TestGameFrameDesktopControls(unittest.TestCase):
    def setUp(self):
        from tests.TestGameFrameLauncher import TestGameFrameLauncher
        TestGameFrameLauncher.setUpClass()
        self.fixture = TestGameFrameLauncher()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.window = self.fixture.window
        index = next(index for index, manifest in enumerate(self.window.packages) if manifest.id == 'native')
        self.window.package_select.setCurrentIndex(index)

    def test_device_fields_advanced_json_and_capability_refusal(self):
        window = self.window
        task = window._visible_tasks[0]
        window._visible_tasks = (replace(task, required_capabilities=frozenset({'frames', 'keyboard', 'mouse'})),)
        value = {'type': 'mumu', 'install_dir': 'C:/MuMu', 'instance_index': 2,
                 'dll_path': 'C:/MuMu/nemu.dll', 'custom': 'preserved'}
        window.device_edit.setPlainText(json.dumps(value))
        self.assertEqual(window.device_editor.options()['custom'], 'preserved')
        self.assertIn('keyboard', window.compatibility_label.text())
        window.start_selected()
        self.assertEqual(self.fixture.controller.starts, [])
        window.device_edit.setPlainText('{"type":"unsupported"}')
        with self.assertRaises(ValueError):
            window._native_options()
        self.assertIn('设备缺少', window.status_label.text())
        window.device_editor.set_options({'type': 'windows', 'hwnd': 123})
        window._device_fields_changed(window.device_editor.options())
        self.assertEqual(json.loads(window.device_edit.toPlainText())['hwnd'], 123)
        self.assertIn('匹配', window.compatibility_label.text())
        window.device_editor.fields['windows']['hwnd'].setText('unfinished')
        window.start_selected()
        self.assertEqual(self.fixture.controller.starts, [])

    def test_actual_controller_jsonl_management_worker_roundtrip(self):
        import os
        import sys
        import threading
        from gameframe.controller import Controller
        window = self.window
        controller = Controller()
        manager = Controller()
        window.controller = controller
        window.management_controller = manager
        worker_code = '''import sys,json
for line in sys.stdin:
    request=json.loads(line)
    if request['command']=='stop': break
    print(json.dumps({'event':'live-response','request_id':request['request_id'],
        'ok':True,'result':{'code':'001234','evidence':{}}}),flush=True)
'''
        management_code = '''import sys,json
print(json.dumps({'event':'live-request','command':'inspect-account-feature','request_id':'real-pipe'}),flush=True)
for line in sys.stdin:
    request=json.loads(line)
    if request['command']=='stop': break
    response=request['response']
    assert response['request_id']=='real-pipe' and response['ok'] and response['result']['code']=='001234'
    print('management-roundtrip-passed',flush=True)
'''
        worker = controller._launch([sys.executable,'-u','-c',worker_code], str(Path.cwd()),
                                    dict(os.environ), 'native', True)
        managed = manager._launch([sys.executable,'-u','-c',management_code], str(Path.cwd()),
                                 dict(os.environ), 'management', False)
        window.process = worker
        window._managing = True
        window._reader = threading.Thread(target=window._read_output,args=(worker,),daemon=True)
        window._reader.start()
        window._events.put(('management-started',managed))
        self.addCleanup(controller.close)
        self.addCleanup(manager.close)
        self.fixture._until(lambda: 'management-roundtrip-passed' in window.output.toPlainText())
        self.assertNotIn('001234',window.output.toPlainText())
        self.assertNotIn('real-pipe',window.output.toPlainText())
        self.assertEqual(window._live_routes,{})

    def test_hotkey_transition_pause_and_resume_after_confirmation(self):
        window = self.window
        controller = self.fixture.controller
        controller.session = True
        window.process = SimpleNamespace(poll=lambda: None)
        self.addCleanup(setattr, window, 'process', None)
        pressed = [False]
        window._hotkey.reader = lambda key: pressed[0]
        window.pause_hotkey.setCurrentText('F9')
        window.pause_button.setEnabled(True)
        pressed[0] = True
        window._drain_events()
        window._drain_events()
        self.assertEqual(controller.controls, ['pause'])
        window._pause_status(json.dumps({'event': 'task-paused', 'paused': True}))
        window._drain_events()
        self.assertEqual(controller.controls, ['pause'])
        pressed[0] = False
        window._drain_events()
        pressed[0] = True
        window._drain_events()
        self.assertEqual(controller.controls, ['pause', 'resume'])
        window._pause_status(json.dumps({'event': 'task-paused', 'paused': False}))
        self.assertFalse(window._paused)
        self.assertEqual(window.pause_button.text(), 'Pause')

    def test_live_bridge_private_response_owner_exit_and_unavailable(self):
        window = self.window
        calls, replies = [], []
        window.management_controller.deliver_live_response = replies.append
        window.controller.request_live = lambda command, request_id, **values: calls.append((command, request_id, values))
        request = {'event': 'live-request', 'request_id': 'management-1', 'command': 'inspect-account-feature'}
        window._events.put(('management-line', json.dumps(request)))
        window._drain_events()
        self.assertEqual(calls[0][:2], ('inspect-account-feature', 'management-1'))
        response = {'event': 'live-response', 'request_id': 'management-1', 'ok': True,
                    'result': {'code': '001234', 'evidence': {}}}
        window._events.put(('line', json.dumps(response)))
        window._drain_events()
        self.assertEqual(replies, [response])
        self.assertNotIn('001234', window.output.toPlainText())
        self.assertNotIn('live-request', window.output.toPlainText())
        window._events.put(('management-line', json.dumps({**request, 'request_id': 'management-2'})))
        window._events.put(('exit', 0))
        window._drain_events()
        self.assertFalse(replies[-1]['ok'])
        self.assertEqual(replies[-1]['request_id'], 'management-2')
        window.controller.request_live = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('no owner'))
        window._management_live_request(json.dumps({**request, 'request_id': 'management-3'}))
        self.assertEqual(replies[-1]['error']['message'], 'no owner')

    def test_preferences_disabled_values_notifications_and_conflict(self):
        from gameframe.desktop_controls import desktop_preferences
        from PySide6.QtWidgets import QSystemTrayIcon
        window = self.window
        data = window.data_dir / window._manifest().id
        (data / 'configs').mkdir(parents=True)
        (data / 'configs/Basic Options.json').write_text(json.dumps({'Start/Stop': 'F10',
            'Minimize Window to System Tray when Closing': False}))
        (data / 'configs/Notification.json').write_text(json.dumps({'System Notification': False}))
        self.assertEqual(desktop_preferences(data, {})['pause_hotkey'], 'F10')
        self.assertFalse(desktop_preferences(data, {})['tray_notifications'])
        window.pause_hotkey.setCurrentText('F9')
        window._reserved_hotkeys = ['f9']
        window._hotkey_conflict()
        self.assertEqual(window._hotkey.key, 'None')
        self.assertIn('冲突', window.pause_hotkey.toolTip())
        window.tray_notifications.setChecked(True)
        with patch.object(QSystemTrayIcon, 'isSystemTrayAvailable', return_value=True), \
                patch.object(window.tray, 'showMessage') as show:
            window._pause_status(json.dumps({'event': 'task-log', 'notify': True,
                                            'level': 'error', 'message': '失败证据'}))
            self.assertEqual(show.call_count, 1)
            window.tray_notifications.setChecked(False)
            window._pause_status(json.dumps({'event': 'combat-notification', 'message': '仅应用内'}))
            self.assertEqual(show.call_count, 1)
        self.assertIn('仅应用内', window.notification_label.text())


if __name__ == '__main__':
    unittest.main()
