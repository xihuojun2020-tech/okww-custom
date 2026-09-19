import unittest
import tempfile
from pathlib import Path
import cv2
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.DailyTask import DailyTask


class TestDailyRegressionImages(TaskTestCase):
    task_class = DailyTask
    config = config

    def load(self, name):
        self.set_image(f'tests/images/daily_regression/{name}.png')

    def test_enemy_page_is_accepted_and_daily_is_not(self):
        self.load('enemy_page')
        self.assertTrue(self.task._guidebook_content('gray_book_all_monsters', self.task.frame))
        self.assertFalse(self.task._daily_page_ready(self.task.frame))
        self.load('unclaimed_zero')
        self.assertFalse(self.task._guidebook_content('gray_book_all_monsters', self.task.frame))

    def test_actual_a3_daily_and_reward_animation_are_distinguished(self):
        from src.task.daily_observation import claimable_tiers
        for name, expected in (('reward_daily', None), ('reward_opening', 'opening'),
                               ('reward_ready', 'ready')):
            with self.subTest(frame=name):
                self.load(name)
                self.assertEqual(self.task._daily_reward_overlay(self.task.frame), expected)
                self.assertEqual(self.task._daily_page_ready(self.task.frame), expected is None)
                self.assertEqual(claimable_tiers(self.task.frame),
                                 [20, 40, 60, 80, 100] if expected is None else [])

    def test_zero_and_claim_buttons_at_supported_sizes(self):
        original = cv2.imread('tests/images/daily_regression/unclaimed_zero.png')
        with tempfile.TemporaryDirectory() as folder:
            for h in (720, 900, 1080, 1440):
                with self.subTest(height=h):
                    path = Path(folder) / f'{h}.png'
                    cv2.imwrite(str(path), cv2.resize(original, (h*16//9, h)))
                    self.set_image(str(path))
                    self.assertEqual(self.task.get_total_daily_points(attempts=1), 0)
                    self.assertGreaterEqual(len(self.task._daily_objective_claim_buttons()), 4)

    def test_revive_confirm_is_identified_on_actual_dialog(self):
        self.load('revive')
        self.assertIsNotNone(self.task._local_revive_button())
        self.load('unclaimed_zero')
        self.assertIsNone(self.task._local_revive_button())

    def test_existing_ninety_points_and_go_buttons_are_not_regressed(self):
        original = cv2.imread('tests/images/daily_followup/echo_missing.png')
        with tempfile.TemporaryDirectory() as folder:
            for h in (720, 900, 1080, 1440):
                with self.subTest(height=h):
                    path = Path(folder) / f'{h}.png'
                    cv2.imwrite(str(path), cv2.resize(original, (h*16//9, h)))
                    self.set_image(str(path))
                    self.assertEqual(self.task.get_total_daily_points(attempts=1), 90)
                    self.assertEqual(self.task._daily_objective_claim_buttons(), [])


if __name__ == '__main__':
    unittest.main()
