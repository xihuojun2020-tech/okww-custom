import tempfile
from pathlib import Path

import cv2
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.SkipDialogTask import AutoDialogTask


class TestStorySkipImages(TaskTestCase):
    task_class = AutoDialogTask
    config = config

    def test_actual_task_recognizes_all_three_scenes_without_false_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            for scene in ('normal', 'letterbox', 'choices_green'):
                original = cv2.imread(f'tests/fixtures/story_skip/{scene}.png')
                for height in (720, 1080, 1440, 2160):
                    with self.subTest(scene=scene, height=height):
                        frame = cv2.resize(original, (height*16//9, height))
                        path = Path(temp) / 'frame.png'
                        cv2.imwrite(str(path), frame)
                        self.set_image(str(path))
                        self.task._skip_requested = False
                        self.assertFalse(self.task.in_team_and_world())
                        self.assertIsNone(self.task._skip_confirmation())
                        button = self.task.find_skip()
                        self.assertIsNotNone(button)
                        self.assertLess(button.center()[0]/frame.shape[1], .1)
                        expected_y = .061 if scene == 'normal' else .170
                        self.assertAlmostEqual(button.center()[1]/height, expected_y, delta=.01)

    def test_right_controls_cannot_drive_task_when_left_skip_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            for scene in ('normal', 'letterbox', 'choices_green'):
                frame = cv2.imread(f'tests/fixtures/story_skip/{scene}.png')
                frame[:160, :200] = 0
                path = Path(temp) / 'negative.png'
                cv2.imwrite(str(path), frame)
                self.set_image(str(path))
                self.assertIsNone(self.task.find_skip(), scene)
