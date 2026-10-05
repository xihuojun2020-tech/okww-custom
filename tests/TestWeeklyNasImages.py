import unittest
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.DailyTask import DailyTask
from src.task.WeeklyBossTask import WeeklyBossTask
from src.task.NightmareNestTask import NightmareNestTask

FOLDER='tests/images/daily_nas_20261005/'

class TestWeeklyNasImages(TaskTestCase):
    task_class=WeeklyBossTask
    config=config

    def test_fraction_recovery_keeps_dialog_cost(self):
        self.set_image(FOLDER+'weekly_claim_171.png')
        dialog=self.task._claim_confirmation()
        self.assertIsNotNone(dialog)
        self.assertEqual((60,171),dialog[:2])
