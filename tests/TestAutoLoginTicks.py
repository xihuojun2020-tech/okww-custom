import unittest
from types import MethodType
from unittest.mock import Mock
from src.task.AutoLoginTask import AutoLoginTask
from tests import TestNavigationAdapter as nav_tests
from tests.TestWaitLogin import FakeLoginTask

class LoginHarness(AutoLoginTask):
    @property
    def logged_in(self):return getattr(self,'_test_logged_in',False)
    @logged_in.setter
    def logged_in(self,value):self._test_logged_in=value

class TestAutoLoginTicks(unittest.TestCase):
    def task(self):
        harness=nav_tests.TestNavigationAdapter();self.addCleanup(harness.doCleanups)
        base=harness.task();task=LoginHarness.__new__(LoginHarness);task.__dict__.update(base.__dict__)
        self.clock=harness.clock;task.executor.current_task=task;task.executor.debug=False
        self.button=harness.button;self.button.name='登录'
        task.in_team_and_world=Mock(return_value=False)
        task.find_monthly_card=Mock(return_value=None);task.find_one=Mock(return_value=None)
        task.box_of_screen=Mock(return_value=object())
        task.find_boxes=MethodType(FakeLoginTask.find_boxes,task)
        task.ocr=Mock(side_effect=lambda **kw:[self.button])
        task._click_login_box=Mock(return_value=True)
        task.sleep=Mock(side_effect=AssertionError('login tick must not sleep'))
        task.log_debug=Mock()
        return task
    def tick(self,task):
        task.executor._last_frame_time+=1
        result=task.run();self.clock[0]+=1
        return result
    def test_login_autologin_grace_is_nonblocking(self):
        task=self.task()
        for _ in range(4):self.assertFalse(self.tick(task))
        task._click_login_box.assert_not_called()
        self.assertTrue(self.tick(task))
        task._click_login_box.assert_called_once_with(self.button,after_sleep=0)
        task.sleep.assert_not_called()
    def test_transient_login_then_world_never_clicks(self):
        task=self.task()
        self.tick(task);self.tick(task)
        task.in_team_and_world.return_value=True
        self.tick(task)
        self.assertTrue(task.logged_in);task._click_login_box.assert_not_called()
    def test_connect_and_login_are_distinct_observed_steps(self):
        task=self.task();self.button.name='点击连接'
        for _ in range(3):self.tick(task)
        self.assertEqual(task._click_login_box.call_count,1)
        self.button.name='登录';self.tick(task)
        self.assertEqual(task._click_login_box.call_count,1)
        for _ in range(5):self.tick(task)
        self.assertEqual(task._click_login_box.call_count,2)
    def test_no_buttons_consume_budget_without_input(self):
        from src.task.ui_transition import TransitionTimeout
        task=self.task();self.tick(task);task.ocr.return_value=[];task.ocr.side_effect=None
        self.clock[0]=19
        with self.assertRaises(TransitionTimeout):self.tick(task)
        task._click_login_box.assert_not_called()
    def test_restart_cooldown_never_blocks_or_clicks(self):
        task=self.task();task._login_restart_wait_until=60
        for _ in range(4):self.assertFalse(self.tick(task))
        task.ocr.assert_not_called();task.sleep.assert_not_called()

if __name__=='__main__':unittest.main()
