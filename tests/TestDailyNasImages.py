import unittest
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.DailyTask import DailyTask
from src.task.WeeklyBossTask import WeeklyBossTask
from src.task.NightmareNestTask import NightmareNestTask

FOLDER='tests/images/daily_nas_20261005/'

class TestDailyNasImages(TaskTestCase):
    task_class=DailyTask
    config=config

    def test_high_scores_in_production_reader(self):
        for score in (240,300):
            self.set_image(FOLDER+f'activity_{score}.png')
            self.assertEqual(score,self.task.get_total_daily_points(attempts=1))

    def test_resource_bar_zero_reserve_is_valid(self):
        self.set_image(FOLDER+'resource_234.png')
        self.assertEqual((234,0,234),self.task.get_stamina())
