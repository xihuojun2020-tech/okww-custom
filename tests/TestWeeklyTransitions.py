import unittest
from unittest.mock import Mock, patch
from src.task.WeeklyBossTask import WeeklyBossTask
from src.task.weekly_boss import WEEKLY_BOSSES
from src.task.ui_transition import TransitionTimeout
from tests import TestNavigationAdapter as navigation_tests

class TestWeeklyTransitions(unittest.TestCase):
    def task(self):
        harness=navigation_tests.TestNavigationAdapter()
        self.addCleanup(harness.doCleanups)
        task=harness.task()
        self.button=harness.button
        task._entry_boss=WEEKLY_BOSSES[0]
        for name in ('TITLE','SINGLE','START'):
            setattr(task,name,getattr(WeeklyBossTask,name))
        task._text=Mock(return_value=task._entry_boss.name)
        task.click=lambda button:task.click_relative(.7,.9)
        return task

    def test_single_then_start_once_after_first_input_loss(self):
        task=self.task()
        task._button=lambda region,text,frame: self.button if (
            region==task.SINGLE and task.click_relative.call_count<2 or
            region==task.START and task.click_relative.call_count==2) else None
        task.in_team_and_world=lambda **kw:task.click_relative.call_count>=3
        WeeklyBossTask._enter_challenge(task)
        self.assertEqual(task.click_relative.call_count,3)

    def test_wrong_boss_stops_before_single(self):
        task=self.task();task._text.return_value=WEEKLY_BOSSES[1].name
        task._button=lambda region,text,frame:self.button if region==task.SINGLE else None
        with self.assertRaisesRegex(RuntimeError,'目标变化'):
            WeeklyBossTask._enter_challenge(task)
        task.click_relative.assert_not_called()

    def test_settlement_loading_does_not_repeat_retry(self):
        task=self.task()
        task._settlement=lambda:(self.button,self.button) if not task.click_relative.called else None
        task.in_team_and_world=lambda **kw:False
        with self.assertRaises(TransitionTimeout):WeeklyBossTask._leave_settlement(task,True)
        task.click_relative.assert_called_once()

    def test_settlement_lost_click_recovers_then_stops(self):
        task=self.task()
        task._settlement=lambda:(self.button,self.button) if task.click_relative.call_count<2 else None
        task.in_team_and_world=lambda **kw:task.click_relative.call_count>=2
        WeeklyBossTask._leave_settlement(task,False)
        self.assertEqual(task.click_relative.call_count,2)

    def test_target_detail_retry_does_not_click_different_boss(self):
        task=self.task();task.LIST=WeeklyBossTask.LIST
        task._text=lambda *args:task._entry_boss.name
        task._button=lambda *args:self.button if task.click_relative.call_count>=2 else None
        task._ocr=Mock(return_value=[])
        with patch(
                'src.task.WeeklyBossTask.match_target_button',return_value=self.button):
            WeeklyBossTask._open_weekly_target(task,task._entry_boss)
        self.assertEqual(task.click_relative.call_count,2)

    def test_wrong_detail_blocks_without_reopening_list(self):
        task=self.task();task.LIST=WeeklyBossTask.LIST
        task._text=Mock(return_value=WEEKLY_BOSSES[1].name)
        task._button=Mock(return_value=self.button)
        with self.assertRaisesRegex(RuntimeError,'不一致'):
            WeeklyBossTask._open_weekly_target(task,task._entry_boss)
        task.click_relative.assert_not_called()

    def test_story_warning_is_confirmed_once_then_original_boss_verified(self):
        task=self.task();task.LIST=WeeklyBossTask.LIST
        def text(region,frame):
            if region==(.25,.43,.75,.53):
                return '提前到达目标位置可能影响剧情体验，是否确认前往？' if task.click_relative.call_count==1 else ''
            return task._entry_boss.name
        task._text=text
        task._button=lambda region,*args:self.button if (
            region==(.55,.59,.76,.67) and task.click_relative.call_count==1 or
            region==task.SINGLE and task.click_relative.call_count>=2) else None
        task._ocr=Mock(return_value=[])
        with patch('src.task.WeeklyBossTask.match_target_button',return_value=self.button):
            WeeklyBossTask._open_weekly_target(task,task._entry_boss)
        self.assertEqual(task.click_relative.call_count,2)


if __name__=='__main__':unittest.main()
