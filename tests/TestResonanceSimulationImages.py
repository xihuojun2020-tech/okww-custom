from pathlib import Path

import cv2
from config import config
from ok.test.TaskTestCase import TaskTestCase

from src.task.ResonanceSimulationTask import ResonanceSimulationTask
from src.task.resonance_simulation import liberation_ready, skill_bar_visible


class TestResonanceSimulationImages(TaskTestCase):
    task_class = ResonanceSimulationTask
    config = config

    def test_real_activity_images(self):
        root = Path('tests/fixtures/resonance_simulation')
        for path in root.glob('*.png'):
            with self.subTest(path=path.name):
                frame = cv2.imread(str(path))
                self.assertTrue(skill_bar_visible(frame))
                self.assertEqual(liberation_ready(frame), path.stem in ('factor', 'currency'))
