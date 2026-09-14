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

    def test_cultivation_tab_requires_selected_highlight(self):
        self.set_image('tests/images/materials/13_33_40.png')
        self.assertTrue(self.task._book_tab_ready('target',self.task.frame))
        self.set_image('tests/images/materials/17_02_22.png')
        self.assertFalse(self.task._book_tab_ready('target',self.task.frame))
    def test_actual_inventory_headers(self):
        from src.task.MaterialPlannerTask import MaterialPlannerTask
        for stamp,expected in (('17_29_37','武器'),('17_29_48','资源'),('17_30_02','资源'),('17_02_22',None)):
            self.set_image(f'tests/images/materials/{stamp}.png')
            self.assertEqual(MaterialPlannerTask._inventory_page(self.task,self.task.frame),expected)


if __name__=='__main__':unittest.main()
