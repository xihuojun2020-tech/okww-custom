"""Production foreground tasks over replay, with legacy imports forbidden."""

import os
import io
import sys
import tempfile
import threading
import traceback
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gameframe.api import Cancelled, TaskContext
from gameframe.devices.replay import ReplayDevice
from gameframe.packages import PackageManifest, TaskDefinition
from gameframe.runtime import Runtime
from gameframe.state import RunStore
from src.combat.settings import COMBAT_GLOBAL_DEFAULTS, TEMPLATE_MATCHING_DEFAULTS
from src.runtime.native_combat_host import NativeCombatHost
from src.runtime.native_task import NativeBaseTask
from tests.TestNativeCombatHost import BlockLegacyImports


ROOT = Path(__file__).resolve().parents[1]


class FrameProbeTask(NativeBaseTask):
    """Lifecycle-policy fixture: one genuine replay capture, no combat substitute."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_exit_after_config()

    def run(self):
        return {'frame_shape': list(self.next_frame().shape)}


class BlockApplicationImports(BlockLegacyImports):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'PyQt5', 'PyQt6', 'custom_ok', 'config', 'main'}:
            raise ImportError(f'Native tasks must not import {fullname}')
        return super().find_spec(fullname, path, target)


class TestNativeWWOneTime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.data_dir = Path(cls.temp.name)
        cls.blocker = BlockApplicationImports()
        sys.meta_path.insert(0, cls.blocker)
        from tests.fixture_support import make_account_environment
        from src.runtime.account_runtime_bootstrap import prepare_native_account_runtime
        make_account_environment(cls.data_dir, names=('A1', 'A3'))
        prepare_native_account_runtime(cls.data_dir, 'test')
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr
        original = Path.cwd()
        try:
            os.chdir(cls.data_dir)
            cls.engine = ONNXPaddleOcr(use_angle_cls=False, use_npu=False, use_openvino=True)
        finally:
            os.chdir(original)

    @classmethod
    def tearDownClass(cls):
        from src.runtime.account_runtime_bootstrap import get_account_runtime
        from src.evidence.service import get_evidence_service
        if get_account_runtime() is not None:
            get_evidence_service().close()
        sys.meta_path.remove(cls.blocker)
        cls.temp.cleanup()

    def setUp(self):
        # Each test starts with fresh task preferences in this synthetic root.
        # Config.update now persists overrides, so previous lifecycle tests must
        # not supply the next test's saved Exit After Task / enabled intent.
        for path in (self.data_dir / 'configs').glob('*Task.json'):
            path.unlink()

    def make_host(self, entry, *, registered_tasks=(), config=None, image='weekly_boss/list1.png', context=None):
        if context is None:
            device = ReplayDevice([ROOT / 'tests/images' / image] * 16)
            context = TaskContext(device, config or {}, self.data_dir, threading.Event(), 'one-time-test', Mock())
        else:
            device = context.device
        # Window metadata is an external boundary; no game/window is opened.
        window = SimpleNamespace(hwnd_title='鸣潮', exists=True, visible=True, hwnd=1)
        host = NativeCombatHost(context, coco_path=ROOT / 'assets/coco_annotations.json',
                                global_options=COMBAT_GLOBAL_DEFAULTS, ocr_engine=self.engine,
                                ocr_config={'default': {'lib': 'onnxocr'}},
                                template_matching=TEMPLATE_MATCHING_DEFAULTS,
                                task_entry=entry, registered_tasks=registered_tasks, window=window)
        return host, device

    def test_selected_production_class_name_metadata_and_registry(self):
        host, device = self.make_host('src.task.PianoTeachingTask:PianoTeachingTask')
        from src.task.PianoTeachingTask import PianoTeachingTask
        self.assertIsInstance(host.task, PianoTeachingTask)
        self.assertEqual(type(host.task).__name__, 'PianoTeachingTask')
        self.assertIs(host.task.get_task_by_class(PianoTeachingTask), host.task)
        self.assertEqual(host.task.config['Key Hold Time'], .03)
        self.assertFalse(host.task.enabled)
        self.assertFalse(device.actions)

    def test_session_foreground_then_real_service_share_executor(self):
        host, device = self.make_host(
            'tests.TestNativeWWOneTime:FrameProbeTask',
            registered_tasks=('src.task.AutoPickTask:AutoPickTask',))
        from src.task.AutoPickTask import AutoPickTask
        service = host.tasks[AutoPickTask]
        service.disable()

        host.context.requests.put({'command': 'run-task', 'task_id': 'missing'})
        host.context.requests.put({'command': 'set-service', 'task_id': 'AutoPickTask', 'enabled': True})
        original = service.run
        def run_service():
            self.assertIs(host.executor.current_task, service)
            self.assertFalse(host.tasks[FrameProbeTask].running)
            result = original()
            host.context.stop.set()
            return result
        with patch.object(service, 'run', side_effect=run_service) as run:
            with self.assertRaises(Cancelled):
                host.run_session('FrameProbeTask')
        run.assert_called_once()
        events = [call.args[0] for call in host.context.events.call_args_list]
        self.assertTrue(any(event['event'] == 'session-task-failed' and event['task_id'] == 'missing'
                            for event in events))
        self.assertTrue(any(event['event'] == 'session-task-finished' and
                            event['task_id'] == 'FrameProbeTask' for event in events))
        self.assertTrue(service.config['_enabled'])
        self.assertIs(host.executor.current_task, host.tasks[FrameProbeTask])
        self.assertFalse(device.held)
        service.disable()

    def test_session_only_restores_saved_services_without_enabling_combat_or_foreground(self):
        host, device = self.make_host('tests.TestNativeWWOneTime:FrameProbeTask',
            registered_tasks=('src.task.AutoCombatTask:AutoCombatTask', 'src.task.AutoPickTask:AutoPickTask'))
        from src.task.AutoCombatTask import AutoCombatTask
        from src.task.AutoPickTask import AutoPickTask
        combat = host.tasks[AutoCombatTask]
        pickup = host.tasks[AutoPickTask]
        host._set_service(combat, False)
        host._set_service(pickup, True, preference_only=True)
        def pickup_run():
            host.context.stop.set()
        with patch.object(host.task, 'run', side_effect=AssertionError('foreground task ran')), \
                patch.object(combat, 'run', side_effect=AssertionError('disabled combat ran')), \
                patch.object(pickup, 'run', side_effect=pickup_run) as run:
            with self.assertRaises(Cancelled):
                host.run_session(None)
        run.assert_called_once()
        self.assertFalse(combat.config['_enabled'])
        self.assertTrue(pickup.config['_enabled'])
        self.assertFalse(device.held)

    def test_session_explicit_combat_toggle_preserves_owner_thread(self):
        host, device = self.make_host('src.task.AutoCombatTask:AutoCombatTask')
        task = host.task
        host._set_service(task, False)
        self.assertFalse(task.enabled)
        self.assertFalse(task.config['_enabled'])
        host._set_service(task, True)
        self.assertTrue(task.enabled)
        self.assertTrue(task.config['_enabled'])
        task.disable()
        self.assertTrue(task.enabled)
        self.assertTrue(task.config['_enabled'])
        host._set_service(task, False)

    def test_session_real_rotation_yields_to_disable_and_foreground_request(self):
        host, device = self.make_host(
            'src.task.AutoCombatTask:AutoCombatTask', image='in_combat.png',
            config={'Switch to Healer before and after Combat': False},
            registered_tasks=('tests.TestNativeWWOneTime:FrameProbeTask',))
        original = device.submit
        stack = []
        def request_after_input(action):
            original(action)
            if action.kind.endswith('_down') and not stack:
                stack.extend(row.name for row in traceback.extract_stack())
                host.context.requests.put({'command': 'set-service', 'task_id': 'auto-combat', 'enabled': False})
                host.context.requests.put({'command': 'run-task', 'task_id': 'FrameProbeTask'})
        device.submit = request_after_input
        def stop_after_foreground(event):
            if event['event'] == 'session-task-finished':
                self.assertFalse(device.held)
                host.context.stop.set()
        host.context.events.side_effect = stop_after_foreground
        watchdog = threading.Timer(10, host.context.stop.set)
        watchdog.start()
        try:
            with self.assertRaises(Cancelled):
                host.run_session('auto-combat')
            for name in ('_run_combat', 'perform_combat_rotation', 'perform', 'do_perform'):
                self.assertIn(name, stack)
            self.assertFalse(host.task.enabled)
            self.assertFalse(host.task.config['_enabled'])
            self.assertFalse(device.held)
            self.assertEqual(host.task._error_count, 0)
            self.assertTrue(any(call.args[0]['event'] == 'session-task-finished'
                                for call in host.context.events.call_args_list))
        finally:
            watchdog.cancel()

    def test_session_solo_saved_disabled_can_start_and_stop_persistently(self):
        host, device = self.make_host('src.task.SoloCombatTask:SoloCombatTask')
        from src.runtime.native_config import Config
        task = host.task
        self.assertFalse(task.enabled)
        self.assertFalse(task._manual_desired)
        host._set_service(task, True)
        self.assertTrue(task.enabled)
        self.assertTrue(task._manual_desired)
        self.assertTrue(Config('SoloCombatTask', task.default_config)['_enabled'])
        self.assertFalse(host.poll()['in_combat'])
        self.assertTrue(host.executor.connected)
        host._set_service(task, False)
        self.assertFalse(task.enabled)
        self.assertFalse(task._manual_desired)
        self.assertFalse(Config('SoloCombatTask', task.default_config)['_enabled'])
        self.assertFalse(device.held)

    def test_real_drop_efficiency_uses_current_poll_start_time(self):
        host, device = self.make_host('src.task.AutoPickTask:AutoPickTask', config={'_enabled': True})
        before = time.time()
        host.poll()
        host.task.incr_drop(True)
        self.assertGreaterEqual(host.task.start_time, before)
        self.assertLessEqual(time.time() - host.task.start_time, 10)
        self.assertEqual(host.task.info['Echo Count'], 1)
        self.assertGreaterEqual(host.task.info['Echo per Hour'], 360)

    def test_foreground_lifecycle_initializes_execution_start_time(self):
        host, device = self.make_host('tests.TestNativeWWOneTime:FrameProbeTask')
        before = time.time()
        host.run_once()
        self.assertGreaterEqual(host.task.start_time, before)
        self.assertLessEqual(time.time() - host.task.start_time, 10)

    def test_invalid_session_requests_do_not_mutate_saved_config_or_service(self):
        from src.runtime.native_config import Config
        for request in (
                {'command': 'set-service', 'task_id': 'AutoPickTask', 'enabled': 0,
                 'config': {'_enabled': False}},
                {'command': 'set-service', 'task_id': 'FrameProbeTask', 'enabled': False,
                 'config': {'Exit After Task': True}}):
            with self.subTest(request=request):
                host, device = self.make_host(
                    'src.task.AutoPickTask:AutoPickTask', config={'_enabled': True},
                    registered_tasks=('tests.TestNativeWWOneTime:FrameProbeTask',))
                requested = next(task for cls, task in host.tasks.items()
                                 if cls.__name__ == request['task_id'])
                original = dict(requested.config)
                host.context.requests.put(request)
                host.context.events.side_effect = lambda event: (
                    host.context.stop.set() if event['event'] == 'session-task-failed' else None)
                with self.assertRaises(Cancelled):
                    host.run_session('AutoPickTask')
                self.assertEqual(dict(requested.config), original)
                self.assertEqual(dict(Config(request['task_id'], requested.default_config)), original)
                self.assertTrue(host.task.enabled)
                self.assertTrue(host.task.config['_enabled'])
                self.assertFalse(device.actions)

    def test_paused_disable_then_stop_persists_without_new_input(self):
        host, device = self.make_host('src.task.AutoCombatTask:AutoCombatTask')
        from src.runtime.native_config import Config
        from gameframe.worker import listen_stop
        device.next_frame = Mock(wraps=device.next_frame)
        device.release_all = Mock(wraps=device.release_all)
        control = ('{"command":"pause"}\n'
                   '{"command":"set-service","task_id":"auto-combat","enabled":false}\n'
                   '{"command":"stop"}\n')
        with patch('gameframe.worker.sys.stdin', io.StringIO(control)):
            listen_stop(host.context.stop, host.context.pause, host.context.requests)
        self.assertTrue(host.context.stop.is_set())
        with self.assertRaises(Cancelled):
            host.run_session('auto-combat')
        self.assertFalse(host.task.enabled)
        self.assertFalse(Config('AutoCombatTask', host.task.default_config)['_enabled'])
        device.next_frame.assert_not_called()
        device.release_all.assert_called_once()
        self.assertFalse(device.actions)

    def test_enable_while_paused_saves_intent_without_capture_or_input(self):
        host, device = self.make_host(
            'tests.TestNativeWWOneTime:FrameProbeTask',
            registered_tasks=('src.task.SoloCombatTask:SoloCombatTask',))
        from src.task.SoloCombatTask import SoloCombatTask
        from src.runtime.native_config import Config
        service = host.tasks[SoloCombatTask]
        self.assertFalse(service.enabled)
        host.context.pause.set()
        device.next_frame = Mock(wraps=device.next_frame)
        host.context.requests.put({'command': 'set-service', 'task_id': 'SoloCombatTask', 'enabled': True})
        def stop_after_enabled(event):
            if event['event'] == 'combat-state' and event['enabled']:
                host.context.stop.set()
        host.context.events.side_effect = stop_after_enabled
        with self.assertRaises(Cancelled):
            host.run_session('FrameProbeTask')
        self.assertTrue(service.enabled)
        self.assertTrue(Config('SoloCombatTask', service.default_config)['_enabled'])
        self.assertTrue(service._enable_pending)
        device.next_frame.assert_not_called()
        self.assertFalse(device.actions)

    def test_paused_foreground_request_runs_original_lifecycle_after_resume(self):
        host, device = self.make_host(
            'src.task.AutoPickTask:AutoPickTask', config={'_enabled': False},
            registered_tasks=('tests.TestNativeWWOneTime:FrameProbeTask',))
        host.context.pause.set()
        host.context.requests.put({'command': 'run-task', 'task_id': 'FrameProbeTask'})
        timers = []
        def resume_and_stop(event):
            if event['event'] == 'task-paused' and event['paused']:
                timer = threading.Timer(.05, host.context.pause.clear)
                timers.append(timer)
                timer.start()
            elif event['event'] == 'session-task-finished':
                self.assertFalse(host.context.pause.is_set())
                host.context.stop.set()
        host.context.events.side_effect = resume_and_stop
        task = host.tasks[FrameProbeTask]
        original = task.run
        def run():
            self.assertFalse(host.context.pause.is_set())
            return original()
        try:
            with patch.object(task, 'run', side_effect=run) as execute, \
                    patch.object(task, 'on_destroy', wraps=task.on_destroy) as cleanup:
                with self.assertRaises(Cancelled):
                    host.run_session('AutoPickTask')
                execute.assert_called_once()
                cleanup.assert_called_once()
            self.assertFalse(task.running)
            self.assertFalse(task.enabled)
            self.assertFalse(host.executor.wait_on_pause)
        finally:
            for timer in timers:
                timer.cancel()

    def test_full_piano_lifecycle_uses_real_unregistered_account_owner(self):
        host, device = self.make_host(
            'src.task.PianoTeachingTask:PianoTeachingTask',
            registered_tasks=('src.task.MultiAccountDailyTask:MultiAccountDailyTask',
                              'src.task.DailyTask:DailyTask'))
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask, CURRENT_ACCOUNT, UNREGISTERED_ACCOUNT
        from src.task.DailyTask import DailyTask
        owner = host.task.get_task_by_class(MultiAccountDailyTask)
        owner.config[CURRENT_ACCOUNT] = UNREGISTERED_ACCOUNT
        daily = host.task.get_task_by_class(DailyTask)
        submit = device.submit
        def stop_on_down(action):
            submit(action)
            if action.kind == 'key_down':
                host.context.stop.set()
        device.submit = stop_on_down
        device.release_all = Mock(wraps=device.release_all)
        class Pack:
            def run(self, task_id, context):
                return host.run_once()
        task = TaskDefinition('piano-lifecycle', 'Piano', 'once', {}, frozenset({'frames', 'keyboard'}))
        manifest = PackageManifest(ROOT, 'native-piano-lifecycle', 'Piano test', '0.00.00', '',
                                   'AGPL-3.0-or-later', ('windows',), 'native', (task,))
        store = RunStore(self.data_dir / 'piano-lifecycle.sqlite')
        try:
            with patch.object(daily, 'clear_profile_binding', wraps=daily.clear_profile_binding) as clear:
                with self.assertRaises(Cancelled):
                    Runtime(store, Mock()).run(manifest, Pack(), task.id, device, self.data_dir,
                                              stop=host.context.stop)
                self.assertEqual(clear.call_count, 2)
            self.assertIn('无序列', host.task.info['账号核验'])
            self.assertEqual(type(owner).__name__, 'MultiAccountDailyTask')
            self.assertEqual(type(daily).__name__, 'DailyTask')
            self.assertTrue(any(a.kind == 'key_down' and a.values['key'] == 'f'
                                for a in device.actions))
            self.assertFalse(host.task.running)
            self.assertFalse(host.task.enabled)
            self.assertFalse(host.executor.wait_on_pause)
            self.assertFalse(device.held)
            device.release_all.assert_called_once()
        finally:
            store.close()

    def test_missing_account_owner_blocks_lifecycle_before_input(self):
        host, device = self.make_host('src.task.PianoTeachingTask:PianoTeachingTask')
        from src.config_integrity import ConfigIntegrityBlocked
        with self.assertRaises(ConfigIntegrityBlocked):
            host.run_once()
        self.assertFalse(device.actions)
        self.assertFalse(host.task.running)
        self.assertFalse(host.task.enabled)
        self.assertFalse(host.executor.wait_on_pause)

    def test_mouse_reset_restores_actual_background_cursor_jump(self):
        host, device = self.make_host('src.task.MouseResetTask:MouseResetTask')
        device.cursor_position = (10, 10)
        host.poll()
        host.task.hwnd.visible = False
        image = device.next_frame().image
        device.cursor_position = (image.shape[1] // 2, image.shape[0] // 2)
        host.poll()
        self.assertEqual(device.cursor_position, (10, 10))
        self.assertEqual(host.task.trigger_interval, 1)
        host.task.hwnd.visible = True
        device.cursor_position = (400, 300)
        host.poll()
        self.assertEqual(device.cursor_position, (400, 300))
        host.task.disable()
        host.task.enable()
        self.assertEqual(host.task.mouse_pos, (400, 300))
        self.assertFalse(device.actions)

    def test_exit_after_task_closes_target_only_after_success(self):
        host, device = self.make_host('tests.TestNativeWWOneTime:FrameProbeTask',
                                     config={'Exit After Task': True})
        device.stop_target = Mock(wraps=device.stop_target)
        result = host.run_once()
        self.assertTrue(result['exit_requested'])
        self.assertTrue(result['result']['frame_shape'])
        device.stop_target.assert_called_once()
        self.assertTrue(device.target_stopped)
        self.assertFalse(host.task.running)

    def test_exit_after_task_does_not_close_on_capture_error_or_stop(self):
        for stopped in (False, True):
            with self.subTest(stopped=stopped):
                host, device = self.make_host('tests.TestNativeWWOneTime:FrameProbeTask',
                                             config={'Exit After Task': True})
                device.stop_target = Mock(wraps=device.stop_target)
                if stopped:
                    host.context.stop.set()
                    error = Cancelled
                else:
                    device.next_frame = Mock(side_effect=OSError('capture fault'))
                    error = OSError
                with self.assertRaises(error):
                    host.run_once()
                device.stop_target.assert_not_called()
                self.assertFalse(device.target_stopped)

    def test_real_echo_model_is_lazy_and_production_geometry_is_preserved(self):
        host, device = self.make_host('src.task.AutoCombatTask:AutoCombatTask', image='echo.png')
        detector = host.task._app.yolo_detect.__self__
        self.assertIsNone(detector._model)
        echoes = host.task.find_echos()
        self.assertTrue(echoes)
        self.assertTrue(all(box.name == 'echo' and box.height == 1 for box in echoes))
        model = detector.model
        raw = host.task.yolo_find_all()
        self.assertIs(detector.model, model)
        self.assertTrue(raw)
        self.assertTrue(all(box.height > 1 for box in raw))
        self.assertFalse(device.actions)

    def test_prepared_evidence_service_is_used_by_real_observers(self):
        host, device = self.make_host('src.task.DailyTask:DailyTask')
        from src.evidence.service import get_evidence_service, begin_daily_run, record_task_evidence
        from tests.fixture_support import synthetic_identity
        service = get_evidence_service()
        self.assertIs(host.executor.completion_evidence_service, service)
        self.assertEqual(service.repository.root,
                         self.data_dir / 'okww监控室' / 'CompletionEvidence')
        # Observer-boundary test with a synthetic identity; this does not claim
        # game identity verification or successful daily completion.
        identity = synthetic_identity('A1')['profile_id']
        host.task._verified_profile_id = identity
        host.task._enabled = True
        with patch.object(service, 'submit', wraps=service.submit) as submit:
            record = begin_daily_run(host.task)
            future = record_task_evidence(host.task, 'daily_activity', 'partial',
                                          'native observer binding', frame=host.task.frame)
            self.assertIsNotNone(record)
            self.assertIsNotNone(future)
            future.result(timeout=10)
            self.assertEqual(submit.call_count, 2)
        self.assertTrue(service.repository.list_records(identity, 'daily_activity'))
        self.assertFalse(device.actions)

    def test_real_piano_menu_detection_sends_f_and_stop_releases_key(self):
        host, device = self.make_host('src.task.PianoTeachingTask:PianoTeachingTask')
        submit = device.submit
        def stop_on_down(action):
            submit(action)
            if action.kind == 'key_down':
                host.context.stop.set()
        device.submit = stop_on_down
        device.release_all = Mock(wraps=device.release_all)
        class Pack:
            def run(self, task_id, context):
                # Business execution is isolated here; account lifecycle is
                # separately tested with a real registered account owner.
                host.task._enabled = True
                from src.runtime.combat_api import TaskDisabledException
                try:
                    return host.task.run()
                except TaskDisabledException as error:
                    raise Cancelled(str(error)) from error
        task = TaskDefinition('piano', 'Piano', 'once', {}, frozenset({'frames', 'keyboard'}))
        manifest = PackageManifest(ROOT, 'native-piano-test', 'Piano test', '0.00.00', '',
                                   'AGPL-3.0-or-later', ('windows',), 'native', (task,))
        store = RunStore(self.data_dir / 'piano.sqlite')
        try:
            with self.assertRaises(Cancelled):
                Runtime(store, Mock()).run(manifest, Pack(), task.id, device, self.data_dir,
                                          stop=host.context.stop)
        finally:
            store.close()
        self.assertEqual(host.task.info['弹琴状态'], '非弹琴界面，每秒按 F 推进')
        self.assertEqual([(a.kind, a.values.get('key')) for a in device.actions],
                         [('activate', None), ('key_down', 'f')])
        self.assertFalse(device.held)
        device.release_all.assert_called_once()

    def test_solo_production_service_retains_disabled_preference(self):
        host, device = self.make_host('src.task.SoloCombatTask:SoloCombatTask')
        from src.task.SoloCombatTask import SoloCombatTask
        self.assertIsInstance(host.task, SoloCombatTask)
        self.assertEqual(type(host.task).__name__, 'SoloCombatTask')
        self.assertEqual(host.run_service(), {'status': 'skipped', 'reason': 'combat-disabled'})
        self.assertFalse(host.task.config['_enabled'])
        self.assertFalse(device.actions)

    def test_simple_services_execute_real_nonactionable_frame(self):
        for entry in ('src.task.AutoPickTask:AutoPickTask',
                      'src.task.AutoLoginTask:AutoLoginTask',
                      'src.task.SkipDialogTask:AutoDialogTask',
                      'src.task.FastTravelTask:FastTravelTask'):
            with self.subTest(entry=entry):
                host, device = self.make_host(entry, config={'_enabled': True})
                host.poll()
                self.assertTrue(host.task.enabled)
                self.assertGreater(device.sequence, 0)
                self.assertFalse(device.actions)

    def test_real_absorb_pickup_input_and_runtime_stop(self):
        host, device = self.make_host('src.task.AutoPickTask:AutoPickTask',
                                     config={'_enabled': True}, image='absorb.png')
        submit = device.submit
        def stop_on_down(action):
            submit(action)
            if action.kind.endswith('_down'):
                host.context.stop.set()
        device.submit = stop_on_down
        device.release_all = Mock(wraps=device.release_all)
        class Pack:
            def run(self, task_id, context):
                return host.run_service()
        task = TaskDefinition('pick', 'Pickup', 'service', {'_enabled': True},
                              frozenset({'frames', 'keyboard'}))
        manifest = PackageManifest(ROOT, 'native-pickup-test', 'Pickup test', '0.00.00', '',
                                   'AGPL-3.0-or-later', ('windows',), 'native', (task,))
        store = RunStore(self.data_dir / 'pickup.sqlite')
        store.set_enabled(manifest.id, task.id, True)
        watchdog = threading.Timer(10, host.context.stop.set)
        watchdog.start()
        try:
            with self.assertRaises(Cancelled):
                Runtime(store, Mock()).run(manifest, Pack(), task.id, device, self.data_dir,
                                          stop=host.context.stop)
            self.assertTrue(any(a.kind == 'key_down' and a.values['key'] == 'f'
                                for a in device.actions))
            self.assertFalse(device.held)
            device.release_all.assert_called_once()
        finally:
            watchdog.cancel()
            store.close()

    def test_real_solo_qingxiao_rotation_and_runtime_stop(self):
        stop = threading.Event()
        device = ReplayDevice([ROOT / 'tests/images/solo_qingxiao_combat_1440.png'] * 16)
        submit = device.submit
        def stop_on_down(action):
            submit(action)
            if action.kind.endswith('_down'):
                stop.set()
        device.submit = stop_on_down
        device.release_all = Mock(wraps=device.release_all)
        hosts = []
        engine = self.engine
        class Pack:
            def run(self, task_id, context):
                host = NativeCombatHost(
                    context, coco_path=ROOT / 'assets/coco_annotations.json',
                    global_options=COMBAT_GLOBAL_DEFAULTS, ocr_engine=engine,
                    ocr_config={'default': {'lib': 'onnxocr'}},
                    template_matching=TEMPLATE_MATCHING_DEFAULTS,
                    task_entry='src.task.SoloCombatTask:SoloCombatTask')
                hosts.append(host)
                return host.run_service()
        task = TaskDefinition('solo', 'Solo Combat', 'service', {'_enabled': True},
                              frozenset({'frames', 'keyboard', 'mouse'}))
        manifest = PackageManifest(ROOT, 'native-solo-test', 'Solo test', '0.00.00', '',
                                   'AGPL-3.0-or-later', ('windows',), 'native', (task,))
        store = RunStore(self.data_dir / 'solo.sqlite')
        store.set_enabled(manifest.id, task.id, True)
        watchdog = threading.Timer(10, stop.set)
        watchdog.start()
        try:
            with self.assertRaises(Cancelled):
                Runtime(store, Mock()).run(manifest, Pack(), task.id, device, self.data_dir, stop=stop)
            self.assertEqual([type(char).__name__ for char in hosts[0].task.chars], ['Qingxiao'])
            self.assertTrue(any(action.kind.endswith('_down') for action in device.actions))
            self.assertFalse(device.held)
            device.release_all.assert_called_once()
            self.assertTrue(store.enabled(manifest.id, task.id))
        finally:
            watchdog.cancel()
            store.close()

    def test_second_sol_foreground_wait_pause_resume_and_stop(self):
        stop = threading.Event()
        pause = threading.Event()
        device = ReplayDevice([])
        device.foreground = False
        device.release_all = Mock(wraps=device.release_all)
        submit = device.submit
        resumes = []
        downs = []
        def pause_then_stop(action):
            submit(action)
            if action.kind == 'key_down':
                downs.append(action)
                if len(downs) == 1:
                    pause.set()
                    timer = threading.Timer(.15, pause.clear)
                    resumes.append(timer)
                    timer.start()
                else:
                    stop.set()
        device.submit = pause_then_stop
        hosts = []
        test = self
        class Pack:
            def run(self, task_id, context):
                host, _ = test.make_host('src.task.SecondSolTask:SecondSolTask', context=context)
                hosts.append(host)
                sleep = context.sleep
                def focus_after_wait(seconds):
                    if not device.foreground:
                        test.assertEqual(host.task.info['活动状态'], '等待游戏回到前台')
                        test.assertFalse(device.actions)
                        device.foreground = True
                    sleep(seconds)
                context.sleep = focus_after_wait
                return host.run_once()
        task = TaskDefinition('second-sol', 'Second Sol', 'once', {}, frozenset({'keyboard'}))
        manifest = PackageManifest(ROOT, 'native-second-sol-test', 'Activity test', '0.00.00', '',
                                   'AGPL-3.0-or-later', ('windows',), 'native', (task,))
        store = RunStore(self.data_dir / 'second-sol.sqlite')
        watchdog = threading.Timer(10, stop.set)
        watchdog.start()
        try:
            with self.assertRaises(Cancelled):
                Runtime(store, Mock()).run(manifest, Pack(), task.id, device, self.data_dir,
                                          stop=stop, pause=pause)
            self.assertEqual(len(downs), 2)
            self.assertFalse(any(a.kind == 'activate' for a in device.actions))
            self.assertEqual(hosts[0].task.info['按键次数'], 1)
            self.assertFalse(device.held)
            self.assertEqual(device.release_all.call_count, 2)
            self.assertFalse(hosts[0].task.running)
        finally:
            watchdog.cancel()
            for timer in resumes:
                timer.cancel()
            store.close()


if __name__ == '__main__':
    unittest.main()
