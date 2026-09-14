import unittest
from unittest.mock import Mock,patch,PropertyMock
from tests import TestNavigationAdapter as nav_tests
from src.task.BaseWWTask import BaseWWTask
from src.task.ui_transition import TransitionTimeout

class TestBookTabTransitions(unittest.TestCase):
    def task(self,height=1080):
        harness=nav_tests.TestNavigationAdapter();self.addCleanup(harness.doCleanups)
        task=harness.task(height);self.button=harness.button
        task._book_tab=Mock(return_value=self.button)
        task._book_tab_highlight=lambda frame,button:task.click_relative.call_count>=2
        task.ocr=Mock(return_value=[])
        return task
    def test_lost_first_click_retries_latest_tab_at_both_resolutions(self):
        for height in (1080,1440):
            task=self.task(height)
            task._book_tab_ready=lambda name,frame:task.click_relative.call_count>=2
            with patch.object(BaseWWTask,'game_lang',new_callable=PropertyMock,return_value='zh_CN'):
                task.open_boss_book('ningsu')
            self.assertEqual(task.click_relative.call_count,2)
            self.assertEqual(task.click_relative.call_args.args,(.7,.9))
            self.doCleanups()
    def test_selected_tab_with_unreadable_list_is_not_clicked_again(self):
        task=self.task();task._book_tab_highlight=lambda *args:True
        task._book_tab_ready=lambda *args:False
        with patch.object(BaseWWTask,'game_lang',new_callable=PropertyMock,return_value='zh_CN'):
            with self.assertRaises(TransitionTimeout):task.open_boss_book('ningsu')
        task.click_relative.assert_not_called()
    def test_already_selected_list_requires_no_input(self):
        task=self.task();task._book_tab_highlight=lambda *args:True
        task._book_tab_ready=lambda *args:True
        with patch.object(BaseWWTask,'game_lang',new_callable=PropertyMock,return_value='zh_CN'):
            task.open_boss_book('ningsu')
        task.click_relative.assert_not_called()

if __name__=='__main__':unittest.main()
