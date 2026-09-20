import unittest
from pathlib import Path
from unittest.mock import Mock

import cv2
import numpy as np

from src.task.SkipDialogTask import AutoDialogTask
from src.task.story_skip import find_hex_skip, find_summary_skip
from tests import TestBackgroundNavigationTasks as background_tests


FIXTURES = Path(__file__).parent / 'fixtures/story_skip'


class TestStorySkip(unittest.TestCase):
    def summary(self):
        return cv2.imread(str(FIXTURES / 'summary.png'))

    def icon_scene(self, x=90, y=30, scale=.5):
        frame = np.full((720, 1280, 3), 40, np.uint8)
        crop = cv2.imread(str(FIXTURES / 'icon_crop.png'))
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        h, w = crop.shape[:2]
        frame[y:y+h, x:x+w] = crop
        return frame

    def test_real_summary_clicks_right_button_at_multiple_resolutions(self):
        for height in (720, 1080, 1440, 2160):
            frame = cv2.resize(self.summary(), (height*16//9, height))
            button = find_summary_skip(frame)
            self.assertIsNotNone(button, height)
            x, y = button.center()
            self.assertAlmostEqual(x/frame.shape[1], .678, delta=.015)
            self.assertAlmostEqual(y/height, .706, delta=.015)
            self.assertIsNone(find_hex_skip(frame))

    def test_title_and_right_label_are_both_required(self):
        for rect in ((480, 170, 800, 260), (730, 460, 1024, 555)):
            frame = self.summary()
            x1, y1, x2, y2 = rect
            frame[y1:y2, x1:x2] = 0
            self.assertIsNone(find_summary_skip(frame))
        frame = self.summary()
        frame[489:530, 765:970] = frame[489:530, 310:515]
        self.assertIsNone(find_summary_skip(frame), 'continue watching is not skip')

    def test_icon_crop_in_hud_and_not_in_central_content(self):
        for x in (60, 1140):
            for scale in (.4, .5, .7, 1):
                frame = self.icon_scene(x=x, scale=scale)
                self.assertIsNotNone(find_hex_skip(frame), (x, scale))
        for height in (1080, 1440, 2160):
            frame = cv2.resize(self.icon_scene(), (height*16//9, height))
            button = find_hex_skip(frame)
            self.assertIsNotNone(button)
            self.assertAlmostEqual(button.center()[0]/frame.shape[1], .091, delta=.01)
        self.assertIsNone(find_hex_skip(self.icon_scene(x=600, y=320)))
        self.assertIsNone(find_hex_skip(np.zeros((720, 1280, 3), np.uint8)))

    def test_other_activity_screens_are_not_story_skip(self):
        for path in (FIXTURES.parent / 'resonance_simulation').glob('*.png'):
            frame = cv2.imread(str(path))
            self.assertIsNone(find_summary_skip(frame), path.name)
            self.assertIsNone(find_hex_skip(frame), path.name)

    def task(self):
        harness = background_tests.TestBackgroundNavigationTasks()
        self.addCleanup(harness.doCleanups)
        task = harness.task(AutoDialogTask)
        task.has_eye_time = 0
        task.skip_message = Mock(return_value=False)
        task.check_skip = Mock(return_value=False)
        return task, harness

    def test_real_detection_drives_two_separate_verified_clicks(self):
        task, harness = self.task()
        task.require_game_frame.side_effect = lambda: cv2.resize(
            self.icon_scene() if task.click_box.call_count == 0 else self.summary(), (1920, 1080))
        for _ in range(3):
            harness.tick(task)
        self.assertEqual(task.click_box.call_count, 1)
        self.assertEqual(task.click_box.call_args.args[0].name, 'skip_dialog_hex')
        harness.tick(task)
        self.assertEqual(task.click_box.call_count, 1)
        for _ in range(3):
            harness.tick(task)
        self.assertEqual(task.click_box.call_count, 2)
        self.assertEqual(task.click_box.call_args.args[0].name, 'skip_story_summary')
        task.in_team_and_world.return_value = True
        harness.tick(task)
        self.assertIsNone(task._ui_tick_navigation)
        task.sleep.assert_not_called()

    def test_summary_already_open_is_supported_without_prior_click(self):
        task, harness = self.task()
        task.require_game_frame.return_value = cv2.resize(self.summary(), (1920, 1080))
        for _ in range(3):
            harness.tick(task)
        task.click_box.assert_called_once()
        self.assertEqual(task.click_box.call_args.args[0].name, 'skip_story_summary')

    def test_world_guard_and_legacy_button_priority(self):
        task, harness = self.task()
        task.in_team_and_world.return_value = True
        task.require_game_frame.return_value = self.icon_scene()
        harness.tick(task)
        task.click_box.assert_not_called()
        legacy = object()
        task.find_one.return_value = legacy
        task.find_hex_skip = Mock(side_effect=AssertionError('legacy path must remain first'))
        self.assertIs(task.find_skip(), legacy)

    def test_blocking_quest_path_uses_same_summary_detector(self):
        task, _ = self.task()
        task.require_game_frame.return_value = self.summary()
        self.assertTrue(task.skip_confirm())
        self.assertEqual(task.click_box.call_args.args[0].name, 'skip_story_summary')


if __name__ == '__main__':
    unittest.main()
