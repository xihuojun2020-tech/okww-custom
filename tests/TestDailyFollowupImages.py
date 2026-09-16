import unittest
import re
import tempfile
import cv2
from pathlib import Path
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.DailyTask import DailyTask
from src.task.daily_observation import claimable_tiers, objective_progress


class TestDailyFollowupImages(TaskTestCase):
    task_class = DailyTask
    config = config

    def load(self, name):
        self.set_image(str(Path('tests/images/daily_followup') / (name + '.png')))

    def test_actual_reward_resource_numbers_are_not_swapped(self):
        self.load('claim_80')
        self.assertEqual((80, 159, 239), self.task.get_stamina(screenshot_on_failure=False))

    def test_activity_page_is_not_resource_page(self):
        self.load('wrong_tab_80')
        self.assertTrue(self.task._daily_page_ready(self.task.frame))
        self.assertFalse(self.task._guidebook_content('gray_book_boss', self.task.frame))
        self.assertEqual((-1, -1, -1), self.task.get_stamina(screenshot_on_failure=False))

    def test_four_claimable_chests_and_missing_echo(self):
        self.load('echo_missing')
        self.assertEqual([20, 40, 60, 80], claimable_tiers(self.task.frame))
        boxes = self.task.ocr(.20, .18, .79, .79)
        self.assertEqual((0, 1), objective_progress(boxes, r'获得任意1个声骸'))
        self.assertTrue(self.task._daily_page_ready(self.task.frame))

    def test_actual_spending_and_story_warning_regions(self):
        self.load('wrong_tab_80')
        boxes=self.task.ocr(.20,.18,.79,.79)
        self.assertEqual(objective_progress(boxes,r'消耗.*180'),(160,180))
        self.load('weekly_story')
        text=''.join(b.name for b in self.task.ocr(.25,.43,.75,.53))
        self.assertIn('提前到达目标位置可能影响剧情体验',text)
        self.assertIn('是否确认',text)
        self.assertEqual(len(self.task.ocr(.55,.59,.76,.67,match=re.compile('确认'))),1)

    def test_scaled_page_and_red_markers(self):
        original=cv2.imread('tests/images/daily_followup/echo_missing.png')
        with tempfile.TemporaryDirectory() as folder:
            for h in (720,900,1080,1440):
                with self.subTest(height=h):
                    path=Path(folder)/f'{h}.png'
                    cv2.imwrite(str(path),cv2.resize(original,(h*16//9,h)))
                    self.set_image(str(path))
                    self.assertEqual(claimable_tiers(self.task.frame),[20,40,60,80])
                    self.assertTrue(self.task._daily_page_ready(self.task.frame))


if __name__ == '__main__':
    unittest.main()
