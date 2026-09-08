"""Only sanitized game UI regions are stored; no game actions are performed."""
import unittest
import tempfile
from pathlib import Path

import cv2

from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.WeeklyBossTask import WeeklyBossTask
from src.task.weekly_boss import WEEKLY_BOSSES, parse_remaining, parse_cost, parse_stamina, match_target_button

config['debug'] = True


class TestWeeklyBossImages(TaskTestCase):
    task_class = WeeklyBossTask
    config = config

    def load(self, name):
        self.set_image(f'tests/images/weekly_boss/{name}.png')

    def test_guidebook_names_and_counts(self):
        for page, indices in ((1, (0, 1, 2)), (2, (3, 4, 5)), (3, (6, 7, 8, 9))):
            self.load(f'list{page}')
            self.assertEqual(parse_remaining(self.task._text(self.task.BOOK_COUNT)), 3)
            boxes = self.task._ocr(self.task.LIST)
            for index in indices:
                with self.subTest(page=page, target=WEEKLY_BOSSES[index].name):
                    self.assertIsNotNone(match_target_button(boxes, WEEKLY_BOSSES[index].name, self.task.height),
                                         [b.name for b in boxes])

    def test_detail_preserves_default_difficulty(self):
        self.load('detail')
        self.assertTrue(self.task._detail_ready(WEEKLY_BOSSES[1]))
        self.assertEqual(parse_remaining(self.task._text(self.task.DETAIL_COUNT)), 3)
        self.assertEqual(parse_cost(self.task._text(self.task.COST)), 60)
        self.assertEqual(parse_stamina(self.task._text(self.task.STAMINA)), 228)

    def test_team_start(self):
        self.load('team')
        self.assertIsNotNone(self.task._button(self.task.START, '开启挑战'))

    def test_claim_is_the_f_interaction(self):
        self.load('claim')
        self.assertTrue(self.task._reward_available())

    def test_settlement_has_both_actions_rewards_and_stamina(self):
        self.load('settlement')
        self.assertTrue(self.task._settlement())
        self.assertEqual(self.task.get_settlement_stamina(), 169)

    def test_real_task_has_only_weekly_controls(self):
        from src.gui.navigation_sections import classify_task
        self.assertEqual(classify_task(self.task), 'tests')
        self.assertNotIn('Repeat Farm Count', self.task.default_config)
        self.assertNotIn('Boss Level', self.task.default_config)
        self.assertNotIn('Exit After Task', self.task.default_config)
        self.assertEqual(self.task.supported_languages, ['zh_CN'])

    def test_claim_and_result_at_other_16x9_resolutions(self):
        with tempfile.TemporaryDirectory() as directory:
            for height in (720, 1080, 2160):
                for name in ('claim', 'settlement', 'detail'):
                    with self.subTest(height=height, name=name):
                        source = cv2.imread(f'tests/images/weekly_boss/{name}.png')
                        resized = cv2.resize(source, (height * 16 // 9, height))
                        path = str(Path(directory) / 'scaled.png')
                        self.assertTrue(cv2.imwrite(path, resized))
                        self.set_image(path)
                        if name == 'claim':
                            self.assertTrue(self.task._reward_available())
                        elif name == 'settlement':
                            self.assertTrue(self.task._settlement())
                            self.assertEqual(self.task.get_settlement_stamina(), 169)
                        else:
                            self.assertTrue(self.task._detail_ready(WEEKLY_BOSSES[1]))
                            self.assertEqual(parse_remaining(self.task._text(self.task.DETAIL_COUNT)), 3)

    def test_chinese_dropdown_uses_names_not_internal_ids(self):
        import gettext
        catalog = gettext.translation('ok', localedir='i18n', languages=['zh_CN'])
        self.assertEqual(catalog.gettext('Weekly Boss Challenge'), '周本挑战')
        for boss in WEEKLY_BOSSES:
            self.assertEqual(catalog.gettext(boss.key), boss.name)


if __name__ == '__main__':
    unittest.main()
