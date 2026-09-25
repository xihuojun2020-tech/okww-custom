"""Offline OCR integration over user-supplied, sanitized screenshots."""
from pathlib import Path
import cv2
import numpy as np
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.AutoSeaRuinsTask import AutoSeaRuinsTask
from src.task import sea_ruins_vision as v
from src.task.sea_ruins import ENDLESS

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
        self.assertTrue(task._token_page(self.image('tokens_unavailable')))
        self.assertFalse(task._token_page(self.image('detail')))

    def test_detail_start_floor(self):
        for name, expected in (('detail', 7), ('start_eight', 8), ('next_floor', 8),
                               ('detail_eleven', 11), ('detail_endless', ENDLESS)):
            frame = self.image(name)
            for height in (720, 1080, 1440):
                self.assertEqual(self.task._detail_floor(cv2.resize(frame, (height*16//9, height))), expected)
        for name in ('map', 'tokens', 'presets_september20'):
            self.assertIsNone(self.task._detail_floor(self.image(name)))

    def test_failed_run_preset_and_team_identities(self):
        frame = self.image('presets_september20')
        expected = [('char_cartethyia', 'char_ciaccona', 'char_rover'),
                    ('char_phrolova', 'char_cantarella', 'char_douling'),
                    ('Augusta', 'char_iuno', 'char_shorekeeper')]
        from src.task.sea_ruins import Preset
        for height in (720, 1080, 1440):
            resized = cv2.resize(frame, (height*16//9, height))
            with self.subTest(height=height):
                records = self.task._page_presets(resized)
                self.assertEqual([p.members for p, _ in records[:3]], expected)
                self.assertTrue(all(p.valid for p, _ in records[:3]))
                self.assertTrue(self.task._members_match(resized, 0, Preset(1, expected[0])))
                self.assertTrue(self.task._members_match(resized, 1, Preset(3, expected[2])))

    def test_september25_applied_preset(self):
        from src.task.sea_ruins import Preset
        frame = self.image('preset_applied_20260925')
        expected = ('char_yuanwu', 'char_galbrena', 'char_verina')
        cards = v.preset_portraits(frame, self.task._page_presets(frame)[1][1])
        self.assertFalse(self.task._members_match(frame, 0, Preset(2, expected)))
        self.assertTrue(self.task._members_match(frame, 0, Preset(2, expected), cards))
        self.assertFalse(self.task._members_match(frame, 1, Preset(2, expected), cards))

    def test_zani_reference_is_not_remapped_to_shorekeeper(self):
        import numpy as np
        from ok.feature.FeatureSet import FeatureSet
        features = FeatureSet(False, 'assets/coco_annotations.json', 0, 0)
        reference = features.get_feature_by_name(np.zeros((1440, 2560, 3), np.uint8), 'char_zani').mat
        for height in (64, 90, 130):
            avatar = cv2.resize(reference, None, fx=height/reference.shape[0], fy=height/reference.shape[0])
            self.assertEqual(self.task._identify_character(avatar)[0], 'char_zani')

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

    def test_completed_detail(self):
        frame = self.image('detail_completed')
        self.task._floor = 7
        for size in ((1280, 720), (1920, 1080), (2560, 1440)):
            resized = cv2.resize(frame, size)
            self.assertTrue(self.task._detail(resized, 7))
            self.assertFalse(self.task._detail(resized, 8))
            self.assertIsNotNone(self.task._challenge_button(resized))

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

    def test_inventory_without_clicks(self):
        from unittest.mock import patch
        frame = self.image('tokens')
        for height in (720, 1080, 1440):
            with patch.object(self.task, 'click_relative') as click:
                records = self.task._page_tokens(cv2.resize(frame, (height*16//9, height)))
                self.assertEqual([t.name for t, _ in records], [
                    '镌刻者-长夜孤灯', '希冀者-长夜孤灯', '编造者-长夜孤灯', '慰藉者-长夜孤灯',
                    '审判-遗落令旗', '布道-遗落令旗', '游猎-遗落令旗'])
                self.assertEqual([t.remaining for t, _ in records], [2, 1, 2, 2, -1, -1, -1])
                click.assert_not_called()

    def test_thin_category_highlight_is_not_a_token_card(self):
        frame = np.zeros((1152, 2048, 3), np.uint8)
        frame[424:431, 974:1116] = (255, 120, 30)
        self.assertEqual(v.token_cards(frame), [])

    def test_unlock_and_sea_identity(self):
        frame = cv2.imread(str(ROOT/'unlock.png'))
        for height in (720, 1080, 1440):
            self.assertTrue(self.task._unlock_popup(cv2.resize(frame, (height*16//9, height))))
        for name in ('detail', 'tokens', 'result'):
            frame = self.image(name)
            self.assertFalse(self.task._unlock_popup(frame))
            self.assertFalse(v.sea_world(frame))
        for name in ('exit_front', 'exit_side', 'exit_low', 'exit_prompt'):
            self.assertTrue(v.sea_world(self.image(name)), name)

    def test_result_numbers(self):
        from unittest.mock import patch
        task = self.task
        frame = self.image('result')
        task._floor = 7
        with patch.object(task, '_wait', side_effect=lambda probe, *a, **kw: probe(frame)), \
                patch.object(task, 'screenshot'), patch.object(task, 'info_set'):
            self.assertEqual(task._read_result(), (1410, 1490, 2900))
