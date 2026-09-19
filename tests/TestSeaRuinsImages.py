"""Offline OCR integration over user-supplied, sanitized screenshots."""
from pathlib import Path
import cv2
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.AutoSeaRuinsTask import AutoSeaRuinsTask
from src.task import sea_ruins_vision as v

ROOT = Path('tests/fixtures/sea_ruins')


class TestSeaRuinsImages(TaskTestCase):
    task_class = AutoSeaRuinsTask
    config = dict(config, debug=True)

    def image(self, name):
        frame = cv2.imread(str(ROOT/f'{name}.png'))
        self.set_image(str(ROOT/f'{name}.png'))
        return frame

    def test_actual_ocr_states(self):
        task = self.task
        self.assertTrue(task._detail(self.image('detail'), 7))
        self.assertFalse(task._detail(self.image('detail'), 8))
        self.assertTrue(task._detail(self.image('next_floor'), 8))
        self.assertTrue(task._map(self.image('map')))
        self.assertTrue(task._upper_end(self.image('exit_front')))
        self.assertTrue(task._prompt(self.image('exit_prompt'), '进入下半海域'))
        self.assertFalse(task._prompt(self.image('exit_front'), '进入下半海域'))
        self.assertTrue(task._result(self.image('result')))
        self.assertTrue(task._token_page(self.image('tokens')))

    def test_map_seven(self):
        for name in ('map', 'map_completed'):
            frame = self.image(name)
            for width, height in ((1280, 720), (1920, 1080), (2560, 1440)):
                with self.subTest(name=name, width=width):
                    boat = self.task._seven_boat(cv2.resize(frame, (width, height)))
                    self.assertIsNotNone(boat)
                    self.assertAlmostEqual(boat[0], .72, delta=.02)
                    self.assertAlmostEqual(boat[1], .51, delta=.03)
            frame = cv2.resize(frame, (1280, 720))
            frame[330:375, 740:795] = 0
            self.assertIsNone(self.task._seven_boat(frame))

    def test_actual_preset_identities_and_applied_team(self):
        task = self.task
        records = task._page_presets(self.image('presets'))
        self.assertGreaterEqual(len(records), 2)
        self.assertEqual(records[0][0].members, ('char_qingxiao', 'char_verina', 'char_denia'))
        self.assertEqual(records[1][0].members, ('char_qingxiao', 'char_denia', 'char_verina'))
        from src.task.sea_ruins import Preset
        frame = self.image('next_floor')
        self.assertTrue(task._members_match(frame, 0, Preset(1, ('char_qingxiao', 'char_denia', 'char_verina'))))
        self.assertTrue(task._members_match(frame, 1, Preset(2, ('yangyang_sp', 'char_rover', 'char_sanhua'))))

    def test_token_counts(self):
        task = self.task
        frame = self.image('tokens')
        values = []
        from src.task.sea_ruins import parse_count
        for x, y, w, h in v.token_cards(frame):
            values.append(task._token_count(frame, (x,y,w,h)))
        self.assertEqual(values[5:9], [2, 1, 2, 2])
        self.assertEqual(values[9:], [-1, -1, -1])

    def test_result_numbers(self):
        from unittest.mock import patch
        task = self.task
        frame = self.image('result')
        task._floor = 7
        with patch.object(task, '_wait', side_effect=lambda probe, *a, **kw: probe(frame)), \
                patch.object(task, 'screenshot'), patch.object(task, 'info_set'):
            self.assertEqual(task._read_result(), (1410, 1490, 2900))
