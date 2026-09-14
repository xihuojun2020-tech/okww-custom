"""Exercise the production adapter with synthetic captures and input loss."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
import numpy as np
from ok import TaskDisabledException
from src.task.BaseWWTask import BaseWWTask
from src.task.ui_transition import TransitionContextChanged, TransitionTimeout


class TestNavigationAdapter(unittest.TestCase):
    def task(self, height=1080):
        task = BaseWWTask.__new__(BaseWWTask)
        width = height*16//9
        task._executor = SimpleNamespace(check_enabled=Mock(), current_task=task,
            device_manager=SimpleNamespace(hwnd_window=SimpleNamespace(hwnd=1, exists=True)),
            method=SimpleNamespace(width=width, height=height), _last_frame_time=0)
        task._verified_profile_id = 'synthetic'
        task._guard_account_input = Mock()
        task.info_set = Mock(); task.log_info = Mock(); task.log_warning = Mock()
        task.screenshot = Mock(); task.click_relative = Mock()
        task.require_game_frame = Mock(return_value=np.zeros((height,width,3),np.uint8))
        def fresh(): task._executor._last_frame_time += 1
        task.next_frame = Mock(side_effect=fresh)
        self.clock = [0.]
        task.sleep = lambda dt: self.clock.__setitem__(0,self.clock[0]+dt)
        self.patch = patch('src.task.BaseWWTask.time.monotonic', side_effect=lambda:self.clock[0])
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.button = SimpleNamespace(center=lambda:(.7*width,.9*height))
        return task

    def test_both_resolutions_use_normalized_fresh_coordinates(self):
        for height in (1080,1440):
            with self.subTest(height=height):
                task = self.task(height)
                task.navigate_ui('test', lambda f:self.button if task.click_relative.call_count < 2 else None,
                                 lambda f:task.click_relative.call_count >= 2)
                self.assertEqual(task.click_relative.call_count,2)
                self.assertEqual(task.click_relative.call_args.args,(.7,.9))
                self.assertIsNone(task.executor._ui_transition_deadline)
                self.patch.stop()

    def test_ambiguous_source_and_target_never_click(self):
        task=self.task()
        with self.assertRaises(TransitionTimeout):
            task.navigate_ui('ambiguous',lambda f:self.button,lambda f:True,timeout=1)
        task.click_relative.assert_not_called()

    def test_account_window_or_task_change_stops(self):
        for field in ('account','window','task'):
            with self.subTest(field=field):
                task=self.task()
                def target(frame):
                    if field == 'account':task._verified_profile_id='other'
                    elif field == 'window':task.hwnd.hwnd=2
                    else:task.executor.current_task=object()
                    return False
                with self.assertRaises(TransitionContextChanged):
                    task.navigate_ui('context',lambda f:self.button,target)
                task.click_relative.assert_not_called()
                self.patch.stop()

    def test_resize_between_observation_and_input_stops(self):
        task=self.task()
        task.executor.method.width=2560
        with self.assertRaises(TransitionContextChanged):
            task.navigate_ui('resize',lambda f:self.button,lambda f:False)
        task.click_relative.assert_not_called()

    def test_stop_from_screenshot_prevents_input(self):
        task=self.task()
        task.screenshot.side_effect=TaskDisabledException('stop')
        with self.assertRaises(TaskDisabledException):
            task.navigate_ui('cancel',lambda f:self.button,lambda f:False,screenshots=True)
        task.click_relative.assert_not_called()

    def test_diagnostics_failure_does_not_replay_input(self):
        task=self.task();task.info_set.side_effect=OSError('ui unavailable')
        task.navigate_ui('disk',lambda f:self.button if not task.click_relative.called else None,
                         lambda f:task.click_relative.called)
        task.click_relative.assert_called_once()

    def test_source_identity_changes_reject_new_target(self):
        task=self.task()
        with self.assertRaises(TransitionContextChanged):
            task.navigate_ui('identity',lambda f:self.button,lambda f:False,
                             identity=lambda f: 'first' if self.clock[0] == 0 else 'second')
        task.click_relative.assert_not_called()

    def test_book_lost_first_input_uses_icon_only_in_world(self):
        task=self.task();task.ensure_main=Mock();task.key_config={}
        task.send_key=Mock();task.send_key_down=Mock();task.send_key_up=Mock()
        task.in_team_and_world=lambda **kw:not task.click_relative.called
        task.find_one=lambda *a,**kw:self.button if task.click_relative.called else None
        task.wait_book=Mock(return_value=self.button);task.click_box=Mock()
        task.openF2Book()
        task.send_key.assert_called_once_with('f2')
        task.click_relative.assert_called_once_with(.77,.05)
        task.send_key_up.assert_called_once_with('alt')
        task.click_box.assert_called_once()

    def test_book_icon_failure_releases_alt_and_does_not_retry(self):
        task=self.task();task.ensure_main=Mock();task.key_config={}
        task.send_key=Mock();task.send_key_down=Mock();task.send_key_up=Mock()
        task.in_team_and_world=lambda **kw:True;task.find_one=lambda *a,**kw:None
        task.click_relative.side_effect=OSError('uncertain input')
        with self.assertRaises(OSError):task.openF2Book()
        task.click_relative.assert_called_once();task.send_key_up.assert_called_once_with('alt')

    def test_daily_record_without_progress_never_reports_success(self):
        from src.task.DailyTask import DailyTask
        task=self.task(); task.openF2Book=Mock()
        task.ocr=Mock(return_value=[]); task.find_one=Mock(return_value=self.button)
        task.click=Mock()
        with self.assertRaises(TransitionTimeout):
            DailyTask._open_record_page(task, '任务页')
        self.assertEqual(task.click.call_count, 3)

    def test_daily_record_waits_for_content_and_does_not_reclick(self):
        from src.task.DailyTask import DailyTask
        task=self.task(); task.openF2Book=Mock(); task.click=Mock()
        task.ocr=lambda *a,**kw: [SimpleNamespace(name='100/180')] if task.click.called else []
        task.find_one=Mock(return_value=self.button)
        self.assertTrue(DailyTask._open_record_page(task, '任务页'))
        task.click.assert_called_once_with(.17,.12)


if __name__=='__main__':unittest.main()
