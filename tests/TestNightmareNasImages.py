import unittest
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.DailyTask import DailyTask
from src.task.WeeklyBossTask import WeeklyBossTask
from src.task.NightmareNestTask import NightmareNestTask

FOLDER='tests/images/daily_nas_20261005/'

class TestNightmareNasImages(TaskTestCase):
    task_class=NightmareNestTask
    config=config

    def test_filter_overlay_blocks_all_entry_selection(self):
        self.set_image(FOLDER+'nightmare_filter_open.png')
        self.assertTrue(self.task._nightmare_filter_open(self.task.frame))
        with self.assertRaisesRegex(ValueError,'筛选'):
            self.task._nightmare_rows(self.task.frame)
