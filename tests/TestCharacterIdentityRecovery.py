import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from src.char import CharFactory as factory
from src.char.BaseChar import BaseChar
from src.char.Hiyuki import Hiyuki
from src.char.TrialGenericChar import TrialGenericChar
from src.task.BaseCombatTask import BaseCombatTask


class TestCharacterIdentityRecovery(unittest.TestCase):
    def setUp(self):
        self.old = Hiyuki(None, 0, char_name=factory.Labels.char_hiyuki, confidence=.940819)
        self.task = Mock()
        self.task.find_one.return_value = None
        self.task.require_game_frame.return_value = np.zeros((720, 1280, 3), np.uint8)
        self.task.hwnd = SimpleNamespace(hwnd=123)
        self.task._verified_profile_id = 'A1'
        self.task.has_challenge_success.return_value = False
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

    def test_weak_old_portrait_does_not_hide_strong_new_identity(self):
        self.task.find_one.return_value = self.runner
        self.loader.side_effect = lambda cls: Hiyuki if cls is Hiyuki else Mock(return_value=self.new)
        self.assertIs(self.sample(), self.old)
        self.assertIs(self.sample(), self.old)
        self.assertIs(self.sample(), self.new)

    def prepare_load(self):
        self.old.index = 0
        self.old.reset_state = Mock()
        self.loader.side_effect = lambda cls: cls
        self.task.chars = [self.old]
        self.task._char_identity = BaseCombatTask._char_identity
        self.task.in_team.return_value = (True, 0, 1)
        self.task._app = None
        self.task._char_context = None
        self.task.executor.next_frame.side_effect = self.advance_frame

    def advance_frame(self, **kwargs):
        self.task.executor._last_frame_time += 1
        return self.task.require_game_frame.return_value

    def test_load_confirms_real_change_before_exposing_combat_roster(self):
        self.prepare_load()
        self.assertTrue(BaseCombatTask.load_chars(self.task))
        self.assertEqual(self.task.chars[0].char_name, factory.Labels.char_rover)
        self.assertIsNot(self.task.chars[0], self.old)
        self.assertEqual(self.task.executor.next_frame.call_count, 2)
        self.old.reset_state.assert_not_called()
        self.task.click.assert_not_called()
        self.task.send_key.assert_not_called()

    def test_load_stale_captures_use_unknown_generic_with_evidence(self):
        self.prepare_load()
        self.task.executor.next_frame.side_effect = None
        self.assertTrue(BaseCombatTask.load_chars(self.task))
        generic = self.task.chars[0]
        self.assertIsInstance(generic, TrialGenericChar)
        self.assertEqual((generic.char_name, generic.confidence), ('unknown', 0))
        self.assertTrue(generic._identity_unconfirmed)
        self.task.report_rotation_anomaly.assert_called_once_with('unconfirmed_identity', generic)
        self.old.reset_state.assert_not_called()
        self.task.click.assert_not_called()
        self.task.send_key.assert_not_called()

    def test_daily_entries_confirm_roster_before_entering_combat(self):
        from types import MethodType
        from src.task.DailyTask import DailyTask
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask
        for task_class in (DailyTask, MultiAccountDailyTask):
            with self.subTest(entry=task_class.__name__):
                self.prepare_load()
                self.task.in_liberation = False
                self.task._in_combat = False
                self.task.has_target.return_value = True
                self.task.load_chars = MethodType(task_class.load_chars, self.task)
                self.assertTrue(task_class.do_check_in_combat(self.task, target=False))
                self.assertEqual(self.task.chars[0].char_name, factory.Labels.char_rover)
                self.assertTrue(self.task._in_combat)

    def test_unchanged_team_needs_no_additional_capture(self):
        self.prepare_load()
        self.task.find_one.return_value = SimpleNamespace(confidence=.95)
        self.assertTrue(BaseCombatTask.load_chars(self.task))
        self.assertIs(self.task.chars[0], self.old)
        self.task.executor.next_frame.assert_not_called()
        self.task.find_best_match_in_box.assert_not_called()

    def test_account_change_discards_previous_account_identity(self):
        self.prepare_load()
        self.task._char_context = (123, 'previous-account')
        self.assertTrue(BaseCombatTask.load_chars(self.task))
        self.assertEqual(self.task.chars[0].char_name, factory.Labels.char_rover)
        self.task.find_one.assert_not_called()
        self.task.executor.next_frame.assert_not_called()

    def test_weak_or_ambiguous_replacements_cannot_enter_combat_as_old_char(self):
        self.prepare_load()
        self.candidate.confidence = .83
        self.assertTrue(BaseCombatTask.load_chars(self.task))
        generic = self.task.chars[0]
        self.assertIsInstance(generic, TrialGenericChar)
        self.assertEqual(generic.char_name, 'unknown')
        self.assertTrue(generic._identity_unconfirmed)
        self.task.report_rotation_anomaly.assert_called_once_with('unconfirmed_identity', generic)
        self.assertIn('0.83', self.task.log_warning.call_args.args[0])
        self.old.reset_state.assert_not_called()

    def test_missing_hud_during_confirmation_does_not_load_old_team(self):
        self.prepare_load()
        self.task.in_team.side_effect = [(True, 0, 1)] + [(False, -1, 1)] * 5
        self.assertFalse(BaseCombatTask.load_chars(self.task))
        self.task.screenshot.assert_not_called()
        self.old.reset_state.assert_not_called()
        self.task.send_key.assert_not_called()

    def test_verified_success_after_liberation_hands_off_without_recovery(self):
        char = BaseChar.__new__(BaseChar)
        char.task = self.task
        self.task.has_challenge_success.return_value = True
        self.task.EXPLICIT_END_REASON = 'explicit_end_condition'
        self.task.raise_not_in_combat.side_effect = RuntimeError('expected end')
        with self.assertRaisesRegex(RuntimeError, 'expected end'):
            char.recheck_liberation_timeout()
        self.task.raise_not_in_combat.assert_called_once_with('挑战成功，交接结果页', expected=True)
        self.task.reset_to_false.assert_called_once_with(reason='explicit_end_condition')
        self.task.has_target.assert_not_called()

    def test_youhu_unknown_page_never_sends_selection_key(self):
        from src.char.Youhu import Youhu
        char = Youhu(self.task, 0)
        self.task.ocr.return_value = []
        with patch.object(BaseChar, 'recheck_liberation_timeout') as recheck:
            char.recheck_liberation_timeout()
        self.task.send_key.assert_not_called()
        recheck.assert_called_once()

    def test_youhu_selection_failure_propagates_without_more_input(self):
        from src.char.Youhu import Youhu
        char = Youhu(self.task, 0)
        self.task.ocr.return_value = [SimpleNamespace(name=k) for k in 'WASD']
        self.task.wait_until.side_effect = RuntimeError('selection did not return')
        with self.assertRaisesRegex(RuntimeError, 'selection did not return'):
            char.recheck_liberation_timeout()
        self.task.send_key.assert_called_once_with('w', after_sleep=.1)

    def test_user_stop_during_confirmation_propagates(self):
        from ok import TaskDisabledException
        self.prepare_load()
        self.task.executor.next_frame.side_effect = TaskDisabledException('stop')
        with self.assertRaises(TaskDisabledException):
            BaseCombatTask.load_chars(self.task)
        self.task.screenshot.assert_not_called()
        self.old.reset_state.assert_not_called()

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
