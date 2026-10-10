"""Production UID processing and generic Qt rendering; no real screen/input APIs."""
import base64
import os
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

class TestNativeUIDOverlay(unittest.TestCase):
    def setUp(self):
        from src.runtime import native_uid_overlay
        self.module=native_uid_overlay
        self.events=[]
        self.context=SimpleNamespace(pause=threading.Event(),stop=threading.Event(),run_id='owner-one',
            emit=lambda event,**values:self.events.append(dict(event=event,**values)))
        self.preferences={'Enable Blur':True,'Blur Algorithm':'Inpaint','Blur Interval':1}
        self.target={'owner':{'hwnd':123,'pid':456,'created':1.5},'x':-1920,'y':150,
                     'width':1920,'height':1080,'dpi':144}
        self.now=0.
        self.processor=self.module.NativeUIDOverlay(self.context,self.preferences,lambda:self.target,
                                                     clock=lambda:self.now)
        random=np.random.default_rng(7)
        self.frame=random.integers(0,256,(1080,1920,3),dtype=np.uint8)

    def test_roi_only_algorithms_interval_and_original_frame(self):
        original=self.frame.copy()
        with patch.object(cv2,'inpaint',wraps=cv2.inpaint) as inpaint:
            self.processor.poll(self.frame)
            self.assertLess(inpaint.call_args.args[0].shape[0],60)
            self.assertLess(inpaint.call_args.args[0].shape[1],300)
        self.assertEqual(self.events[-1]['event'],'overlay-update')
        patch_data=self.events[-1]['patch']
        image=cv2.imdecode(np.frombuffer(base64.b64decode(patch_data['png']),np.uint8),cv2.IMREAD_COLOR)
        self.assertEqual(image.shape[:2],(patch_data['height'],patch_data['width']))
        self.assertLess(len(base64.b64decode(patch_data['png'])),100000)
        self.now=.9
        self.processor.poll(self.frame)
        self.assertEqual(len(self.events),1)
        self.preferences['Blur Algorithm']='Blur'
        self.now=1.
        with patch.object(cv2,'GaussianBlur',wraps=cv2.GaussianBlur) as blur:
            self.processor.poll(self.frame)
            self.assertEqual(blur.call_args.args[0].shape[:2],image.shape[:2])
        self.assertEqual(len(self.events),2)
        self.assertTrue(np.array_equal(self.frame,original))

    def test_pause_background_resize_stop_clear_without_disabling(self):
        self.processor.poll(self.frame)
        self.context.pause.set();self.processor.poll(self.frame)
        self.assertEqual(self.events[-1],{'event':'overlay-clear','owner_id':'owner-one'})
        self.assertTrue(self.preferences['Enable Blur'])
        self.context.pause.clear();self.processor.poll(self.frame)
        target=self.target;self.target=None
        self.processor.poll(self.frame)
        self.assertEqual(self.events[-1]['event'],'overlay-clear')
        self.target=target;self.processor.poll(self.frame)
        self.target['width']=1280;self.processor.poll(self.frame)
        self.assertEqual(self.events[-1]['event'],'overlay-clear')
        self.target['width']=1920;self.processor.poll(self.frame)
        self.context.stop.set();self.processor.poll(self.frame)
        self.assertEqual(self.events[-1]['event'],'overlay-clear')
        self.assertTrue(self.preferences['Enable Blur'])

    def test_worker_module_has_no_qt_or_legacy_import(self):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        body='''
import importlib.abc
class Forbidden(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'ok','PySide6','qfluentwidgets'}:
            raise ImportError('forbidden worker import: '+fullname)
sys.meta_path.insert(0,Forbidden())
from src.runtime import native_uid_overlay
assert not any(name.split('.')[0] in {'ok','PySide6','qfluentwidgets'} for name in sys.modules)
'''
        TestAccountManagementEntry().run_probe(body)


class TestGenericPatchOverlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['QT_QPA_PLATFORM']='offscreen'
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_clickthrough_physical_placement_live_move_identity_clear(self):
        from PySide6.QtCore import Qt
        from gameframe import overlay as module
        owner={'hwnd':123,'pid':456,'created':1.5}
        state=[dict(owner=owner,x=-1920,y=150,width=1920,height=1080,dpi=144)]
        placements=[]
        def place(widget,rect):placements.append(rect);widget.resize(rect[2],rect[3])
        geometry=SimpleNamespace(target=lambda requested:state[0] if requested==owner else None,place=place)
        widget=module.PatchOverlay(geometry=geometry)
        self.addCleanup(widget.clear)
        self.addCleanup(widget.close)
        success,png=cv2.imencode('.png',np.zeros((20,100,3),np.uint8));self.assertTrue(success)
        event={'event':'overlay-update','owner_id':'owner-one','target':dict(state[0]),
               'patch':{'x':1700,'y':1050,'width':100,'height':20,'png':base64.b64encode(png).decode()}}
        widget.apply_event(event)
        self.assertTrue(widget.windowFlags() & Qt.WindowTransparentForInput)
        self.assertTrue(widget.windowFlags() & Qt.WindowStaysOnTopHint)
        self.assertTrue(widget.windowFlags() & Qt.WindowDoesNotAcceptFocus)
        self.assertEqual(placements[-1],(-220,1200,100,20))
        state[0]['x']=10;state[0]['dpi']=192
        widget.refresh_target()
        self.assertEqual(placements[-1],(1710,1200,100,20))
        widget.apply_event({'event':'overlay-clear','owner_id':'old-owner'})
        self.assertTrue(widget.isVisible())
        state[0]=None;widget.refresh_target()
        self.assertFalse(widget.isVisible())
        self.assertFalse(widget.timer.isActive())
        geometry.target=lambda owner:(_ for _ in ()).throw(OSError('fixture window disappeared'))
        with self.assertLogs('gameframe.overlay',level='ERROR'):
            widget.apply_event(event)
        self.assertFalse(widget.isVisible())
        self.assertFalse(widget.timer.isActive())

    def test_reused_target_process_or_changed_client_clears(self):
        from gameframe import overlay as module
        state=[{'owner':{'hwnd':1,'pid':2,'created':3},'x':0,'y':0,'width':200,'height':100,'dpi':96}]
        geometry=SimpleNamespace(target=lambda owner:state[0],place=lambda widget,rect:widget.resize(rect[2],rect[3]))
        widget=module.PatchOverlay(geometry=geometry)
        self.addCleanup(widget.clear);self.addCleanup(widget.close)
        _,png=cv2.imencode('.png',np.zeros((10,20,3),np.uint8))
        event={'event':'overlay-update','owner_id':'run','target':dict(state[0]),
               'patch':{'x':100,'y':80,'width':20,'height':10,'png':base64.b64encode(png).decode()}}
        widget.apply_event(event)
        state[0]['width']=300;widget.refresh_target()
        self.assertFalse(widget.isVisible())
        self.assertIsNone(widget.target)
