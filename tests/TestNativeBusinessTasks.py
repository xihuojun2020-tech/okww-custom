"""Real business branches with native services, local OCR and offline devices.

Run in a fresh interpreter: python -I with the repository inserted into sys.path.
All writable account, proof, model cache and material data uses one temporary root.
"""

import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from gameframe.api import Cancelled, TaskContext
from gameframe.devices.replay import ReplayDevice
from gameframe.packages import PackageManifest, TaskDefinition
from gameframe.runtime import Runtime
from gameframe.state import RunStore
from src.combat.settings import COMBAT_GLOBAL_DEFAULTS, TEMPLATE_MATCHING_DEFAULTS
from src.runtime.native_combat_host import NativeCombatHost
from tests.TestNativeWWOneTime import BlockApplicationImports


ROOT = Path(__file__).resolve().parents[1]


class TestNativeBusinessTasks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.data_dir = Path(cls.temp.name)
        cls.old_cwd = Path.cwd()
        cls.blocker = BlockApplicationImports()
        sys.meta_path.insert(0, cls.blocker)
        from tests.fixture_support import make_account_environment
        from src.runtime.account_runtime_bootstrap import prepare_native_account_runtime
        from scripts.build_gamepack import source_metadata
        make_account_environment(cls.data_dir)
        cls.runtime = prepare_native_account_runtime(cls.data_dir, 'offline-business-test')
        cls.entries = tuple(f"{task['module']}:{task['class']}"
                            for task in source_metadata(ROOT)['tasks'] if 'module' in task)
        os.chdir(cls.data_dir)
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr
        cls.engine = ONNXPaddleOcr(use_angle_cls=False, use_npu=False, use_openvino=True)

    @classmethod
    def tearDownClass(cls):
        from src.evidence.service import get_evidence_service
        get_evidence_service().close()
        os.chdir(cls.old_cwd)
        sys.meta_path.remove(cls.blocker)
        cls.temp.cleanup()

    def make_host(self, name, relative_image, *, all_tasks=False):
        image = ROOT / relative_image
        self.assertTrue(image.is_file(), str(image))
        device = ReplayDevice([image] * 64)
        events = []
        context = TaskContext(device, {}, self.data_dir, threading.Event(), name, events.append)
        entry = next(entry for entry in self.entries if entry.endswith(':' + name))
        host = NativeCombatHost(
            context, coco_path=ROOT / 'assets/coco_annotations.json',
            global_options=COMBAT_GLOBAL_DEFAULTS, ocr_engine=self.engine,
            ocr_config={'default': {'lib': 'onnxocr'}},
            template_matching=TEMPLATE_MATCHING_DEFAULTS,
            task_entry=entry, registered_tasks=self.entries if all_tasks else (),
            window=SimpleNamespace(hwnd=1, top_hwnd=1, exists=True, visible=True,
                                   hwnd_title='鸣潮 offline fixture', get_capture_origin=lambda: (0, 0)))
        host.task._enabled = True
        return host, device

    def run_until_business_input(self, host, device, *, kind):
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask, CURRENT_ACCOUNT, UNREGISTERED_ACCOUNT
        owner = host.executor.get_task_by_class(MultiAccountDailyTask)
        owner.config[CURRENT_ACCOUNT] = UNREGISTERED_ACCOUNT
        submitted, released = [], []
        submit, release = device.submit, device.release_all
        def stop_at_input(action):
            submit(action)
            if action.kind == kind:
                submitted.append(action)
                host.context.stop.set()
        def release_owned_input():
            released.append(True)
            release()
        device.submit, device.release_all = stop_at_input, release_owned_input
        class Pack:
            def run(self, task_id, context):
                return host.run_once()
        task = TaskDefinition('business', type(host.task).__name__, 'once', {}, frozenset({'frames', 'mouse'}))
        manifest = PackageManifest(ROOT, 'native-business-test', 'Business test', '0.00.00', '',
                                   'AGPL-3.0-or-later', ('windows',), 'native', (task,))
        store = RunStore(self.data_dir / f'{type(host.task).__name__}-run.sqlite')
        try:
            with self.assertRaises(Cancelled):
                Runtime(store, lambda event: None).run(manifest, Pack(), task.id, device,
                                                      self.data_dir, stop=host.context.stop)
        finally:
            store.close()
        self.assertEqual(len(submitted), 1)
        self.assertEqual(len(released), 1)
        self.assertFalse(device.held)
        self.assertFalse(host.task.running)
        return submitted[0]

    def test_character_trial_original_run_reaches_real_roster_drag_and_stops(self):
        host, device = self.make_host('CharacterTrialTask', 'tests/fixtures/character_trial/current_page.png', all_tasks=True)
        action = self.run_until_business_input(host, device, kind='button_down')
        self.assertEqual(action.values['button'], 'left')
        self.assertEqual(host.task.last_result['configured_count'], 5)
        self.assertFalse(host.task.last_result['complete'])
        move = next(action for action in device.actions if action.kind == 'move_client')
        self.assertAlmostEqual(move.values['y'] / host.executor.height, .905, places=3)

    def test_echoes_original_run_reaches_confirmed_single_challenge_and_stops(self):
        host, device = self.make_host('EchoesRemainTask', 'tests/fixtures/echoes_remain/stage1.png', all_tasks=True)
        self.run_until_business_input(host, device, kind='button_down')
        self.assertIsNotNone(host.task.last_result['stage'])
        self.assertFalse(host.task.last_result['activity_complete'])
        move = next(action for action in device.actions if action.kind == 'move_client')
        self.assertGreater(move.values['x'] / host.executor.width, .81)
        self.assertGreater(move.values['y'] / host.executor.height, .87)

    def test_tiangong_original_run_reaches_stage_selection_and_stops(self):
        host, device = self.make_host('TiangongTreasureTask', 'tests/fixtures/tiangong_treasure/page.png', all_tasks=True)
        self.run_until_business_input(host, device, kind='button_down')

    def test_weekly_original_stable_count_reads_two_real_frames(self):
        host, device = self.make_host('WeeklyBossTask', 'tests/images/weekly_boss/list1.png')
        self.assertEqual(host.task._read_remaining(), 3)
        self.assertGreaterEqual(device.sequence, 2)
        self.assertFalse(device.actions)

    def test_account_switch_original_test_entry_reaches_production_service_and_cancels(self):
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask
        from src.runtime.login_flow_service import LoginFlowService
        host, device = self.make_host('TestAccountSwitchTask', 'tests/images/weekly_boss/list1.png', all_tasks=True)
        host.task.config['目标账号'] = 'A1'
        def raw_login_ocr(image):
            return [[([[20, 20], [180, 20], [180, 60], [20, 60]], ('登录', .99)),
                     ([[220, 100], [460, 100], [460, 140], [220, 140]], ('199****0001', .99))]]
        engine = SimpleNamespace(ocr=raw_login_ocr)
        host.executor.ocr_engine = engine
        for task in host.tasks.values():
            task._ocr_service.engine = engine
        codes = (MultiAccountDailyTask._select_and_login_specific.__code__,
                 MultiAccountDailyTask.switch_to_account.__code__,
                 LoginFlowService.switch_to_account.__code__)
        observed = []
        def observe_calls(frame, event, arg):
            if event == 'call' and frame.f_code in codes:
                observed.append(frame.f_code)
                if frame.f_code is codes[-1]:
                    host.context.stop.set()
        previous = sys.getprofile()
        try:
            sys.setprofile(observe_calls)
            with self.assertRaises(Cancelled):
                host.run_once()
        finally:
            sys.setprofile(previous)
            device.release_all()
        self.assertEqual(observed, list(codes))
        self.assertFalse(device.held)
        self.assertFalse(host.task.running)
        self.assertNotEqual(host.task.info.get('状态'), '测试通过 ✓')

    def test_original_controlled_restart_rebinds_and_cancellation_propagates(self):
        from tests.TestWindowsLaunch import TestWindowsLaunch
        from tests.TestGameFrameDevices import FakeCapture
        from src.runtime.native_errors import TaskDisabledException
        device, platform, window, launcher, child, launch, *_ = TestWindowsLaunch().make_device()
        host, _ = self.make_host('MultiAccountDailyTask', 'tests/images/weekly_boss/list1.png', all_tasks=True)
        host.context.device = device
        host.task.hwnd = window
        host.executor.device_manager.hwnd_window = window
        captured_hwnds = []
        def capture_factory(**values):
            captured_hwnds.append(values['window_hwnd'])
            capture = FakeCapture()
            original_start = capture.start_free_threaded
            def start():
                control = original_start()
                capture.emit(np.ones((1080, 1920, 4), dtype=np.uint8))
                return control
            capture.start_free_threaded = start
            return capture
        device._capture_factory = capture_factory
        next_frame = device.next_frame
        def stop_after_recovered_frame(timeout):
            frame = next_frame(timeout)
            host.context.stop.set()
            return frame
        device.next_frame = stop_after_recovered_frame
        with self.assertRaises(TaskDisabledException):
            host.task._restart_game_once()
        self.assertTrue(host.task._game_restart_attempted)
        launch.assert_called_once()
        self.assertEqual(captured_hwnds, [201])
        self.assertEqual(host.task.hwnd.hwnd, 201)
        self.assertIs(host.task.hwnd, window)
        self.assertTrue(host.context.stop.is_set())

    def test_full_production_registry_after_init_uses_only_explicit_root(self):
        host, _ = self.make_host('DailyTask', 'tests/images/weekly_boss/list1.png', all_tasks=True)
        self.assertEqual(len(host.tasks), len(self.entries))
        for cls, task in host.tasks.items():
            self.assertIs(host.executor.get_task_by_class(cls), task)
            self.assertIs(task.executor, host.executor)
            self.assertEqual(Path(task.config.config_file).parent, self.data_dir / 'configs')
        from src.task.MaterialPlannerTask import MaterialPlannerTask
        planner = host.executor.get_task_by_class(MaterialPlannerTask)
        self.assertEqual(planner.repository.root, self.data_dir / 'MaterialPlanner')
        from src.task.TestAccountSwitchTask import TestAccountSwitchTask
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask
        switch = host.executor.get_task_by_class(TestAccountSwitchTask)
        self.assertIs(switch._get_multi_account_task(), host.executor.get_task_by_class(MultiAccountDailyTask))
        self.assertFalse(any(name.split('.')[0] in {'ok', 'PySide6', 'PyQt5', 'PyQt6', 'qfluentwidgets', 'config'}
                             for name in sys.modules))

    def test_character_trial_real_page_and_enter_button_dispatch(self):
        host, device = self.make_host('CharacterTrialTask', 'tests/fixtures/character_trial/current_page.png')
        task = host.task
        task.next_frame()
        self.assertTrue(task._page())
        self.assertFalse(task._intro())
        task._click_button(task.ENTER, '前往试用')
        self.assertEqual([action.kind for action in device.actions],
                         ['move_client', 'button_down', 'button_up'])
        self.assertFalse(device.held)

    def test_tiangong_real_stage_and_formation_recognition(self):
        host, _ = self.make_host('TiangongTreasureTask', 'tests/fixtures/tiangong_treasure/page.png')
        task = host.task
        frame = task.next_frame()
        self.assertTrue(task._page(frame))
        self.assertEqual(task._state(frame, 0), dict(status='pending', score=30415))
        self.assertEqual(task._state(frame, 1), dict(status='pending', score=0))
        formation = cv2.imread(str(ROOT / 'tests/fixtures/tiangong_treasure/formation.png'))
        self.assertTrue(task._formation(formation))
        self.assertFalse(task._result(formation))

    def test_sea_and_abyss_assets_work_from_private_cwd(self):
        sea, _ = self.make_host('AutoSeaRuinsTask', 'tests/fixtures/sea_ruins/detail.png')
        frame = sea.task.next_frame()
        self.assertTrue(sea.task._detail(frame, 7))
        self.assertTrue(sea.task._character_template_descriptors())
        abyss, _ = self.make_host('AutoAbyssTask', 'tests/images/abyss_season_20261004/presets.png')
        self.assertTrue(abyss.task._character_template_descriptors())
        self.assertIsNotNone(abyss.task._hiyuki_preset_descriptor)
        for path in abyss.task._TEMPLATES.values():
            self.assertTrue(path.is_absolute())
            self.assertIsNotNone(cv2.imread(str(path)))

    def test_echoes_real_stage_button_and_private_masked_proof(self):
        host, device = self.make_host('EchoesRemainTask', 'tests/fixtures/echoes_remain/stage1.png')
        task = host.task
        frame = task.next_frame()
        name = task._stage_name(frame)
        self.assertIsNotNone(name)
        button = task._single_button(frame, name)
        self.assertIsNotNone(button)
        task.click(button, after_sleep=0)
        self.assertEqual([action.kind for action in device.actions],
                         ['move_client', 'button_down', 'button_up'])
        task.last_result = {'activity': 'echoes_remain', 'activity_complete': False}
        original = frame.copy()
        task._save_proof(frame)
        proof = Path(task.last_result['proof'])
        self.assertTrue(proof.is_relative_to(self.data_dir))
        self.assertTrue(proof.with_suffix('.json').is_file())
        saved = cv2.imread(str(proof))
        band = round(len(saved) * .025)
        self.assertLess(float(saved[:max(1, band-2)].mean()), 1)
        self.assertLess(float(saved[-max(1, band-2):].mean()), 1)
        self.assertTrue(np.array_equal(frame, original))


if __name__ == '__main__':
    unittest.main()
