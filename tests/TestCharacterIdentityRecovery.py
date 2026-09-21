import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from src.char import CharFactory as factory
from src.char.BaseChar import BaseChar
from src.char.Hiyuki import Hiyuki


class TestCharacterIdentityRecovery(unittest.TestCase):
    def setUp(self):
        self.old = Hiyuki.__new__(Hiyuki)
        self.old.char_name = factory.Labels.char_hiyuki
        self.old.confidence = .940819
        self.task = Mock()
        self.task.find_one.return_value = None
        self.task.require_game_frame.return_value = np.zeros((720, 1280, 3), np.uint8)
        self.task.hwnd = SimpleNamespace(hwnd=123)
        self.task._verified_profile_id = 'A1'
        self.task.executor._last_frame_time = 1
        self.candidate = SimpleNamespace(name=factory.Labels.char_rover, confidence=.96)
        self.runner = SimpleNamespace(name=factory.Labels.char_hiyuki, confidence=.7)
        self.task.find_best_match_in_box.side_effect = lambda box, names, **kw: (
            self.candidate if factory.Labels.char_rover in names else self.runner)
        self.new = Mock()
        self.loader = patch.object(factory, 'load_custom_char_class', return_value=Mock(return_value=self.new)).start()
        self.addCleanup(patch.stopall)

    def sample(self):
        result = factory.get_char_by_pos(self.task, object(), 0, self.old)
        self.task.executor._last_frame_time += 1
        return result

    def test_reported_wrong_scores_never_replace_confirmed_hiyuki(self):
        for score in (.839298, .814672, .800596):
            self.candidate.confidence = score
            for _ in range(5):
                self.assertIs(self.sample(), self.old)
        self.loader.assert_not_called()

    def test_real_change_requires_three_distinct_captures(self):
        self.assertIs(self.sample(), self.old)
        self.assertIs(self.sample(), self.old)
        self.assertIs(self.sample(), self.new)

    def test_repeated_capture_does_not_confirm_change(self):
        for _ in range(5):
            self.assertIs(factory.get_char_by_pos(self.task, object(), 0, self.old), self.old)

    def test_close_runner_up_prevents_change(self):
        self.runner.confidence = .91
        for _ in range(5):
            self.assertIs(self.sample(), self.old)

    def test_missing_match_resets_consecutive_evidence(self):
        self.sample()
        self.sample()
        candidate = self.candidate
        self.candidate = None
        self.assertIs(self.sample(), self.old)
        self.candidate = candidate
        self.assertIs(self.sample(), self.old)
        self.assertIs(self.sample(), self.old)
        self.assertIs(self.sample(), self.new)

    def test_account_context_change_restarts_verification(self):
        self.sample()
        self.sample()
        self.task._verified_profile_id = 'A3'
        self.assertIs(self.sample(), self.old)
        self.assertIs(self.sample(), self.old)
        self.assertIs(self.sample(), self.new)

    def test_first_recognition_is_not_delayed(self):
        self.assertIs(factory.get_char_by_pos(self.task, object(), 0, None), self.new)

    def test_long_observation_gap_restarts_confirmation(self):
        with patch.object(factory.time, 'monotonic', side_effect=[0, .2, 5, 5.2, 5.4]):
            self.assertIs(self.sample(), self.old)
            self.assertIs(self.sample(), self.old)
            self.assertIs(self.sample(), self.old)
            self.assertIs(self.sample(), self.old)
            self.assertIs(self.sample(), self.new)

    def test_liberation_loop_exits_after_recheck_instead_of_waiting_forever(self):
        char = BaseChar.__new__(BaseChar)
        char.task = self.task
        char.logger = Mock()
        char.recheck_liberation_timeout = Mock()
        char.add_freeze_duration = Mock()
        char.record_liberation_use = Mock()
        self.task.in_liberation = True
        self.task.use_liberation = True
        self.task.in_team.return_value = (False, -1, 1)
        with patch('src.char.BaseChar.time.time', side_effect=[0, 0, 8, 8]):
            self.assertTrue(char.click_liberation())
        char.recheck_liberation_timeout.assert_called_once()
        self.assertFalse(self.task.in_liberation)

    def test_liberation_timeout_recovers_only_with_player_and_enemy(self):
        char = BaseChar.__new__(BaseChar)
        char.task = self.task
        self.task.in_team.return_value = (False, -1, 1)
        self.task.find_one.return_value = object()  # Player health remains visible.
        self.task.has_target.return_value = False
        self.task.check_health_bar.return_value = True
        char.recheck_liberation_timeout()
        self.assertFalse(self.task.in_liberation)
        self.assertEqual(self.task.next_frame.call_count, 2)
        self.task.raise_not_in_combat.assert_not_called()

    def test_unknown_frame_does_not_resume_combat(self):
        char = BaseChar.__new__(BaseChar)
        char.task = self.task
        self.task.in_team.return_value = (False, -1, 1)
        self.task.find_one.return_value = None
        self.task.has_target.return_value = True
        self.task.raise_not_in_combat.side_effect = RuntimeError('unknown HUD')
        with self.assertRaisesRegex(RuntimeError, 'unknown HUD'):
            char.recheck_liberation_timeout()
        self.assertFalse(self.task.in_liberation)
        self.task.log_warning.assert_not_called()

    def test_enemy_disappearing_on_second_frame_does_not_resume(self):
        char = BaseChar.__new__(BaseChar)
        char.task = self.task
        self.task.in_team.return_value = (True, 0, 1)
        self.task.has_target.side_effect = [True, False]
        self.task.check_health_bar.return_value = False
        self.task.raise_not_in_combat.side_effect = RuntimeError('unknown HUD')
        with self.assertRaises(RuntimeError):
            char.recheck_liberation_timeout()
        self.task.log_warning.assert_not_called()


if __name__ == '__main__':
    unittest.main()
