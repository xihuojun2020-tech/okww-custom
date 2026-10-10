"""Owner-bound live capture at real native session boundaries, Replay only."""
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestNativeLiveInspection(unittest.TestCase):
    def probe(self, body):
        with tempfile.TemporaryDirectory() as directory:
            prelude = '''
                import sys, threading, json
                from pathlib import Path
                import cv2, numpy as np
                sys.path.insert(0, ROOT)
                from src.runtime import combat_api
                combat_api.configure(native=True,data_dir=DATA)
                from gameframe.api import TaskContext, Cancelled
                from gameframe.devices.replay import ReplayDevice
                from src.combat.settings import COMBAT_GLOBAL_DEFAULTS,TEMPLATE_MATCHING_DEFAULTS
                from src.runtime.native_combat_host import NativeCombatHost
                data=Path(DATA)
                def host_for(context, **options):
                    return NativeCombatHost(context,coco_path=Path(ROOT)/'assets/coco_annotations.json',
                        global_options=COMBAT_GLOBAL_DEFAULTS,ocr_engine=options.pop('ocr_engine',None),
                        template_matching=TEMPLATE_MATCHING_DEFAULTS,**options)
            '''
            script = (textwrap.dedent(prelude) + textwrap.dedent(body) +
                      "\nassert not any(name.split('.')[0] in ('ok','PySide6','qfluentwidgets') for name in sys.modules)\n")
            script = script.replace('ROOT',repr(str(ROOT))).replace('DATA',repr(directory))
            result = subprocess.run([sys.executable,'-I','-B','-X','utf8','-c',script],
                                    capture_output=True,text=True,encoding='utf-8',timeout=20)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_paused_capture_ocr_stable_feature_and_live_configuration(self):
        self.probe('''
            frames=[]
            for index in range(4):
                image=np.full((90,160,3),20+index,dtype=np.uint8)
                path=data/('frame-'+str(index)+'.png'); cv2.imwrite(str(path),image); frames.append(path)
            selected=data/'selected-storage'; selected.mkdir()
            (data/'configs').mkdir()
            (data/'configs/runtime_storage.json').write_text(json.dumps({'root':str(selected),
                'paths':{'screenshots':str(selected/'shots')}}))
            class Engine:
                def ocr(self,image):
                    return [[([[1,2],[45,2],[45,12],[1,12]],('特征码001234',.99))]]
            device=ReplayDevice(frames); stop=threading.Event(); pause=threading.Event(); pause.set()
            events=[]
            def receive(event):
                events.append(event)
                if event.get('request_id')=='schema': stop.set()
            context=TaskContext(device,{},data,stop,'inspect',receive,pause)
            host=host_for(context,ocr_engine=Engine(),ocr_config={'default':{'lib':'onnxocr'}})
            revision=host.applied_character_revision
            context.requests.put({'command':'inspect-frame','request_id':'frame','ocr':True})
            context.requests.put({'command':'inspect-account-feature','request_id':'feature'})
            context.requests.put({'command':'set-config','request_id':'config','scope':'global',
                'id':'Monthly Card Config','values':{'Check Monthly Card':False}})
            context.requests.put({'command':'get-schema','request_id':'schema'})
            try: host.run_session('auto-combat')
            except Cancelled: pass
            else: raise AssertionError('session did not stop')
            frame=next(event for event in events if event.get('request_id')=='frame')
            assert frame['event']=='live-response' and frame['ok'],frame
            result=frame['result']; path=Path(result['path'])
            assert path.parent==selected/'shots' and path.is_file()
            assert result['masked'] and result['sequence']==1 and result['captured_ns']>0
            assert result['timestamp_source']=='replay-host-read'
            assert result['text']=='特征码001234' and result['ocr_rows'][0]['width']==44
            from src.runtime.native_screenshots import masked_native_frame
            assert np.array_equal(cv2.imread(str(path)),masked_native_frame(cv2.imread(str(frames[0]))))
            feature=next(event for event in events if event.get('request_id')=='feature')
            assert feature['ok'] and feature['result']['code']=='001234',feature
            assert len(set(feature['result']['evidence']['frame_hashes']))==3
            assert feature['result']['evidence']['resolution']==[160,90]
            assert all(next(event for event in events if event.get('request_id')==key)['ok'] for key in ('config','schema'))
            assert pause.is_set() and host.task.enabled and host.task.config['_enabled']
            assert host.applied_character_revision==revision and not device.actions and not device.held
            assert not hasattr(host.executor,'_account_feature_run')
            stop.clear()
            exhausted=host.live_request({'command':'inspect-frame','request_id':'empty'})
            assert not exhausted['ok'] and exhausted['error']['type']=='FrameUnavailable',exhausted
            class Broken:
                def ocr(self,image): raise OSError('synthetic OCR failure')
            context.device=ReplayDevice([frames[0]])
            host.executor.ocr_engine=Broken()
            failed=host.live_request({'command':'inspect-frame','request_id':'broken','ocr':True})
            assert not failed['ok'] and failed['error']=={'type':'OSError','message':'synthetic OCR failure'},failed
            context.device=ReplayDevice([frames[0]])
            failed_feature=host.live_request({'command':'inspect-account-feature','request_id':'broken-feature'})
            assert not failed_feature['ok'] and failed_feature['error']=={
                'type':'RuntimeError','message':'特征码 OCR 读取失败'},failed_feature
            assert pause.is_set() and host.task.config['_enabled']
        ''')

    def test_input_owner_releases_before_live_capture(self):
        self.probe('''
            from src.task.BaseCombatTask import BaseCombatTask
            from src.runtime.native_task import NativeTriggerTask
            order=[]
            path=data/'frame.png'; cv2.imwrite(str(path),np.full((90,160,3),40,dtype=np.uint8))
            class Device(ReplayDevice):
                def next_frame(self,timeout=1):
                    assert not self.held
                    order.append('capture')
                    return super().next_frame(timeout)
                def release_all(self):
                    order.append('release-all')
                    super().release_all()
            class Service(BaseCombatTask,NativeTriggerTask):
                def run(self):
                    try:
                        self.send_key_down('x'); order.append('down')
                        self.executor.context.requests.put({'command':'inspect-frame','request_id':'frame'})
                        self.sleep(.01)
                    finally:
                        self._release_combat_inputs(); order.append('task-released')
                    order.append('old-resumed')
            stop=threading.Event(); device=Device([path]); events=[]
            def receive(event):
                events.append(event)
                if event.get('event')=='live-response': stop.set()
            context=TaskContext(device,{},data,stop,'owner',receive)
            host=host_for(context,task_entry=Service)
            try: host.run_session('Service')
            except Cancelled: pass
            else: raise AssertionError('session did not stop')
            response=next(event for event in events if event.get('event')=='live-response')
            assert response['ok'],response
            assert order.index('down')<order.index('task-released')<order.index('capture'),order
            assert 'release-all' in order[order.index('task-released'):order.index('capture')]
            assert 'old-resumed' not in order and not device.held
            assert [action.kind for action in device.actions]==['key_down','key_up']
            assert host.task.enabled and host.task.config['_enabled']
        ''')
