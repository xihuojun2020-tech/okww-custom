import unittest
from unittest.mock import Mock,patch
from tests import TestNavigationAdapter as nav_tests
from src.task.trigger_navigation import advance
from src.task.ui_transition import TransitionContextChanged,TransitionTimeout

class TestTriggerNavigation(unittest.TestCase):
    def task(self):
        harness=nav_tests.TestNavigationAdapter();self.addCleanup(harness.doCleanups)
        task=harness.task();self.clock=harness.clock;self.button=harness.button
        task.sleep=Mock(side_effect=AssertionError('background must not sleep'))
        return task
    def tick(self,task,source=True,target=False,identity='destination'):
        task._executor._last_frame_time+=1
        result=advance(task,'travel',lambda f:self.button if source else None,lambda f:target,identity=identity)
        self.clock[0]+=.5
        return result
    def test_three_ticks_then_one_input_no_wait(self):
        task=self.task()
        self.assertFalse(self.tick(task));self.assertFalse(self.tick(task));self.assertTrue(self.tick(task))
        task.click_relative.assert_called_once();task.sleep.assert_not_called()
        self.assertTrue(self.tick(task,False,True));task.click_relative.assert_called_once()
    def test_destination_identity_changes_stop(self):
        task=self.task();self.tick(task)
        with self.assertRaises(TransitionContextChanged):self.tick(task,identity='other')
        task.click_relative.assert_not_called()
    def test_other_owner_cancels_old_pending_step(self):
        task=self.task();self.tick(task)
        task.executor._navigation_epoch=1;task.executor._navigation_owner=object()
        with self.assertRaises(TransitionContextChanged):self.tick(task)
        self.assertFalse(self.tick(task));task.click_relative.assert_not_called()
    def test_own_success_does_not_cancel_verification(self):
        task=self.task()
        for _ in range(3):self.tick(task)
        task.executor._navigation_epoch=1;task.executor._navigation_owner=task
        self.assertTrue(self.tick(task,False,True))
    def test_window_change_cancels_pending(self):
        task=self.task();self.tick(task);task.hwnd.hwnd=2
        with self.assertRaises(TransitionContextChanged):self.tick(task)
        task.click_relative.assert_not_called()
    def test_timeout_does_not_restart_budget_next_tick(self):
        task=self.task();self.tick(task);self.clock[0]=19
        with self.assertRaises(TransitionTimeout):self.tick(task)
        self.assertFalse(self.tick(task));task.click_relative.assert_not_called()
    def test_loading_does_not_reread_destination_or_click(self):
        task=self.task()
        for _ in range(3):self.tick(task)
        identity=Mock(side_effect=AssertionError('no title during loading'))
        self.assertFalse(self.tick(task,False,False,identity))
        self.assertTrue(self.tick(task,False,True,identity));task.click_relative.assert_called_once()
    def test_failed_diagnostics_do_not_replay_input(self):
        task=self.task()
        with patch('src.task.trigger_navigation.publish',side_effect=OSError('disk')):
            for _ in range(3):self.tick(task)
            self.tick(task,False,True)
        task.click_relative.assert_called_once()

if __name__=='__main__':unittest.main()
