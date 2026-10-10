"""Real production task classes and local OCR over replay, with no game input."""

import os
import importlib.abc
import sys
import tempfile
import threading
import traceback
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from gameframe.api import Cancelled, TaskContext
from gameframe.devices.replay import ReplayDevice
from gameframe.packages import PackageManifest, TaskDefinition
from gameframe.runtime import Runtime
from gameframe.state import RunStore
from src.runtime.native_combat_host import NativeCombatHost
from src.combat.settings import COMBAT_GLOBAL_DEFAULTS, TEMPLATE_MATCHING_DEFAULTS


ROOT = Path(__file__).resolve().parents[1]


class BlockLegacyImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ok', 'PySide6', 'qfluentwidgets'}:
            raise ImportError(f'Native combat must not import {fullname}')
        return None


class TestNativeCombatHost(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.data_dir = Path(cls.temp.name)
        if any(name.split('.')[0] in {'ok', 'PySide6', 'qfluentwidgets'} for name in sys.modules):
            raise RuntimeError('Run NativeCombatHost tests in an isolated native process')
        cls.import_blocker = BlockLegacyImports()
        sys.meta_path.insert(0, cls.import_blocker)
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr
        previous_cwd = Path.cwd()
        try:
            # Installed models are read-only; OpenVINO's compiled cache is temporary.
            os.chdir(cls.data_dir)
            cls.engine = ONNXPaddleOcr(use_angle_cls=False, use_npu=False, use_openvino=True)
        finally:
            os.chdir(previous_cwd)

    @classmethod
    def tearDownClass(cls):
        sys.meta_path.remove(cls.import_blocker)
        cls.temp.cleanup()

    def make_host(self, image='con_full.png'):
        device = ReplayDevice([ROOT / 'tests/images' / image] * 8)
        context = TaskContext(device, {}, self.data_dir, threading.Event(), 'host-test', Mock())
        host = NativeCombatHost(context, coco_path=ROOT / 'assets/coco_annotations.json',
                                global_options=COMBAT_GLOBAL_DEFAULTS, ocr_engine=self.engine,
                                template_matching=TEMPLATE_MATCHING_DEFAULTS)
        return host, device

    def test_real_production_team_recognition_without_ok_application(self):
        host, device = self.make_host()
        from src.task.AutoCombatTask import AutoCombatTask
        self.assertIsInstance(host.task, AutoCombatTask)
        with patch.object(self.engine, 'ocr', wraps=self.engine.ocr) as ocr:
            team = host.task.in_team()
            ocr.assert_not_called()
        self.assertTrue(team[0], team)
        self.assertIn(team[2], (2, 3))
        self.assertTrue(host.task.logged_in)
        self.assertFalse(any(name.split('.')[0] in {'ok', 'PySide6', 'qfluentwidgets'}
                             for name in sys.modules))
        self.assertFalse(device.actions)

    def test_real_task_noncombat_poll_on_menu_screenshot(self):
        host, device = self.make_host('weekly_boss/list1.png')
        result = host.poll()
        self.assertEqual(result, {'in_combat': False, 'enabled': True})
        self.assertFalse(device.actions)
        self.assertTrue(host.task.config['_enabled'])
        self.assertIsNone(getattr(host.executor, '_background_combat_mode', None))

    def test_real_open_world_classification_without_loading_daily_tasks(self):
        host, device = self.make_host('in_combat.png')
        self.assertTrue(host.task.is_open_world_auto_combat())
        self.assertNotIn('src.task.TacetTask', sys.modules)
        self.assertNotIn('src.task.DailyTask', sys.modules)
        self.assertFalse(device.actions)

    def test_production_heavy_attack_uses_new_input_and_stop_contract(self):
        host, device = self.make_host()
        from src.char.BaseChar import BaseChar
        host.task.skip_combat_check = True
        char = BaseChar(host.task, index=0)
        char.heavy_attack(duration=.001)
        self.assertEqual([action.kind for action in device.actions], ['button_down', 'button_up'])
        self.assertFalse(device.held)
        host.context.stop.set()
        with self.assertRaises(Cancelled):
            host.poll()
        self.assertTrue(host.task.enabled)
        self.assertTrue(host.task.config['_enabled'])

    def test_actual_production_recovery_catch_propagates_stop(self):
        host, _ = self.make_host()
        from src.runtime.combat_api import TaskDisabledException
        host.context.stop.set()
        with self.assertRaises(TaskDisabledException):
            host.task.combat_is_active()
        self.assertEqual(host.task._error_count, 0)
        self.assertTrue(host.task.enabled)

    def test_provider_cannot_switch_existing_production_class_mro(self):
        host, _ = self.make_host()
        from src.runtime import combat_api
        with self.assertRaisesRegex(RuntimeError, 'another mode'):
            combat_api.configure(native=False, data_dir=self.data_dir)
        from src.runtime.native_task import NativeBaseTask
        self.assertIsInstance(host.task, NativeBaseTask)

    def test_headless_screenshot_is_saved_under_explicit_data_root(self):
        host, _ = self.make_host()
        image = host.executor.frame
        host.task.screenshot('native-host/frame', frame=image)
        path = self.data_dir / 'okww监控室/native-host/frame.png'
        self.assertTrue(path.is_file())
        self.assertTrue((self.data_dir / 'configs/_con_full_size.json').is_file())

    def test_real_local_ocr_through_production_task(self):
        host, device = self.make_host('weekly_boss/detail.png')
        boxes = host.task.ocr()
        self.assertTrue(boxes)
        self.assertTrue(any('单人挑战' in box.name for box in boxes), [box.name for box in boxes])
        from src.runtime.combat_api import Box
        self.assertTrue(all(isinstance(box, Box) for box in boxes))
        self.assertFalse(device.actions)

    def test_real_ocr_reuses_same_frame_and_recomputes_changed_frame(self):
        host, _ = self.make_host('weekly_boss/detail.png')
        with patch.object(self.engine, 'ocr', wraps=self.engine.ocr) as infer:
            first = host.task.ocr()
            second = host.task.ocr()
            self.assertEqual(infer.call_count, 1)
            self.assertEqual([box.name for box in first], [box.name for box in second])
            host.executor.next_frame()
            host.task.ocr()
            self.assertEqual(infer.call_count, 2)

    def test_service_reuses_real_task_and_production_error_backoff(self):
        host, device = self.make_host()
        elapsed = [0.0]
        capture_times = []
        def failed_capture(timeout):
            capture_times.append(round(elapsed[0], 3))
            raise OSError('offline capture fault')
        device.next_frame = failed_capture
        def sleep(seconds):
            elapsed[0] += seconds
            if elapsed[0] >= 6.2:
                host.context.stop.set()
            host.context.check_stop()
        host.context.sleep = sleep
        with patch('time.monotonic', side_effect=lambda: elapsed[0]), \
                patch('time.time', side_effect=lambda: 1000 + elapsed[0]):
            with self.assertRaises(Cancelled):
                host.run_service()
        self.assertEqual(host.task._error_count, 3)
        self.assertEqual(capture_times, [0, 0, 2, 2, 6, 6])
        self.assertTrue(host.task.enabled)
        self.assertTrue(host.task.config['_enabled'])
        self.assertFalse(device.actions)

    def test_service_pause_waits_and_resumes_same_task(self):
        host, device = self.make_host('weekly_boss/list1.png')
        pause = threading.Event()
        pause.set()
        host.executor.pause_event = pause
        identity = id(host.task)
        sleeps = []
        def sleep(seconds):
            sleeps.append((seconds, device.sequence))
            if len(sleeps) == 2:
                pause.clear()
            elif len(sleeps) == 3:
                host.context.stop.set()
            host.context.check_stop()
        host.context.sleep = sleep
        with self.assertRaises(Cancelled):
            host.run_service()
        self.assertEqual(sleeps[0][1], 0)
        self.assertEqual(sleeps[1][1], 0)
        self.assertGreater(device.sequence, 0)
        self.assertEqual(id(host.task), identity)
        self.assertTrue(host.task.enabled)
        self.assertFalse(device.held)

    def test_log_screenshot_failure_does_not_replace_combat_error(self):
        host, _ = self.make_host()
        with patch.object(host, 'save_screenshot', side_effect=OSError('disk unavailable')):
            host.task.log_error('production diagnostic')
        self.assertEqual(host.task.info['Error'], 'production diagnostic')
        self.assertTrue(host.task.enabled)

    def test_full_production_rotation_stops_and_runtime_releases_single_owner(self):
        for image, names in (
                ('in_combat.png', ['Iuno', 'Roccia', 'ShoreKeeper']),
                ('combat_has_cd.png', ['Aemeath', 'ShoreKeeper', 'Iuno'])):
            with self.subTest(image=image):
                stop = threading.Event()
                device = ReplayDevice([ROOT / 'tests/images' / image] * 16)
                submit = device.submit
                call_stack = []
                def stop_after_input(action):
                    submit(action)
                    if action.kind.endswith('_down'):
                        call_stack.extend(row.name for row in traceback.extract_stack())
                        stop.set()
                device.submit = stop_after_input
                device.release_all = Mock(wraps=device.release_all)
                hosts = []
                engine = self.engine
                class Pack:
                    def run(self, task_id, context):
                        host = NativeCombatHost(
                            context, coco_path=ROOT / 'assets/coco_annotations.json',
                            global_options=COMBAT_GLOBAL_DEFAULTS, ocr_engine=engine,
                            template_matching=TEMPLATE_MATCHING_DEFAULTS)
                        hosts.append(host)
                        return host.run_service()
                task = TaskDefinition('combat', 'Offline combat', 'service',
                                      {'Switch to Healer before and after Combat': False},
                                      frozenset({'frames', 'keyboard', 'mouse'}))
                manifest = PackageManifest(ROOT, 'native-combat-test', 'Offline test',
                                           '0.00.00', '', 'AGPL-3.0-or-later',
                                           ('windows',), 'native', (task,))
                store = RunStore(self.data_dir / f'{Path(image).stem}.sqlite')
                store.set_enabled(manifest.id, task.id, True)
                runtime = Runtime(store, Mock())
                watchdog = threading.Timer(10, stop.set)
                watchdog.start()
                try:
                    with self.assertRaises(Cancelled):
                        runtime.run(manifest, Pack(), task.id, device,
                                    self.data_dir, stop=stop)
                    self.assertEqual([char.name for char in hosts[0].task.chars], names)
                    for name in ('_run_combat', 'perform_combat_rotation', 'perform', 'do_perform'):
                        self.assertIn(name, call_stack)
                    self.assertTrue(any(action.kind.endswith('_down') for action in device.actions))
                    self.assertFalse(device.held)
                    device.release_all.assert_called_once()
                    self.assertTrue(store.enabled(manifest.id, task.id))
                    self.assertEqual(store.history()[0]['status'], 'cancelled')
                    self.assertEqual(hosts[0].task._error_count, 0)
                finally:
                    watchdog.cancel()
                    store.close()


if __name__ == '__main__':
    unittest.main()
