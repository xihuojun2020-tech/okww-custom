import unittest
from unittest.mock import patch

import cv2
import numpy as np
from ok.feature.FeatureSet import FeatureSet
from src.Labels import Labels
from src.char.BaseChar import BaseChar, Elements
from src.char.CharFactory import char_dict
from src.char.JingRan import JingRan
from src.task.AutoAbyssTask import AutoAbyssTask


class OfflineAbyss(AutoAbyssTask):
    @property
    def height(self):
        return self.test_height


class TestJingRan(unittest.TestCase):
    def test_upstream_battle_portrait_loads_and_matches(self):
        original = cv2.imread('assets/images/characters/jingran_source_34.png')
        self.assertIsNotNone(original)
        features = FeatureSet(False, 'assets/coco_annotations.json', .002, .002, default_threshold=.7)
        for height in (720, 1080, 1440, 2160):
            frame = cv2.resize(original, (height * 16 // 9, height))
            with self.subTest(height=height):
                self.assertTrue(features.find_one_feature(frame, Labels.char_jingran, threshold=.8))

    def test_limited_portraits_against_all_registered_characters(self):
        original = cv2.imread('tests/fixtures/jingran/limited_roster.png')
        expected = [Labels.char_verina, Labels.char_qingxiao, Labels.char_denia,
                    Labels.char_jingran, Labels.char_iuno, Labels.char_shorekeeper, Labels.yangyang_sp]
        # Source capture is 2560x1440; fixture retains the first card row only.
        for height in (720, 1080, 1440, 2160):
            frame = np.zeros((height, height * 16 // 9, 3), np.uint8)
            fs = FeatureSet(False, 'assets/coco_annotations.json', .002, .002, default_threshold=.7)
            task = OfflineAbyss.__new__(OfflineAbyss)
            task.test_height = height
            task._avatar_orb = cv2.ORB_create(nfeatures=300, edgeThreshold=5, fastThreshold=5)
            task._avatar_matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
            task._character_descriptors = None
            task.get_feature_by_name = lambda name: fs.get_feature_by_name(frame, name)
            for index, name in enumerate(expected):
                x = int((.0785 + index * .1221 + .105 * .02) * 2560) - int(.078 * 2560)
                y = int((.1285 + .2275 * .01) * 1440) - int(.125 * 1440)
                right = int((.0785 + index * .1221 + .105 * .98) * 2560) - int(.078 * 2560)
                bottom = int((.1285 + .2275 * .78) * 1440) - int(.125 * 1440)
                crop = cv2.resize(original[y:bottom, x:right], None, fx=height/1440, fy=height/1440)
                with self.subTest(height=height, name=name):
                    result = task._identify_character(crop)
                    if name == Labels.char_jingran or height == 1440:
                        self.assertIsNotNone(result)
                        self.assertEqual(result[0], name)
                    else:
                        # Negative controls: adding JingRan must not capture adjacent identities.
                        self.assertTrue(result is None or result[0] != Labels.char_jingran)
            self.assertIsNotNone(fs.get_feature_by_name(frame, Labels.char_jingran))
        self.assertIs(char_dict[Labels.char_jingran]['cls'], JingRan)
        self.assertEqual(char_dict[Labels.char_jingran]['ring_index'], Elements.FIRE)

    def rotation(self, liberation):
        char = JingRan(None, 0)
        clock = [100.0]
        events = []
        char.wait_intro = lambda: None
        char.click_echo = lambda **kwargs: None
        char.time_elapsed_accounting_for_freeze = lambda start: clock[0] - start
        char.cycle_start = lambda: None
        char.cycle_sleep = lambda: clock.__setitem__(0, clock[0] + 1)
        char.is_forte_full = lambda: not events
        char.heavy_click_forte = lambda: events.append('heavy')
        char.click_liberation = lambda **kwargs: events.append('liberation') or liberation
        char.click_resonance = lambda **kwargs: (True,)
        char.continues_normal_attack = lambda duration: events.append('followup')
        char.switch_next_char = lambda: events.append('switch')
        with patch('src.char.JingRan.time.time', side_effect=lambda: clock[0]):
            char.do_perform()
        return clock[0] - 100, events

    def test_priority_and_successful_liberation_window(self):
        duration, events = self.rotation(True)
        self.assertEqual(events[:2], ['heavy', 'liberation'])
        self.assertEqual(events.count('liberation'), 1)
        self.assertEqual(duration, 16)
        self.assertIn('followup', events)
        self.assertEqual(events[-1], 'switch')

    def test_failed_liberation_stops_after_build_budget(self):
        duration, events = self.rotation(False)
        self.assertEqual(duration, 8)
        self.assertEqual(events[-1], 'switch')

    def test_shared_heavy_releases_mouse_on_interruption(self):
        from unittest.mock import Mock
        task = Mock()
        task.wait_until.side_effect = RuntimeError('stopped')
        char = BaseChar(task, 0)
        with self.assertRaisesRegex(RuntimeError, 'stopped'):
            char.heavy_click_forte(lambda: True)
        task.mouse_down.assert_called_once()
        task.mouse_up.assert_called_once()
