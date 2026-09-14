import unittest
from unittest.mock import Mock
import numpy as np
from ok import TaskDisabledException
from src.task.AutoAbyssTask import AutoAbyssTask, CharacterScanRecord, character_card_slots

class TestAbyssCancelRetry(unittest.TestCase):
    def task(self, states, waits):
        task=AutoAbyssTask.__new__(AutoAbyssTask)
        record=CharacterScanRecord('a','清宵',1,90,.9,1,0,slot=character_card_slots()[0])
        task.next_frame=Mock()
        task.require_game_frame=Mock(return_value=np.zeros((720,1280,3),np.uint8))
        task._relocate_record=Mock(return_value=record)
        task._selection_marker_present=Mock(side_effect=states)
        task._wait_selection_marker=Mock(side_effect=waits)
        task.log_info=Mock();task._log_card_action=Mock();task.click_relative=Mock();task.screenshot=Mock()
        return task,record

    def test_missed_first_click_retries(self):
        task,record=self.task([True,True],[False,True])
        task._cancel_character_selection(record)
        self.assertEqual(task.click_relative.call_count,2)
        self.assertEqual(task.next_frame.call_count,2)

    def test_delayed_success_is_not_toggled_back(self):
        task,record=self.task([True,False],[False])
        task._cancel_character_selection(record)
        self.assertEqual(task.click_relative.call_count,1)

    def test_already_clear_never_clicks(self):
        task,record=self.task([False],[])
        task._cancel_character_selection(record)
        task.click_relative.assert_not_called()

    def test_unknown_after_missed_click_stops(self):
        task,record=self.task([True,None],[False])
        with self.assertRaisesRegex(RuntimeError,'不明确'):task._cancel_character_selection(record)
        self.assertEqual(task.click_relative.call_count,1)

    def test_missing_identity_never_clicks(self):
        task,record=self.task([],[])
        task._relocate_record.return_value=None
        with self.assertRaisesRegex(RuntimeError,'身份'):task._cancel_character_selection(record)
        task.click_relative.assert_not_called()

    def test_three_click_limit(self):
        task,record=self.task([True]*4,[False]*3)
        with self.assertRaisesRegex(RuntimeError,'清宵.*3次'):task._cancel_character_selection(record)
        self.assertEqual(task.click_relative.call_count,3)

    def test_last_click_delayed_success(self):
        task,record=self.task([True,True,True,False],[False]*3)
        task._cancel_character_selection(record)
        self.assertEqual(task.click_relative.call_count,3)

    def test_stop_between_attempts(self):
        task,record=self.task([True],[False])
        task.next_frame.side_effect=[None,TaskDisabledException()]
        with self.assertRaises(TaskDisabledException):task._cancel_character_selection(record)
        self.assertEqual(task.click_relative.call_count,1)
