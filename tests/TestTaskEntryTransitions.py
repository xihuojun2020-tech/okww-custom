import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from tests import TestNavigationAdapter as nav_tests
from src.task.EventTask import EventTask
from src.task.AutoAbyssTask import AutoAbyssTask, TOWER_NAMES
from src.task.ui_transition import TransitionTimeout

class TestTaskEntryTransitions(unittest.TestCase):
    def task(self):
        harness=nav_tests.TestNavigationAdapter();self.addCleanup(harness.doCleanups)
        task=harness.task();self.button=harness.button;self.button.name='确认'
        task.ocr=Mock(return_value=[self.button])
        return task
    def test_event_next_wave_recovers_first_click_loss(self):
        task=self.task()
        task._detect_page=lambda:'confirm_next' if task.click_relative.call_count<2 else 'arena'
        EventTask._handle_confirm_next_wave(task)
        self.assertEqual(task.click_relative.call_count,2)
    def test_event_unknown_never_confirms(self):
        task=self.task();task._detect_page=lambda:'unknown'
        with self.assertRaises(TransitionTimeout):EventTask._handle_confirm_next_wave(task)
        task.click_relative.assert_not_called()
    def test_shop_cannot_return_before_confirmed_exit(self):
        task=self.task();task.send_key=Mock()
        task._detect_page=lambda:'shop' if task.send_key.call_count<2 else 'confirm_next'
        EventTask._leave_shop(task)
        self.assertEqual(task.send_key.call_count,2)
    def test_abyss_same_card_entry_retries_then_stops_at_overview(self):
        task=self.task()
        title=SimpleNamespace(name='深境区',x=700,y=250,width=100,height=30)
        button=SimpleNamespace(name='前往',x=1000,y=250,width=80,height=30,center=lambda:(1040,265))
        def ocr(*args,**kwargs):
            if task.click_relative.call_count>=2:
                return [SimpleNamespace(name=name) for name in TOWER_NAMES]
            return [button] if kwargs.get('match') else [title]
        task.ocr=ocr
        AutoAbyssTask._open_adversity_tower(task)
        self.assertEqual(task.click_relative.call_count,2)

if __name__=='__main__':unittest.main()
