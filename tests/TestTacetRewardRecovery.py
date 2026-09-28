import unittest
from unittest.mock import Mock

from src.task.BaseWWTask import BaseWWTask


def reward_task():
    task = Mock()
    task.width = 1920
    task.height = 1080
    task.find_treasure_icon.return_value = None
    task.walk_until_f.return_value = True
    task.require_game_frame.return_value = None
    return task


class TestTacetRewardRecovery(unittest.TestCase):
    def test_nearby_claim_does_not_move_or_nudge(self):
        task = reward_task()
        task.find_f_with_claim_text.return_value = True
        self.assertTrue(BaseWWTask.walk_to_treasure(task))
        task.do_walk_to_box.assert_not_called()
        task.send_key.assert_not_called()
        self.assertEqual(task.send_key_up.call_count, 4)

    def test_stalled_marker_repositions_and_then_claims(self):
        task = reward_task()
        marker = Mock()
        marker.center.return_value = (960, 860)
        task.find_treasure_icon.return_value = marker
        task.find_f_with_claim_text.side_effect = lambda: task.send_key.call_count > 0
        self.assertTrue(BaseWWTask.walk_to_treasure(task))
        self.assertEqual(task.do_walk_to_box.call_count, 3)
        task.send_key.assert_called_once_with('s', down_time=.25)

    def test_missing_reward_is_bounded_and_releases_inputs(self):
        task = reward_task()
        task.find_f_with_claim_text.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'claim interaction unconfirmed'):
            BaseWWTask.walk_to_treasure(task)
        self.assertEqual(task.send_key.call_count, 6)
        self.assertEqual(task.send_key_up.call_count, 4)
        task.screenshot.assert_called_once()

    def test_movement_exception_releases_inputs(self):
        task = reward_task()
        task.find_f_with_claim_text.return_value = False
        marker = Mock()
        marker.center.return_value = (800, 850)
        task.find_treasure_icon.return_value = marker
        task.do_walk_to_box.side_effect = ValueError('movement failed')
        with self.assertRaisesRegex(ValueError, 'movement failed'):
            BaseWWTask.walk_to_treasure(task)
        self.assertEqual(task.send_key_up.call_count, 4)
        task.mouse_up.assert_called_with(key='right')
