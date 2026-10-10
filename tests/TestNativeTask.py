"""Native task API over real pack vision and replayed device input."""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from gameframe.api import TaskContext
from gameframe.devices.replay import ReplayDevice
from src.runtime.native_combat_executor import NativeCombatExecutor
from src.runtime.native_config import Config
from src.runtime.native_errors import TaskDisabledException, WaitFailedException
from src.runtime.native_task import NativeTriggerTask
from src.vision.features import FeatureSet


ROOT = Path(__file__).resolve().parents[1]
FRAME = ROOT / 'assets/images/logout_power_icon.png'
COCO = ROOT / 'assets/coco_annotations.json'


class CombatTask(NativeTriggerTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config['_enabled'] = True
        self.default_config['Use Liberation'] = True

    def run(self):
        found = self.find_one('logout_power_icon', threshold=.6)
        self.click_box(found, after_sleep=0, down_time=0)
        self.send_key('e', down_time=0)
        return found


class TestNativeTask(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data_dir = Path(temp.name)
        previous = Config.config_folder
        self.addCleanup(setattr, Config, 'config_folder', previous)
        Config.config_folder = self.data_dir / 'configs'
        self.events = []
        self.stop = threading.Event()
        self.device = ReplayDevice([FRAME, FRAME])
        context = TaskContext(self.device, {}, self.data_dir, self.stop,
                              'native-test', self.events.append)
        feature_set = FeatureSet(False, COCO, .002, .002,
                                 default_threshold=.7)
        self.executor = NativeCombatExecutor(
            context, feature_set=feature_set,
            stop_exception=TaskDisabledException,
            wait_exception=WaitFailedException)
        self.task = CombatTask(
            self.executor, SimpleNamespace(tr=lambda message: message),
            ocr_engine=SimpleNamespace(ocr=lambda image: [[]]),
            global_configs={}, supported_ratio=16 / 9)
        self.task.after_init()

    def test_real_image_match_to_replay_actions_and_evidence(self):
        found = self.task.run()
        self.assertEqual(found.name, 'logout_power_icon')
        self.assertEqual(found.center(), (102, 1357))
        kinds = [action.kind for action in self.device.actions]
        self.assertEqual(kinds, ['move_client', 'button_down', 'button_up',
                                 'key_down', 'key_up'])
        self.assertEqual(self.device.held, set())
        screenshot = self.task.screenshot('native/match')
        self.assertTrue(screenshot.is_file())
        self.assertEqual(screenshot, self.data_dir / 'okww监控室' / 'native' / 'match.png')
        self.assertTrue(screenshot.read_bytes().startswith(b'\x89PNG'))
        self.assertEqual(self.task.info_get('Error'), None)

    def test_config_lifecycle_and_explicit_stop(self):
        self.assertTrue(self.task.enabled)
        self.assertIs(self.executor.current_task, self.task)
        self.assertEqual(self.task.config['Use Liberation'], True)
        self.task.disable()
        path = self.data_dir / 'configs' / 'CombatTask.json'
        self.assertFalse(json.loads(path.read_text(encoding='utf-8'))['_enabled'])
        with self.assertRaises(TaskDisabledException):
            self.task.next_frame()

    def test_wait_uses_fresh_replay_frame(self):
        found = self.task.wait_feature('logout_power_icon', threshold=.6,
                                       time_out=1)
        self.assertEqual(found.center(), (102, 1357))
        self.assertEqual(self.device.sequence, 1)

    def test_wide_screen_coordinates_use_production_anchor(self):
        self.executor.width, self.executor.height = 3440, 1440
        box = self.task.box_of_screen(.5, .5, .6, .6)
        self.assertEqual((box.x, box.y, box.width, box.height),
                         (1280, 720, 256, 144))

    def test_browser_detection_uses_preferred_device(self):
        preferred = {'device': 'browser'}
        self.executor.device_manager = SimpleNamespace(
            get_preferred_device=lambda: preferred)
        self.assertTrue(self.task.is_browser())
        preferred['device'] = 'windows'
        self.assertFalse(self.task.is_browser())

    def test_ocr_threshold_uses_mutable_engine_setting(self):
        self.assertEqual(self.task.ocr_default_threshold, .2)
        self.task.ocr_default_threshold = .65
        self.assertEqual(self.task._ocr.ocr_default_threshold, .65)

    def test_jiyan_relative_middle_click_contract(self):
        self.executor.width, self.executor.height = 200, 100
        self.task.middle_click_relative(.5, .5, down_time=0)
        self.assertEqual([(action.kind, dict(action.values)) for action in self.device.actions], [
            ('move_client', {'x': 100, 'y': 50}),
            ('button_down', {'button': 'middle'}), ('button_up', {'button': 'middle'})])
        self.assertFalse(self.device.held)

    def test_foreground_text_scroll_and_swipe_replay(self):
        self.executor.width, self.executor.height = 200, 100
        self.task.input_text('无妄者')
        self.task.scroll_relative(.75, .5, 3)
        self.task.scroll(20, 30, -2)
        sleeps = []
        original_sleep = self.executor.sleep

        def record_sleep(seconds):
            sleeps.append((seconds, bool(self.device.held)))
            original_sleep(seconds)

        self.executor.sleep = record_sleep
        self.task.swipe_relative(.1, .2, .5, .6, duration=.02,
                                 settle_time=.03)

        actions = self.device.actions
        self.assertEqual([(action.kind, dict(action.values)) for action in actions[:5]], [
            ('text', {'text': '无妄者'}),
            ('move_client', {'x': 150, 'y': 50}), ('scroll', {'clicks': 3}),
            ('move_client', {'x': 20, 'y': 30}), ('scroll', {'clicks': -2})])
        self.assertEqual([action.kind for action in actions[5:]],
                         ['move_client', 'button_down', 'move_client',
                          'move_client', 'button_up'])
        self.assertEqual(dict(actions[5].values), {'x': 20, 'y': 20})
        self.assertEqual(dict(actions[-2].values), {'x': 100, 'y': 60})
        self.assertIn((.03, True), sleeps)
        self.assertEqual(sleeps[-1], (.1, False))
        self.assertEqual(self.device.held, set())

    def test_swipe_releases_button_when_stop_interrupts_movement(self):
        original_submit = self.device.submit

        def stop_after_held_move(action):
            original_submit(action)
            if action.kind == 'move_client' and self.device.held:
                self.stop.set()

        self.device.submit = stop_after_held_move
        with self.assertRaises(TaskDisabledException):
            self.task.swipe(10, 20, 30, 40, duration=.01, after_sleep=0)
        self.assertEqual([action.kind for action in self.device.actions],
                         ['move_client', 'button_down', 'move_client', 'button_up'])
        self.assertEqual(self.device.held, set())

    def test_swipe_releases_button_when_stop_races_button_down(self):
        original_submit = self.device.submit

        def stop_after_button_down(action):
            original_submit(action)
            if action.kind == 'button_down':
                self.stop.set()

        self.device.submit = stop_after_button_down
        with self.assertRaises(TaskDisabledException):
            self.task.swipe(10, 20, 30, 40, duration=.01, after_sleep=0)
        self.assertEqual([action.kind for action in self.device.actions],
                         ['move_client', 'button_down', 'button_up'])
        self.assertEqual(self.device.held, set())


if __name__ == '__main__':
    unittest.main()
