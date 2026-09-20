import unittest
from pathlib import Path
from unittest.mock import Mock

import cv2
import numpy as np

from src.task.SkipDialogTask import AutoDialogTask
from src.task.story_skip import find_hex_skip, find_summary_skip, find_skip_warning
from tests import TestBackgroundNavigationTasks as background_tests


FIXTURES = Path(__file__).parent / 'fixtures/story_skip'


class TestStorySkip(unittest.TestCase):
    def warning(self, checked=False):
        frame = cv2.imread(str(FIXTURES / 'warning.png'))
        if checked:
            # Synthetic tick: a real checked-state screenshot has not been provided.
            cv2.line(frame, (562, 396), (567, 401), (30, 30, 30), 2)
            cv2.line(frame, (567, 401), (574, 392), (30, 30, 30), 2)
        return frame

    def test_real_letterboxed_icon_excludes_other_hexagonal_controls(self):
        frame = cv2.imread(str(FIXTURES / 'letterbox.png'))
        for height in (720, 1080, 1440, 2160):
            scaled = cv2.resize(frame, (height*16//9, height))
            button = find_hex_skip(scaled)
            self.assertIsNotNone(button, height)
            x, y = button.center()
            self.assertAlmostEqual(x/scaled.shape[1], .041, delta=.006)
            self.assertAlmostEqual(y/height, .170, delta=.006)
        frame[90:150, :100] = 0
        self.assertIsNone(find_hex_skip(frame), 'right-side controls are not skip')

    def test_warning_positions_and_checkbox_states(self):
        for checked in (False, True):
            for height in (720, 1080, 1440, 2160):
                frame = cv2.resize(self.warning(checked), (height*16//9, height))
                dialog = find_skip_warning(frame)
                self.assertIsNotNone(dialog)
                self.assertIs(dialog.checked, checked)
                self.assertAlmostEqual(dialog.checkbox.center()[0]/frame.shape[1], .444, delta=.01)
                self.assertAlmostEqual(dialog.confirm.center()[0]/frame.shape[1], .657, delta=.01)

    def test_unrelated_warning_or_missing_confirm_never_matches(self):
        for rect in ((398, 318, 869, 345), (586, 386, 715, 407), (815, 439, 866, 465)):
            frame = self.warning()
            x, y, right, bottom = rect
            frame[y:bottom, x:right] = 240
            self.assertIsNone(find_skip_warning(frame))
        frame = self.warning()
        frame[391:404, 562:575] = 200
        self.assertIsNone(find_skip_warning(frame).checked)

    def test_warning_checks_once_then_confirms_on_a_new_frame(self):
        task, harness = self.task()
        task.require_game_frame.side_effect = lambda: cv2.resize(
            self.warning(task.click_box.call_count > 0), (1920, 1080))
        for _ in range(3):
            harness.tick(task)
        self.assertEqual(task.click_box.call_count, 1)
        self.assertEqual(task.click_box.call_args.args[0].name, 'skip_story_checkbox')
        harness.tick(task)
        self.assertEqual(task.click_box.call_count, 1)
        for _ in range(3):
            harness.tick(task)
        self.assertEqual(task.click_box.call_count, 2)
        self.assertEqual(task.click_box.call_args.args[0].name, 'skip_story_warning_confirm')

    def test_lost_checkbox_click_is_not_repeated_or_confirmed(self):
        task, harness = self.task()
        task.require_game_frame.return_value = cv2.resize(self.warning(), (1920, 1080))
        for _ in range(12):
            harness.tick(task)
        task.click_box.assert_called_once()
        self.assertEqual(task.click_box.call_args.args[0].name, 'skip_story_checkbox')

    def test_already_checked_warning_only_confirms(self):
        task, harness = self.task()
        task.require_game_frame.return_value = cv2.resize(self.warning(True), (1920, 1080))
        for _ in range(3):
            harness.tick(task)
        task.click_box.assert_called_once()
        self.assertEqual(task.click_box.call_args.args[0].name, 'skip_story_warning_confirm')

    def test_ambiguous_checkbox_does_not_fall_back_to_generic_confirm(self):
        task, harness = self.task()
        frame = self.warning()
        frame[391:404, 562:575] = 200
        task.require_game_frame.return_value = cv2.resize(frame, (1920, 1080))
        task.find_one.return_value = object()
        for _ in range(4):
            harness.tick(task)
        task.click_box.assert_not_called()
        task.find_one.assert_not_called()
        task.check_skip.assert_not_called()

    def test_summary_can_transition_to_warning_without_skipping_checkbox(self):
        task, harness = self.task()
        task.require_game_frame.side_effect = lambda: cv2.resize(
            self.summary() if task.click_box.call_count == 0 else self.warning(task.click_box.call_count > 1),
            (1920, 1080))
        for _ in range(11):
            harness.tick(task)
        self.assertEqual([c.args[0].name for c in task.click_box.call_args_list],
                         ['skip_story_summary', 'skip_story_checkbox', 'skip_story_warning_confirm'])

    def test_blocking_warning_does_not_toggle_twice(self):
        task, _ = self.task()
        task.require_game_frame.return_value = self.warning()
        self.assertFalse(task.skip_confirm())
        self.assertFalse(task.skip_confirm())
        task.click_box.assert_called_once()
        task.require_game_frame.return_value = self.warning(True)
        self.assertTrue(task.skip_confirm())
        self.assertEqual(task.click_box.call_args.args[0].name, 'skip_story_warning_confirm')

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
