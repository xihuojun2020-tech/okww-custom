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

    def test_a3_suiboshi_ocr_variant_selects_first_row(self):
        from src.task.NightmareNestTask import FARM_NIGHTMARE_SETTLEMENTS
        self.set_image('tests/images/daily_nas_20261008/nightmare_suiboshi.png')
        self.task.config[FARM_NIGHTMARE_SETTLEMENTS] = ['穗波市梦魇聚落']
        self.task._reset_progress_tracking()
        target = self.task._find_nightmare_nest()
        self.assertEqual('穗波市梦魇聚落', target.display_name)
        self.assertEqual((0, 36), (target.current, target.total))
        self.assertEqual('直接挑战', target.box.name)
        self.assertLess(target.box.y, self.task.height_of_screen(.4))
