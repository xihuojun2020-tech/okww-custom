import unittest
from unittest.mock import Mock
from tests import TestNavigationAdapter as nav_tests
from src.task.SkipDialogTask import AutoDialogTask
from src.task.FastTravelTask import FastTravelTask

class TestBackgroundNavigationTasks(unittest.TestCase):
    def task(self,kind):
        harness=nav_tests.TestNavigationAdapter();self.addCleanup(harness.doCleanups)
        base=harness.task();task=kind.__new__(kind);task.__dict__.update(base.__dict__)
        task.executor.current_task=task;self.clock=harness.clock;self.button=harness.button
        task.sleep=Mock(side_effect=AssertionError('no waits'))
        task.in_team_and_world=Mock(return_value=False);task.click_box=Mock()
        task.find_one=Mock(return_value=None)
        return task
    def tick(self,task):
        task.executor._last_frame_time+=1
        value=task.run();self.clock[0]+=.5
        return value
    def test_skip_then_confirmation_are_separate_ticks(self):
        task=self.task(AutoDialogTask)
        task.find_skip=Mock(side_effect=lambda:self.button if task.click_box.call_count==0 else None)
        task._skip_confirmation=Mock(side_effect=lambda:self.button if task.click_box.call_count==1 else None)
        for _ in range(3):self.tick(task)
        self.assertEqual(task.click_box.call_count,1)
        self.tick(task)
        self.assertEqual(task.click_box.call_count,1)
        for _ in range(3):self.tick(task)
        self.assertEqual(task.click_box.call_count,2)
        task.in_team_and_world.return_value=True;self.tick(task)
        self.assertIsNone(task._ui_tick_navigation);task.sleep.assert_not_called()
    def test_unrelated_confirm_does_not_become_skip_confirmation(self):
        task=self.task(AutoDialogTask)
        task.find_one.side_effect=lambda name,**kw:self.button if name=='skip_dialog_check' else None
        self.assertIsNone(task._skip_confirmation())
        task.click_box.assert_not_called()
    def test_fast_travel_ignores_remove_marker(self):
        task=self.task(FastTravelTask);task.match=['快速旅行']
        task.find_one=Mock(return_value=self.button);task.ocr=Mock(return_value=[self.button])
        for _ in range(4):self.tick(task)
        task.click_relative.assert_not_called()
    def test_fast_travel_requires_destination_identity_and_one_input(self):
        task=self.task(FastTravelTask);task.match=['快速旅行'];self.button.name='传送目标'
        task.find_one=lambda name,**kw:self.button if name=='gray_teleport' and not task.click_relative.called else None
        task.ocr=Mock(return_value=[self.button])
        for _ in range(3):self.tick(task)
        task.click_relative.assert_called_once()
        task.in_team_and_world.return_value=True;self.tick(task)
        task.click_relative.assert_called_once();task.sleep.assert_not_called()

    def test_fast_travel_confirmation_waits_for_next_tick(self):
        task=self.task(FastTravelTask);task.match=['快速旅行'];self.button.name='传送目标'
        task.find_one=lambda name,**kw:self.button if name=='gray_teleport' and not task.click_relative.called else None
        task.ocr=Mock(return_value=[self.button])
        task._travel_confirmation=lambda frame:self.button if task.click_relative.call_count==1 else None
        for _ in range(3):self.tick(task)
        self.assertEqual(task.click_relative.call_count,1)
        self.tick(task)
        self.assertEqual(task.click_relative.call_count,1)
        for _ in range(3):self.tick(task)
        self.assertEqual(task.click_relative.call_count,2)
        task.in_team_and_world.return_value=True;self.tick(task)
        self.assertFalse(task._travel_requested)
        task.sleep.assert_not_called()

    def test_skip_source_lingers_without_replaying(self):
        task=self.task(AutoDialogTask)
        task.find_skip=Mock(return_value=self.button)
        for _ in range(20):self.tick(task)
        task.click_box.assert_called_once()


if __name__=='__main__':unittest.main()
