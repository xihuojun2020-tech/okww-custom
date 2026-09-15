import unittest
import tempfile
from pathlib import Path
import cv2
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.BaseWWTask import BaseWWTask


class TestDailyRecoveryImages(TaskTestCase):
    task_class = BaseWWTask
    config = config

    def test_world_texture_is_not_a_guidebook_tab(self):
        self.set_image('tests/images/daily_recovery/guide_world.png')
        self.assertTrue(self.task.in_team_and_world())
        # The old 0.30 threshold matches this world's terrain at about 0.33.
        self.assertIsNotNone(self.task.find_one('gray_book_quest', box='box_gray_book', threshold=.3))
        self.assertIsNone(self.task._guidebook_tab('gray_book_quest', self.task.frame))

    def test_actual_guidebook_has_page_structure(self):
        self.set_image('tests/images/daily_recovery/guide_daily.png')
        self.assertIsNotNone(self.task._guidebook_tab('gray_book_quest', self.task.frame))
        self.assertIsNotNone(self.task._guidebook_tab('gray_book_boss', self.task.frame))

    def test_all_three_failed_accounts_and_scaled_guidebook(self):
        # Resized screenshots exercise image scaling, not Windows DPI behavior.
        with tempfile.TemporaryDirectory() as folder:
            for name in ('guide_world', 'guide_a2', 'guide_a3', 'guide_daily'):
                original = cv2.imread(f'tests/images/daily_recovery/{name}.png')
                for height in (720, 900, 1080, 1440):
                    with self.subTest(name=name, height=height):
                        path = Path(folder) / f'{name}-{height}.png'
                        cv2.imwrite(str(path), cv2.resize(original, (height * 16 // 9, height)))
                        self.set_image(str(path))
                        found = self.task._guidebook_tab('gray_book_quest', self.task.frame)
                        self.assertEqual(found is not None, name == 'guide_daily')
                        if name != 'guide_daily':
                            self.assertTrue(self.task.in_team_and_world())

    def test_nest_map_has_travel_not_team_action(self):
        self.set_image('tests/images/daily_recovery/nest_map.png')
        self.assertIsNone(self.task.find_one('team_start_challenge'))
        self.assertIsNotNone(self.task._travel_button(self.task.frame))
        self.assertIsNone(self.task._single_challenge_entry(self.task.frame))

    def test_tacet_disabled_reason_is_readable(self):
        self.set_image('tests/images/daily_recovery/tacet_unreachable.png')
        with self.assertRaisesRegex(RuntimeError, '无法|不可'):
            self.task._check_travel_unavailable(self.task.frame)

    def test_reward_overlay_keeps_positive_world_evidence(self):
        self.set_image('tests/images/daily_recovery/world_overlay.png')
        self.assertTrue(self.task.in_team_and_world())
        self.assertTrue(self.task.in_world())
        self.assertFalse(self.task.in_realm())

    def test_existing_weekly_formation_still_has_challenge_action(self):
        self.set_image('tests/images/weekly_boss/team.png')
        self.assertIsNotNone(self.task._team_start_button(self.task.frame))


if __name__ == '__main__':
    unittest.main()
