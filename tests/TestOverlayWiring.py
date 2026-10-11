"""Actual production executor/host and GUI dispatch, with synthetic read-only geometry."""
import json
import os
from types import SimpleNamespace
import unittest

class TestOverlayWiring(unittest.TestCase):
    def test_configuration_and_capture_failure_call_chain(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        body='''
import threading,numpy as np
from types import SimpleNamespace
from unittest.mock import patch
from tests.TestNativeWWOneTime import BlockApplicationImports
sys.meta_path.insert(0,BlockApplicationImports())
from tests.fixture_support import make_account_environment
data=root/'data';make_account_environment(data)
(data/'configs').mkdir(exist_ok=True)
(data/'configs/Language.json').write_text('{"Language":"en_US"}')
(data/'configs/Basic Options.json').write_text('{"Enable Blur":true,"Blur Algorithm":"Blur","Blur Interval":0}')
from src.runtime.native_configuration import create_configuration_host
manifest=Path(sys.argv[1])/'gamepacks/wuthering_waves_native/manifest.json'
events=[]
host=create_configuration_host(data,'overlay-test',manifest,events.append)
assert host.uid_overlay is None and host.context.device is None
assert host.program_preferences['Enable Blur'] is True
assert host.program_preferences['Blur Algorithm']=='Blur' and host.program_preferences['Blur Interval']==0
from src.runtime.native_metadata import TaskMetadata
schema=TaskMetadata(host).snapshot()
preferences=next(item for item in schema['globals'] if item['id']=='Program Preferences')
assert preferences['config_type']['Enable Blur']['sub_configs'][True]==['Blur Algorithm','Blur Interval']
assert preferences['config_type']['Blur Algorithm']['options']==['Blur','Inpaint']
assert preferences['config_type']['Blur Interval']['min']==0
from gameframe.api import TaskContext,Cancelled
image=np.zeros((1080,1920,3),dtype=np.uint8)
state={'owner':{'hwnd':123,'pid':456,'created':1.5},'x':-1920,'y':0,'width':1920,'height':1080,'dpi':144}
class Device:
 calls=0
 outcome=SimpleNamespace(image=image)
 def overlay_target(self):return state
 def next_frame(self,budget):
  self.calls+=1
  if isinstance(self.outcome,Exception):raise self.outcome
  return self.outcome
 def release_all(self):pass
device=Device()
def context_factory(*args,**kwargs):
 context=TaskContext(*args,**kwargs);context.device=device;return context
with patch('gameframe.api.TaskContext',side_effect=context_factory):
 host=create_configuration_host(data,'overlay-test',manifest,events.append)
assert host.uid_overlay is not None
executor=host.executor
host.task._enabled=True
assert executor.next_frame() is image
assert device.calls==1 and events[-1]['event']=='overlay-update'
from src.runtime.game_runtime_errors import FrameUnavailable
for outcome,error_type in [(OSError('capture fixture'),OSError),(None,FrameUnavailable)]:
 device.outcome=outcome
 try:executor.next_frame(time_out=0)
 except error_type:pass
 else:raise AssertionError('capture failure hidden')
 assert executor.nullable_frame() is None and executor._diagnostic_frame[0] is image
 assert events[-1]['event']=='overlay-clear'
 count=len(events);host.update_uid_overlay(executor.nullable_frame());assert len(events)==count
 device.outcome=SimpleNamespace(image=image);executor.next_frame()
executor.pause_event.set()
try:executor.check_enabled()
except executor.stop_exception:pass
else:raise AssertionError('pause ignored')
assert events[-1]['event']=='task-paused' and any(x['event']=='overlay-clear' for x in events[-2:])
executor.pause_event.clear()
with patch.object(host.uid_overlay,'poll',side_effect=ValueError('visual fixture')):
 assert executor.next_frame() is image
assert events[-1]['event']=='overlay-failed' and host.program_preferences['Enable Blur'] is True
original_observer=host.context.events
def failing_observer(event):
 original_observer(event)
 if event['event']=='overlay-update':raise OSError('event delivery fixture')
host.context.events=failing_observer
assert executor.next_frame() is image
assert events[-2]['event']=='overlay-clear' and events[-1]['event']=='overlay-failed'
assert host.uid_overlay.active is False
host.context.events=original_observer
assert device.calls==7
host.clear_uid_overlay()
assert not any(name.split('.')[0] in {'ok','PySide6','qfluentwidgets','onnxocr'} for name in sys.modules)
'''
        TestAccountManagementEntry().run_probe(body)

    def test_plugin_common_finally_for_all_execution_routes(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        TestAccountManagementEntry().run_probe('''
from unittest.mock import patch,Mock
from types import SimpleNamespace
import json,os
from tests.fixture_support import make_account_environment
data=root/'data';make_account_environment(data)
(data/'configs').mkdir(exist_ok=True)
(data/'configs/Language.json').write_text('{"Language":"en_US"}')
from src.runtime.native_configuration import create_configuration_host
manifest=Path(sys.argv[1])/'gamepacks/wuthering_waves_native/manifest.json'
host=create_configuration_host(data,'overlay-finally',manifest,lambda event:None)
from gameframe.packages import PackageManifest
package=PackageManifest.read(manifest.parent).load();package.engine=object()
original_events=host.context.events;original_cwd=Path.cwd()
clear=Mock(wraps=host.clear_uid_overlay);host.clear_uid_overlay=clear
closed=[]
hub=SimpleNamespace(close=lambda:closed.append(True))
for route,task_id in [('run_session',None),('run_service',next(item['id'] for item in package.manifest['tasks'] if item['kind']=='service')),('run_once','DailyTask')]:
 for failure in (False,True):
  outcome=Mock(side_effect=ValueError('execution fixture')) if failure else Mock(return_value={'status':'ok'})
  setattr(host,route,outcome)
  host.drain_desktop_notification=lambda:False
  with patch('src.runtime.native_combat_host.NativeCombatHost',return_value=host),patch('src.runtime.native_diagnostics.attach_native_executor'),patch('src.runtime.native_diagnostics.record_native_event'),patch('src.runtime.native_logging.configure_logging'),patch('src.runtime.native_desktop_notifications.create_owner_desktop_notifications',return_value=None),patch('src.runtime.native_notification_hub.NativeNotificationHub',return_value=hub):
   before=clear.call_count
   try:package._run(task_id,host.context,session=route=='run_session')
   except ValueError:
    assert failure
   else:assert not failure
   assert clear.call_count==before+1
   assert host.context.events is original_events and Path.cwd()==original_cwd
   assert package._notifications is None
  package._live_writer.close()
assert len(closed)==6
''')

    def test_gui_dispatch_lifecycle_consumes_patch_without_logging_it(self):
        os.environ['QT_QPA_PLATFORM']='offscreen'
        from gameframe import gui as module
        cls=module.GameFrameWindow
        clears=[];applied=[];errors=[]
        overlay=SimpleNamespace(clear=lambda:clears.append(True),apply_event=applied.append)
        obj=SimpleNamespace(_overlay=overlay,_closing=False,_stopping=False,_paused=False,
            _exit_requested=False,process=None,_live_response=lambda event:False,_notify=lambda event:None,
            pause_button=SimpleNamespace(setEnabled=lambda value:None),
            status_label=SimpleNamespace(setText=lambda value:None),
            _set_label=lambda *args:None,_error=errors.append)
        obj._clear_overlay=lambda:cls._clear_overlay(obj)
        obj._overlay_event=lambda event:cls._overlay_event(obj,event)
        update={'event':'overlay-update','patch':{'png':'private fixture'}}
        self.assertTrue(cls._pause_status(obj,json.dumps(update)))
        self.assertEqual(applied,[update])
        cls._pause_status(obj,'{"event":"task-paused","paused":true}')
        cls._pause_status(obj,'{"event":"finished","result":{}}')
        self.assertEqual(len(clears),2)
        obj._stopping=True
        self.assertTrue(cls._pause_status(obj,json.dumps(update)))
        self.assertEqual(len(applied),1)
        obj._stopping=False
        overlay.apply_event=lambda event:(_ for _ in ()).throw(ValueError('decode fixture'))
        self.assertTrue(cls._pause_status(obj,json.dumps(update)))
        self.assertEqual(len(errors),1)
        self.assertEqual(len(clears),3)
        obj._closing=True
        self.assertTrue(cls._pause_status(obj,json.dumps(update)))
        self.assertEqual(len(errors),1)

    def test_gui_worker_exit_stop_and_close_clear(self):
        from queue import Queue
        from unittest.mock import MagicMock,patch
        os.environ['QT_QPA_PLATFORM']='offscreen'
        from gameframe import gui as module
        cls=module.GameFrameWindow
        def window():
            obj=MagicMock()
            for field in ('_closing','_stopping','_managing','_updating','_starting','_installing',
                          '_configuration_querying','_overview_starting','_foreground_requested','_exit_requested'):
                setattr(obj,field,False)
            obj._events=Queue();obj._live_routes={};obj._account_context=None
            obj.managed_update_bindings.handle.return_value=False
            obj.task_list.currentRow.return_value=0
            obj._hotkey.poll.return_value=False
            obj._clear_overlay.side_effect=lambda:cls._clear_overlay(obj)
            return obj
        for code in (0,1,-9):
            obj=window();obj._events.put(('exit',code))
            cls._drain_events(obj)
            obj._overlay.clear.assert_called_once()
            self.assertIsNone(obj.process)
        obj=window()
        with patch.object(module.threading,'Thread'):
            cls.stop_selected(obj)
        obj._overlay.clear.assert_called_once()
        for tray in (False,True):
            obj=window();obj._force_close=False;obj._cleanup_done=not tray
            obj.close_to_tray.isChecked.return_value=tray
            event=MagicMock()
            with patch.object(module.QSystemTrayIcon,'isSystemTrayAvailable',return_value=True):
                cls.closeEvent(obj,event)
            obj._overlay.clear.assert_called_once()
            if tray:event.ignore.assert_called_once()
            else:event.accept.assert_called_once()

if __name__=='__main__':unittest.main()
