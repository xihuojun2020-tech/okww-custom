"""Native user identities and owner-boundary replacement over Replay only."""
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gameframe.api import Cancelled, TaskContext
from gameframe.devices.replay import ReplayDevice
from src.combat.settings import COMBAT_GLOBAL_DEFAULTS, TEMPLATE_MATCHING_DEFAULTS
from src.runtime.native_combat_host import NativeCombatHost
from src.runtime.native_metadata import TaskMetadata, task_id
from src.runtime.native_task import NativeBaseTask, NativeTriggerTask

ROOT = Path(__file__).resolve().parents[1]

class Builtin(NativeBaseTask):
    def run(self):
        return 'builtin'

class User(NativeTriggerTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config['value'] = 1
    def run(self):
        return False

class Renamed(User):
    pass

class Bad(User):
    def on_create(self):
        raise ValueError('candidate rejected')

class TestNativeUserTaskHost(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.data = Path(cls.temp.name)
    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()
    def descriptor(self, cls=User, identifier='one', revision='v1'):
        return dict(task_class=cls, id='user:'+identifier, config_name='user_'+identifier,
                    source_revision=revision, required_capabilities=frozenset())
    def host(self, descriptors=()):
        self.events=[]
        device=ReplayDevice([ROOT/'tests/images/con_full.png'] * 8)
        context=TaskContext(device, {}, self.data, threading.Event(), 'users', self.events.append)
        host=NativeCombatHost(context, coco_path=ROOT/'assets/coco_annotations.json',
            global_options=COMBAT_GLOBAL_DEFAULTS, ocr_engine=None,
            template_matching=TEMPLATE_MATCHING_DEFAULTS, task_entry=Builtin,
            user_tasks=descriptors)
        return host
    def test_identity_rename_registry_and_failed_candidate(self):
        # Same class name in two modules remains two independent sources/configs.
        other=type('User', (User,), {})
        host=self.host((self.descriptor(),self.descriptor(other,'two')))
        first=host._tasks_by_id()['user:one']; second=host._tasks_by_id()['user:two']
        host._select_task(first); first.config['value']=9; first.enable()
        self.assertNotEqual(first.config.config_file,second.config.config_file)
        self.assertEqual(second.config['value'],1)
        host._select_task(first)
        store=SimpleNamespace(load_tasks=lambda:[self.descriptor(Renamed,revision='v2')],revision='catalog2')
        result=host.reload_user_tasks(store)
        renamed=host._tasks_by_id()['user:one']
        self.assertEqual(result,{'applied_revision':'catalog2'})
        self.assertEqual(renamed.config['value'],9)
        self.assertTrue(renamed.enabled)
        self.assertIs(host.task,renamed)
        self.assertIsNone(host.executor.get_task_by_class(other))
        self.assertIs(host.executor.get_task_by_class(Renamed),renamed)
        registry=host.tasks
        with self.assertRaisesRegex(ValueError,'candidate rejected'):
            host.reload_user_tasks(SimpleNamespace(load_tasks=lambda:[self.descriptor(Bad)],revision='bad'))
        self.assertIs(host.tasks,registry)
        self.assertIs(host.task,renamed)
        self.assertEqual(host.applied_revision,'catalog2')
        host._configuration_service_enables.add('user:one')
        host.reload_user_tasks(SimpleNamespace(load_tasks=lambda:[],revision='empty'))
        self.assertNotIn('user:one',host._tasks_by_id())
        self.assertFalse(host._configuration_service_enables)
        self.assertNotIn('user:one',{row['id'] for row in TaskMetadata(host).snapshot()['tasks']})
        self.assertTrue(first.config['_enabled'])
        self.assertTrue(first.config.config_file.exists())

    def test_bundle_features_commit_with_registry_and_fail_as_one_candidate(self):
        import json
        import cv2
        import numpy as np
        assets = self.data / 'bundle-fixture'
        assets.mkdir(exist_ok=True)
        image = assets / 'icon.png'
        cv2.imwrite(str(image), np.full((8, 8, 3), 30, dtype=np.uint8))
        coco = assets / 'coco.json'
        coco.write_text(json.dumps(dict(images=[dict(id=1,file_name='icon.png')],
            categories=[dict(id=1,name='icon')], annotations=[dict(image_id=1,category_id=1,bbox=[0,0,8,8])])))
        descriptor = self.descriptor()
        descriptor.update(asset_coco_path=coco,asset_namespace='bundle',group_name='Tools')
        host = self.host((descriptor,))
        self.assertEqual(len(host.executor.feature_set._coco_sources),2)
        self.assertEqual(host._tasks_by_id()['user:one'].group_name,'Tools')
        frame = np.zeros((8,8,3),dtype=np.uint8)
        self.assertEqual(int(host.executor.feature_set.get_feature_by_name(frame,'bundle/icon').mat[0,0,0]),30)
        updated = assets / 'updated.png'
        cv2.imwrite(str(updated), np.full((8,8,3), 90, dtype=np.uint8))
        value = json.loads(coco.read_text()); value['images'][0]['file_name']='updated.png'
        new_coco = assets/'new.json'; new_coco.write_text(json.dumps(value))
        next_descriptor = self.descriptor(Renamed)
        next_descriptor.update(asset_coco_path=new_coco,asset_namespace='bundle',group_name='Tools')
        host.reload_user_tasks(SimpleNamespace(load_tasks=lambda:[next_descriptor],revision='new-assets'))
        self.assertEqual(int(host.executor.feature_set.get_feature_by_name(frame,'bundle/icon').mat[0,0,0]),90)
        features, registry = host.executor.feature_set, host.tasks
        broken = dict(next_descriptor,task_class=Bad)
        with self.assertRaisesRegex(ValueError,'candidate rejected'):
            host.reload_user_tasks(SimpleNamespace(load_tasks=lambda:[broken],revision='failed'))
        self.assertIs(host.executor.feature_set,features); self.assertIs(host.tasks,registry)
        updated.write_bytes(b'not an image')
        with self.assertRaisesRegex(ValueError,'Could not read image'):
            host.reload_user_tasks(SimpleNamespace(load_tasks=lambda:[next_descriptor],revision='bad-assets'))
        self.assertIs(host.executor.feature_set,features); self.assertIs(host.tasks,registry)
        host.reload_user_tasks(SimpleNamespace(load_tasks=lambda:[],revision='removed'))
        self.assertFalse(host.executor.feature_set.get_feature_by_name(frame,'bundle/icon'))
    def test_foreground_request_waits_for_destroy_and_release(self):
        host=self.host()
        trace=[]
        class Foreground(NativeBaseTask):
            def run(self):
                trace.append('run')
                host.context.requests.put({'command':'reload-user-tasks','request_id':'reload'})
                return None
            def on_destroy(self):
                trace.append('destroy')
        foreground=host.create_task(Foreground)
        host.tasks[Foreground]=foreground
        host.executor.set_task_registry(host.tasks)
        original=host.context.device.release_all
        def release():
            trace.append('release'); original()
        host.context.device.release_all=release
        def reload():
            trace.append('reload'); host.context.stop.set()
            return {'applied_revision':'next'}
        with patch.object(host,'reload_user_tasks',side_effect=reload):
            with self.assertRaises(Cancelled): host.run_session('Foreground')
        self.assertLess(trace.index('destroy'),trace.index('release'))
        self.assertLess(trace.index('release'),trace.index('reload'))
        self.assertTrue(any(event['event']=='user-tasks-reloaded' for event in self.events))
    def test_background_checkpoint_releases_before_reload(self):
        trace=[]
        class Service(NativeTriggerTask):
            def run(self):
                trace.append('service')
                self.executor.context.requests.put({'command':'reload-user-tasks'})
                self.sleep(.01)  # Genuine executor checkpoint preempts this poll.
                trace.append('unreachable')
        host=self.host((self.descriptor(Service,'background'),))
        original=host.context.device.release_all
        def release():
            trace.append('release'); original()
        host.context.device.release_all=release
        def reload():
            trace.append('reload'); host.context.stop.set()
            return {'applied_revision':'background-next'}
        with patch.object(host,'reload_user_tasks',side_effect=reload):
            with self.assertRaises(Cancelled): host.run_session('user:background')
        self.assertNotIn('unreachable',trace)
        self.assertLess(trace.index('service'),trace.index('reload'))
        self.assertIn('release',trace[trace.index('service')+1:trace.index('reload')])

    def test_paused_deferred_request_resolves_deleted_id(self):
        calls=[]
        class Foreground(NativeBaseTask):
            def run(self): calls.append('obsolete')
        host=self.host((self.descriptor(Foreground,'deferred'),))
        host.context.pause.set()
        host.context.requests.put({'command':'reload-user-tasks'})
        original_events=host.context.events
        def event(value):
            original_events(value)
            if value['event']=='user-tasks-reloaded': host.context.pause.clear()
            if value['event']=='session-task-failed': host.context.stop.set()
        host.context.events=event
        original_reload=host.reload_user_tasks
        store=SimpleNamespace(load_tasks=lambda:[],revision='deferred-delete')
        with patch.object(host,'reload_user_tasks',side_effect=lambda:original_reload(store)):
            with self.assertRaises(Cancelled): host.run_session('user:deferred')
        self.assertFalse(calls)
        failed=[event for event in self.events if event['event']=='session-task-failed']
        self.assertEqual(failed[0]['task_id'],'user:deferred')
        self.assertIn('KeyError',failed[0]['error'])

    def test_requirements_follow_replacement_and_deletion(self):
        host=self.host()
        descriptor=self.descriptor(identifier='requirements')
        descriptor['required_capabilities']={'unavailable'}
        host.reload_user_tasks(SimpleNamespace(load_tasks=lambda:[descriptor],revision='requires'))
        self.assertEqual(host.task_requirements['user:requirements'],{'unavailable'})
        host._select_task(host._tasks_by_id()['user:requirements'])
        with self.assertRaisesRegex(RuntimeError,'Missing device capabilities'):
            host.poll()
        self.assertFalse(host.context.device.actions)
        host.reload_user_tasks(SimpleNamespace(load_tasks=lambda:[],revision='deleted'))
        self.assertNotIn('user:requirements',host.task_requirements)

if __name__=='__main__': unittest.main()
