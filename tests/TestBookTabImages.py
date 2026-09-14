import unittest
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.BaseWWTask import BaseWWTask

class TestBookTabImages(TaskTestCase):
    task_class=BaseWWTask
    config=config
    def test_forgery_selected_other_tabs_unselected(self):
        for stamp in ('17_02_22','17_02_46','17_03_02','17_03_16'):
            self.set_image(f'tests/images/materials/{stamp}.png')
            frame=self.task.frame
            self.assertTrue(self.task._book_tab_ready('ningsu',frame),stamp)
            self.assertIsNone(self.task._unselected_book_tab('ningsu',frame))
            for name in ('moni','qiangdi','wuyin','zhange','canxiang'):
                self.assertIsNotNone(self.task._unselected_book_tab(name,frame),name)
                self.assertFalse(self.task._book_tab_ready(name,frame),name)
    def test_redacted_sidebar_cannot_prove_selection(self):
        self.set_image('tests/images/weekly_boss/list1.png')
        self.assertFalse(self.task._book_tab_ready('zhange',self.task.frame))
    def test_world_map_is_not_a_book(self):
        self.set_image('tests/images/big_map.png')
        self.assertIsNone(self.task._book_tab('ningsu',self.task.frame))

if __name__=='__main__':unittest.main()
