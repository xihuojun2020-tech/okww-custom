"""Owner, messenger and complete-format clipboard fixtures; no OS calls."""
import io
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image


from src.runtime import native_desktop_notifications as desktop
from src.runtime import native_desktop_clipboard as clipboard_module


def png_fixture():
    values = np.indices((32,32)).sum(axis=0)%2*255
    frame = np.stack((values, 255-values, values), axis=2).astype(np.uint8)
    output = io.BytesIO()
    Image.fromarray(frame[:,:,::-1]).save(output, format='PNG')
    return output.getvalue(), frame


class MessengerFixture:
    def __init__(self, search=False):
        self.game = desktop.WindowIdentity(1, 10, 100)
        self.messenger = desktop.WindowIdentity(2, 20, 200)
        self.popup = desktop.WindowIdentity(3, 20, 200)
        self.focus = self.game
        self.calls = []
        self.search, self.searched = search, False
        self.conversation = not search
        self.text = self.typed = ''
        self.image = self.prepared = None
        self.menu = False
        self.fail_capture = False

    def find(self, route): self.calls.append('find'); return self.messenger
    def activate(self, identity): self.calls.append(('activate', identity.hwnd)); self.focus = identity
    def valid(self, identity): return identity in (self.game,self.messenger,self.popup)
    def foreground(self): return self.focus
    def geometry(self, identity): return (800,600,1) if identity == self.messenger else (400,400,1)
    def windows(self, identity): return [self.messenger, self.popup] if self.searched else [self.messenger]
    def menus(self, identity): return [self.messenger]
    def capture(self, identity):
        if self.fail_capture: raise OSError('secret-private-chat-screenshot')
        width, height, _ = self.geometry(identity)
        frame = np.full((height,width,3),128,np.uint8)
        frame[0,0,0] = identity.hwnd
        if self.image is not None: frame[160:192,550:582] = self.image
        return frame
    def click(self, identity, point, right=False):
        self.calls.append(('click',identity.hwnd,right))
        if identity == self.popup: self.conversation = True
        if right: self.menu = True
        if point[1] == 550:
            if self.prepared is not None: self.image = self.prepared
            else: self.text = self.typed
    def clear_search(self, identity): self.calls.append('clear-search')
    def type_text(self, identity, text):
        self.calls.append('type')
        if not self.conversation: self.searched = True
        else: self.typed = text
    def ocr(self, frame):
        def box(text,x,y,w=80,h=20): return ([[x,y],[x+w,y],[x+w,y+h],[x,y+h]],(text,.99))
        if frame[0,0,0] == 3:
            return [[box('Contacts',20,20),box('fixture-contact',30,70),
                     box('Chat history',20,140),box('fixture-contact',30,190)]]
        boxes = [box('Send',700,540),box('Search',130,25)]
        if self.conversation:
            boxes += [box('fixture-contact',400,60),box('fixture-contact',70,170)]
        if self.text: boxes.append(box(self.text.replace('\n',''),500,180,200))
        if self.menu: boxes.append(box('Paste',600,480))
        return [boxes]


class FakeMedium:
    def set(self, tymed, data): self.tymed,self.data=tymed,data


class NativeDataObjectFixture:
    def __init__(self): self.entries=[]
    def SetData(self,fmt,medium,release):
        if release: raise AssertionError('Snapshot must copy without stealing source data')
        copy=FakeMedium();copy.set(medium.tymed,medium.data)
        self.entries.append((fmt,copy))
    def GetData(self,fmt):
        medium=next(medium for stored,medium in self.entries if stored==fmt)
        copy=FakeMedium();copy.set(medium.tymed,medium.data)
        return copy


class ClipboardFixture:
    def __init__(self):
        self.calls=[]
        self.number=1
        self.mediums={13:(1,b'unicode'),101:(1,b'html'),15:(1,b'file-drop'),2:(16,300)}
        self.current='original'
        self.com=SimpleNamespace(IID_IDataObject='data',DVASPECT_CONTENT=1,DATADIR_GET=1,
            TYMED_HGLOBAL=1,TYMED_GDI=16,TYMED_MFPICT=32,TYMED_ENHMF=64,TYMED_ISTREAM=4,
            STGMEDIUM=FakeMedium,OleGetClipboard=lambda:self,
            OleSetClipboard=self.set,OleFlushClipboard=lambda:self.calls.append('flush'))
    def sequence(self): return self.number
    def initialize(self): self.calls.append(('init',threading.get_ident()))
    def uninitialize(self): self.calls.append(('uninit',threading.get_ident()))
    def EnumFormatEtc(self, direction):
        return [(key,None,1,-1,value[0]) for key,value in self.mediums.items()]
    def GetData(self, requested):
        self.calls.append(('get',requested[0]))
        medium=FakeMedium()
        medium.set(*self.mediums[requested[0]])
        return medium
    def object(self, entries):
        api=clipboard_module.OleClipboardAPI.__new__(clipboard_module.OleClipboardAPI)
        api.com=self.com
        api.shell=SimpleNamespace(SHCreateDataObject=lambda parent,children,inner,iid:NativeDataObjectFixture())
        return api.object(entries)
    def png_object(self,png): return 'image'
    def set(self,obj): self.current=obj;self.number+=1;self.calls.append('set')


class DesktopTests(unittest.TestCase):
    def owner(self, fixture, *, clipboard=None, wait=None):
        stop,pause=threading.Event(),threading.Event()
        clock=[0]
        def advance(seconds): clock[0]+=seconds
        sender=desktop.MessengerSender(fixture,SimpleNamespace(ocr=fixture.ocr),stop=stop,pause=pause,
                                       clipboard=clipboard,clock=lambda:clock[0],wait=wait or advance)
        state={'_enabled':True}
        lease=threading.Lock();lease.acquire()
        thread=threading.get_ident()
        def guard():
            self.assertTrue(lease.locked());self.assertEqual(threading.get_ident(),thread)
        context=SimpleNamespace(stop=stop,pause=pause,
            device=SimpleNamespace(release_all=lambda:fixture.calls.append('release')))
        prefix = 'WeChat' if fixture.search else 'QQ'
        config = {prefix+' Desktop Notification (Not Reliable)':True,
                  prefix+' Desktop Nickname':'fixture-contact'}
        owner=desktop.OwnerDesktopNotifications(context,sender,config,owner_check=guard)
        self.addCleanup(owner.close)
        self.addCleanup(lease.release)
        return owner,context,state

    def test_http_thread_only_queues_checkpoint_yields_owner_sends(self):
        from src.runtime.native_combat_executor import SessionPreempted
        fixture=MessengerFixture()
        owner,context,state=self.owner(fixture)
        futures=[]
        worker=threading.Thread(target=lambda:futures.extend(owner.submit('Notice','fixture')))
        worker.start();worker.join()
        self.assertEqual(fixture.calls,[])
        with self.assertRaises(SessionPreempted): owner.checkpoint()
        self.assertFalse(futures[0].done())
        self.assertTrue(owner.drain_one())
        self.assertEqual(futures[0].result()['status'],'delivered')
        self.assertEqual(fixture.calls[0],'release')
        self.assertEqual(fixture.calls[-2:],['release',('activate',1)])
        self.assertEqual(state,{'_enabled':True})
        self.assertFalse(context.pause.is_set())
        self.assertEqual(fixture.focus,fixture.game)

    def test_existing_runtime_session_lease_remains_held_through_handoff(self):
        from gameframe.runtime import Runtime
        from src.runtime.native_combat_executor import SessionPreempted
        fixture=MessengerFixture()
        events=[]
        store=SimpleNamespace(begin=lambda *args:None,finish=lambda *args:None)
        runtime=Runtime(store,events.append)
        device=SimpleNamespace(capabilities=set(),release_all=lambda:fixture.calls.append('release'))
        manifest=SimpleNamespace(id='fixture',session_required_capabilities=set())
        thread=threading.get_ident()
        def guard():
            self.assertTrue(runtime._input_owner.locked())
            self.assertEqual(threading.get_ident(),thread)
        def session(task,context):
            clock=[0]
            sender=desktop.MessengerSender(fixture,SimpleNamespace(ocr=fixture.ocr),
                stop=context.stop,pause=context.pause,clock=lambda:clock[0],
                wait=lambda seconds:clock.__setitem__(0,clock[0]+seconds))
            config={'QQ Desktop Notification (Not Reliable)':True,'QQ Desktop Nickname':'fixture-contact'}
            owner=desktop.OwnerDesktopNotifications(context,sender,config,owner_check=guard)
            try:
                future,=owner.submit('','fixture')
                with self.assertRaises(SessionPreempted): owner.checkpoint()
                device.release_all()  # Existing host unwind boundary.
                owner.drain_one()
                guard()
                return {'notification':future.result()}
            finally: owner.close()
        package=SimpleNamespace(run_session=session)
        result=runtime.run(manifest,package,None,device,Path.cwd(),session=True)
        self.assertEqual(result['notification']['status'],'delivered')
        self.assertFalse(runtime._input_owner.locked())
        self.assertEqual(fixture.focus,fixture.game)

    def test_real_runtime_replay_owner_active_cross_thread_and_revoked(self):
        from gameframe.runtime import Runtime
        from gameframe.devices.replay import ReplayDevice
        context_holder=[]
        runtime=Runtime(SimpleNamespace(begin=lambda *args:None,finish=lambda *args:None),lambda event:None)
        def session(task,context):
            context_holder.append(context)
            context.assert_input_owner()
            errors=[]
            def cross_thread():
                try: context.assert_input_owner()
                except RuntimeError as error: errors.append(str(error))
            worker=threading.Thread(target=cross_thread);worker.start();worker.join()
            self.assertEqual(len(errors),1)
            return {}
        runtime.run(SimpleNamespace(id='fixture',session_required_capabilities=set()),
                    SimpleNamespace(run_session=session),None,ReplayDevice([]),Path.cwd(),session=True)
        with self.assertRaisesRegex(RuntimeError,'active input owner'):
            context_holder[0].assert_input_owner()

    def test_factory_is_lazy_and_unsupported_replay_route_is_truthful(self):
        from gameframe.runtime import Runtime
        from gameframe.devices.replay import ReplayDevice
        runtime=Runtime(SimpleNamespace(begin=lambda *args:None,finish=lambda *args:None),lambda event:None)
        def session(task,context):
            config={'QQ Desktop Notification (Not Reliable)':False,'QQ Desktop Nickname':'fixture'}
            with patch.object(desktop,'WindowsMessengerBackend',side_effect=AssertionError('Win32 instantiated')):
                owner=desktop.create_owner_desktop_notifications(context,object(),config)
                try:
                    self.assertIsNone(owner.sender)
                    self.assertEqual(owner.submit('','disabled'),())
                    self.assertFalse(owner.drain_one())
                    config['QQ Desktop Notification (Not Reliable)']=True
                    future,=owner.submit('','unsupported')
                    owner.drain_one()
                    self.assertEqual(future.result(),{'route':'qq-desktop','status':'unavailable',
                                     'failure':'windows-desktop-device-required','submitted_messages':0})
                    self.assertIsNone(owner.sender)
                finally: owner.close()
            return {}
        runtime.run(SimpleNamespace(id='fixture',session_required_capabilities=set()),
                    SimpleNamespace(run_session=session),None,ReplayDevice([]),Path.cwd(),session=True)

    def test_contact_search_checks_popup_section_and_header(self):
        fixture=MessengerFixture(search=True)
        owner,_,_=self.owner(fixture)
        future,=owner.submit('','fixture')
        owner.drain_one()
        self.assertEqual(future.result()['status'],'delivered')
        self.assertIn('clear-search',fixture.calls)
        self.assertIn(('click',3,False),fixture.calls)

    def test_pause_preserves_queue_stop_closes_and_wrong_thread_cannot_send(self):
        fixture=MessengerFixture()
        owner,context,_=self.owner(fixture)
        future,=owner.submit('','fixture')
        context.pause.set()
        self.assertFalse(owner.drain_one())
        self.assertFalse(future.done())
        self.assertTrue(context.pause.is_set())
        errors=[]
        def wrong():
            try: owner.drain_one()
            except RuntimeError as error: errors.append(str(error))
        worker=threading.Thread(target=wrong);worker.start();worker.join()
        self.assertEqual(len(errors),1)
        self.assertEqual(fixture.calls,[])
        context.stop.set();owner.close()
        self.assertTrue(future.cancelled())

    def test_failed_sender_restores_game_and_hides_private_exception(self):
        fixture=MessengerFixture();fixture.fail_capture=True
        owner,_,state=self.owner(fixture)
        future,=owner.submit('','fixture')
        owner.drain_one()
        self.assertEqual(future.result()['status'],'failed')
        self.assertNotIn('secret',str(future.result()))
        self.assertEqual(fixture.focus,fixture.game)
        self.assertTrue(state['_enabled'])

    def test_pause_during_sender_stops_send_and_restores_owned_foreground(self):
        fixture=MessengerFixture()
        owner,context,state=self.owner(fixture)
        original=fixture.type_text
        def paused(identity,text): original(identity,text);context.pause.set()
        fixture.type_text=paused
        future,=owner.submit('','fixture')
        owner.drain_one()
        self.assertEqual(future.result(),{'route':'qq-desktop','status':'failed',
                         'failure':'paused','submitted_messages':0})
        self.assertTrue(context.pause.is_set())
        self.assertTrue(state['_enabled'])
        self.assertEqual(fixture.focus,fixture.game)

    def test_external_foreground_change_is_not_overwritten(self):
        fixture=MessengerFixture()
        owner,_,_=self.owner(fixture)
        other=desktop.WindowIdentity(99,99,99)
        original=owner.sender.send
        def moved(*args): result=original(*args);fixture.focus=other;return result
        owner.sender.send=moved
        future,=owner.submit('','fixture')
        owner.drain_one()
        self.assertEqual(future.result()['status'],'delivered')
        self.assertEqual(fixture.focus,other)

    def test_actual_input_boundary_rejects_pid_reuse(self):
        backend=desktop.WindowsMessengerBackend.__new__(desktop.WindowsMessengerBackend)
        calls=[]
        backend.gui=SimpleNamespace(IsWindow=lambda hwnd:True,
            SendMessageTimeout=lambda *args:calls.append(args),EnumChildWindows=lambda *args:None)
        backend.process=SimpleNamespace(GetWindowThreadProcessId=lambda hwnd:(0,20))
        backend.psutil=SimpleNamespace(Process=lambda pid:SimpleNamespace(create_time=lambda:201))
        with self.assertRaisesRegex(desktop.DesktopFailure,'identity'):
            backend.type_text(desktop.WindowIdentity(2,20,200),'fixture')
        self.assertEqual(calls,[])

    def test_chromium_surface_coordinates_and_unicode_use_trusted_child(self):
        backend=desktop.WindowsMessengerBackend.__new__(desktop.WindowsMessengerBackend)
        calls=[]
        backend.gui=SimpleNamespace(IsWindow=lambda hwnd:True,
            SendMessageTimeout=lambda *args:calls.append(args),
            EnumChildWindows=lambda hwnd,callback,data:callback(30,data),
            GetClassName=lambda hwnd:'Chrome_RenderWidgetHostHWND',
            ClientToScreen=lambda hwnd,point:(point[0]+100,point[1]+200),
            ScreenToClient=lambda hwnd,point:(point[0]-110,point[1]-230))
        backend.api=SimpleNamespace(MAKELONG=lambda x,y:(y<<16)|x)
        backend.process=SimpleNamespace(GetWindowThreadProcessId=lambda hwnd:(0,20))
        backend.psutil=SimpleNamespace(Process=lambda pid:SimpleNamespace(create_time=lambda:200))
        identity=desktop.WindowIdentity(2,20,200)
        backend.click(identity,(50,60))
        self.assertEqual([call[0] for call in calls],[30,30,30])
        self.assertEqual([call[3] for call in calls],[0x001E0028]*3)
        calls.clear()
        backend.type_text(identity,'😀')
        self.assertEqual([call[2] for call in calls],[0xD83D,0xDE00])
        self.assertEqual([call[0] for call in calls],[30,30])

    def test_clipboard_all_formats_are_materialized_and_restored_in_sta(self):
        api=ClipboardFixture()
        clipboard=clipboard_module.PreservedClipboard(api)
        with clipboard.preserve() as scope:
            self.assertEqual({item[1] for item in api.calls if isinstance(item,tuple) and item[0]=='get'},
                             set(api.mediums))
            scope.set_png(b'png')
            self.assertEqual(api.current,'image')
        snapshot=api.current
        self.assertEqual({fmt[0] for fmt,_ in snapshot.entries},set(api.mediums))
        for fmt,medium in snapshot.entries:
            value=snapshot.GetData(fmt).data
            self.assertEqual(value,medium.data)
        self.assertEqual(api.calls[0][0],'init')
        self.assertEqual(api.calls[-1][0],'uninit')
        self.assertIn(('uninit',threading.get_ident()),api.calls)
        self.assertEqual(api.calls.count('flush'),2)

    def test_external_clipboard_change_is_retained(self):
        api=ClipboardFixture()
        with self.assertRaises(clipboard_module.ClipboardChanged):
            with clipboard_module.PreservedClipboard(api).preserve() as scope:
                scope.set_png(b'png')
                api.current='external-new-data';api.number+=1
        self.assertEqual(api.current,'external-new-data')

    def test_empty_clipboard_is_restored_empty(self):
        api=ClipboardFixture();api.mediums={}
        with clipboard_module.PreservedClipboard(api).preserve() as scope: scope.set_png(b'png')
        self.assertIsNone(api.current)
        self.assertEqual(api.calls.count('flush'),1)

    def test_clipboard_snapshot_failure_never_overwrites_original(self):
        api=ClipboardFixture()
        def failed(fmt): raise OSError('fixture format cannot be materialized')
        api.GetData=failed
        with self.assertRaises(OSError):
            with clipboard_module.PreservedClipboard(api).preserve(): self.fail('Snapshot failure entered sender')
        self.assertEqual(api.current,'original')
        self.assertNotIn('set',api.calls)
        self.assertEqual(api.calls[-1][0],'uninit')
        api=ClipboardFixture()
        def mta(): raise OSError('fixture incompatible apartment')
        api.initialize=mta
        with self.assertRaises(OSError):
            with clipboard_module.PreservedClipboard(api).preserve(): self.fail('MTA entered sender')
        self.assertEqual(api.current,'original')
        self.assertEqual(api.calls,[])

    def test_disabled_desktop_preference_and_unconfirmed_send(self):
        fixture=MessengerFixture()
        owner,_,_=self.owner(fixture)
        owner.config['QQ Desktop Notification (Not Reliable)']=False
        self.assertEqual(owner.submit('','fixture'),())
        self.assertFalse(owner.pending)
        owner.config['QQ Desktop Notification (Not Reliable)']=True
        pending,=owner.submit('','queued')
        owner.config['QQ Desktop Notification (Not Reliable)']=False
        owner.drain_one()
        self.assertEqual(pending.result(),{'route':'qq-desktop','status':'skipped','reason':'route-disabled'})
        self.assertEqual(fixture.calls,[])
        owner.config['QQ Desktop Notification (Not Reliable)']=True
        original=fixture.ocr
        def hidden(frame):
            return [[entry for entry in original(frame)[0] if entry[1][0]!='fixture']]
        fixture.ocr=hidden
        owner.sender.ocr=SimpleNamespace(ocr=hidden)
        future,=owner.submit('','fixture')
        owner.drain_one()
        self.assertEqual(future.result(),{'route':'qq-desktop','status':'failed',
                         'failure':'outgoing-text-not-verified','submitted_messages':1})
        self.assertEqual(fixture.focus,fixture.game)

    def test_image_sender_pastes_verifies_and_restores_clipboard(self):
        fixture=MessengerFixture()
        png,frame=png_fixture()
        api=ClipboardFixture()
        def image_object(data): fixture.prepared=frame;return 'image'
        api.png_object=image_object
        owner,_,_=self.owner(fixture,clipboard=clipboard_module.PreservedClipboard(api))
        future,=owner.submit('','',[png])
        owner.drain_one()
        self.assertEqual(future.result(),{'route':'qq-desktop','status':'delivered','submitted_messages':1})
        self.assertIsInstance(api.current,NativeDataObjectFixture)
        self.assertEqual(fixture.focus,fixture.game)


if __name__=='__main__': unittest.main()
