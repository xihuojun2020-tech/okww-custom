import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from src.char.BaseChar import BaseChar, CharType, SwitchPriority
from src.char.Qingxiao import Qingxiao
from src.char.Suisui import Suisui
from src.char.Iuno import Iuno
from src.char.Denia import Denia
from src.char.Mornye import Mornye
from src.char.CharFactory import get_char_by_pos
from src.Labels import Labels
from src.combat.roster_context import roster_context
from src.combat.rotation_state import RotationState
from src.task.BaseCombatTask import BaseCombatTask, CombatStateUnknown
from src.task.DailyTask import DailyTask


def combat_task(executor=None):
    task = BaseCombatTask.__new__(BaseCombatTask)
    task._executor = executor or SimpleNamespace(
        device_manager=SimpleNamespace(hwnd_window=SimpleNamespace(hwnd=123)),
        _last_frame_time=1, next_frame=Mock(), debug=False)
    task._app = None
    task.char_config = {}
    for name in ('log_info', 'log_warning', 'log_debug', 'screenshot', 'info_set', 'load_hotkey'):
        setattr(task, name, Mock())
    task.require_game_frame = Mock(return_value=np.zeros((720, 1280, 3), np.uint8))
    task.get_box_by_name = Mock()
    task.in_team = Mock(return_value=(True, 0, 3))
    task.chars = [Qingxiao(task, 0, char_name=Labels.char_qingxiao, char_type=CharType.MAIN_DPS),
                  Suisui(task, 1, char_name=Labels.char_suisui, char_type=CharType.HEALER),
                  Iuno(task, 2, char_name=Labels.char_iuno, char_type=CharType.SUB_DPS)]
    task.chars[0].is_current_char = True
    task._char_context = roster_context(task)
    task._rotation_state = RotationState(task.chars)
    return task


class TestTrioCombatRecovery(unittest.TestCase):
    def test_all_reused_children_discard_previous_account_on_bind(self):
        first = combat_task()
        daily = DailyTask.__new__(DailyTask)
        daily._executor = first.executor
        daily.config = None
        daily.load_daily_profiles = lambda: {n: {'profile_id': n} for n in ('B7', 'B8', 'B10')}
        children = [first, combat_task(first.executor), combat_task(first.executor)]
        from src.task.NightmareNestTask import NightmareNestTask
        from src.task.TacetTask import TacetTask
        from src.task.ForgeryTask import ForgeryTask
        for child, cls in zip(children, (NightmareNestTask, TacetTask, ForgeryTask)):
            child.__class__ = cls
        for account in ('B7', 'B8', 'B10', 'B10'):
            before = roster_context(first)
            daily.bind_verified_profile(account)
            self.assertNotEqual(before, roster_context(first))
            for child in children:
                old = child.chars[0]
                def recognize(owner, box, index, cached, **kwargs):
                    self.assertIsNone(cached)
                    cls, label, role = [(Qingxiao, Labels.char_qingxiao, CharType.MAIN_DPS),
                                        (Denia, Labels.char_denia, CharType.SUB_DPS),
                                        (Mornye, Labels.char_moning, CharType.HEALER)][index]
                    return cls(owner, index, char_name=label, char_type=role)
                with patch('src.task.BaseCombatTask.get_char_by_pos', side_effect=recognize):
                    self.assertFalse(child.prepare_character_rotation(old))
                self.assertIsInstance(child.chars[1], Denia)
                self.assertIsInstance(child.chars[2], Mornye)

    def test_window_change_rechecks_before_character_actions(self):
        task = combat_task()
        char = task.chars[0]
        task.executor.device_manager.hwnd_window.hwnd = 456
        task.load_chars = Mock(return_value=False)
        char.do_perform = Mock()
        with self.assertRaises(CombatStateUnknown):
            char.perform()
        char.do_perform.assert_not_called()

    def test_rejected_profile_binding_does_not_publish_account_context(self):
        from src.config_integrity import ConfigIntegrityBlocked
        child = combat_task()
        daily = DailyTask.__new__(DailyTask)
        daily._executor = child.executor
        daily.load_daily_profiles = lambda: {'B10': {'profile_id': 'B10'}}
        before = roster_context(child)
        with self.assertRaises(ConfigIntegrityBlocked):
            daily.bind_verified_profile('B10', expected_profile_id='B7')
        self.assertEqual(roster_context(child), before)

    def test_two_support_attempts_reach_main_even_when_suisui_is_must(self):
        task = combat_task()
        main, healer, sub = task.chars
        state = task._rotation_state
        state.begin(healer)
        state.finish_turn(healer)
        self.assertIs(task._choose_switch_target(healer, False), sub)
        state.switched(sub)
        state.begin(sub)
        state.finish_turn(sub)
        self.assertEqual(healer.get_switch_priority(sub, False), SwitchPriority.MUST)
        with patch('src.runtime.diagnostic_lifecycle.record_combat_anomaly'):
            self.assertIs(task._choose_switch_target(sub, False), main)
        self.assertFalse(main.has_intro)
        self.assertFalse(healer.has_buff())
        self.assertFalse(sub.has_buff())

    def test_background_multi_uses_upstream_priority_instead_of_local_budget(self):
        task = combat_task()
        main, healer, sub = task.chars
        task.use_original_multi_rotation = True
        task._rotation_state.support_attempts = {healer.index, sub.index}
        self.assertEqual(healer.get_switch_priority(sub, False), SwitchPriority.MUST)
        self.assertIs(task._choose_switch_target(sub, False), healer)

    def test_recovery_respects_no_priority_and_switch_cooldown(self):
        for blocked in ('priority', 'cooldown'):
            task = combat_task()
            main, healer, sub = task.chars
            task._rotation_state.support_attempts = {1, 2}
            if blocked == 'priority':
                main.get_switch_priority = Mock(return_value=SwitchPriority.NO)
            else:
                main.last_switch_time = 99.5
                task.time_elapsed_accounting_for_freeze = lambda start, *args, **kw: 100 - start
            self.assertIsNot(task._choose_switch_target(sub, False), main)

    def test_normal_preparation_and_intro_still_return_to_main(self):
        task = combat_task()
        main, healer, sub = task.chars
        task._rotation_state.support_attempts = {1, 2}
        healer.has_buff = sub.has_buff = Mock(return_value=True)
        self.assertIs(task._choose_switch_target(sub, True), main)
        task.screenshot.assert_not_called()

    def test_failed_switch_not_counted_as_successful_entry(self):
        task = combat_task()
        state = task._rotation_state
        with patch('src.combat.rotation_state.time.monotonic', return_value=100):
            state.begin(task.chars[1])
        with patch('src.combat.rotation_state.time.monotonic', return_value=126):
            state.finish_turn(task.chars[1])
            self.assertEqual(state.snapshot()['chars'][1]['field_seconds'], 26)
        self.assertEqual(sum(r['switches'] for r in state.snapshot()['chars']), 0)
        state.switched(task.chars[2])
        self.assertEqual(state.snapshot()['chars'][2]['switches'], 1)

    def test_anomaly_evidence_rate_limits_but_counts_every_event(self):
        task = combat_task()
        with patch('src.runtime.diagnostic_lifecycle.record_combat_anomaly') as record:
            for _ in range(3):
                task.report_rotation_anomaly('suisui_forte_timeout', task.chars[1], recheck=True)
        self.assertTrue(task._rotation_roster_recheck)
        task.screenshot.assert_called_once_with('combat_rotation_suisui_forte_timeout')
        record.assert_called_once()
        self.assertEqual(task._rotation_state.events['suisui_forte_timeout'], 3)

    def test_evidence_failure_does_not_fail_combat_but_user_stop_propagates(self):
        from ok import TaskDisabledException
        for error in (OSError('disk full'), TaskDisabledException('stop')):
            task = combat_task()
            task.screenshot.side_effect = error
            if isinstance(error, TaskDisabledException):
                with self.assertRaises(TaskDisabledException):
                    task.report_rotation_anomaly('fixture', task.chars[0])
            else:
                task.report_rotation_anomaly('fixture', task.chars[0])

    def test_three_instant_main_turns_are_detected(self):
        task = combat_task()
        state = task._rotation_state
        for expected in (False, False, True):
            state.begin(task.chars[0])
            self.assertEqual(state.finish_turn(task.chars[0]), expected)

    def test_fast_skill_send_is_not_an_empty_main_turn(self):
        task = combat_task()
        state = task._rotation_state
        for _ in range(4):
            state.begin(task.chars[0])
            state.action(task.chars[0], 'resonance_send_attempt')
            self.assertFalse(state.finish_turn(task.chars[0]))

    def test_full_roster_recheck_preserves_confirmed_character_rotation_state(self):
        task = combat_task()
        old = task.chars[1]
        old.last_failed_rotation = 100
        old._yield_after_recheck = True
        task.find_one = Mock()
        task.find_best_match_in_box = Mock(side_effect=lambda box, names, **kw:
            SimpleNamespace(name=Labels.char_suisui, confidence=.99) if Labels.char_suisui in names else None)
        self.assertIs(get_char_by_pos(task, object(), 1, old, force_full_scan=True), old)
        self.assertFalse(old._identity_unconfirmed)
        task.find_one.assert_not_called()
        self.assertEqual(old.last_failed_rotation, 100)
        self.assertTrue(old._yield_after_recheck)

    def test_recheck_rejects_weak_ambiguous_and_unknown_portraits(self):
        for score, runner in ((.79, None), (.96, SimpleNamespace(confidence=.92)), (None, None)):
            task = combat_task()
            candidate = SimpleNamespace(name=Labels.char_suisui, confidence=score) if score else None
            task.find_best_match_in_box = Mock(side_effect=lambda box, names, **kw:
                candidate if Labels.char_suisui in names else runner)
            for old in (None, task.chars[1]):
                char = get_char_by_pos(task, object(), 1, old, force_full_scan=True)
                self.assertTrue(char._identity_unconfirmed)

    def test_stable_low_score_needs_three_independent_frames(self):
        task = combat_task()
        task.find_best_match_in_box = Mock(side_effect=lambda box, names, **kw:
            SimpleNamespace(name=Labels.char_suisui, confidence=.846)
            if Labels.char_suisui in names else SimpleNamespace(confidence=.71))
        char = None
        for token in (1, 1, 2, 3):
            task.executor._last_frame_time = token
            char = get_char_by_pos(task, object(), 1, char, force_full_scan=True)
            self.assertEqual(char._identity_unconfirmed, token != 3)
        self.assertEqual(char.char_name, Labels.char_suisui)

    def test_ambiguous_low_score_never_accumulates_identity(self):
        task = combat_task()
        task.find_best_match_in_box = Mock(side_effect=lambda box, names, **kw:
            SimpleNamespace(name=Labels.char_suisui, confidence=.846)
            if Labels.char_suisui in names else SimpleNamespace(confidence=.80))
        char = None
        for token in range(1, 5):
            task.executor._last_frame_time = token
            char = get_char_by_pos(task, object(), 1, char, force_full_scan=True)
            self.assertTrue(char._identity_unconfirmed)

    def test_full_scan_replaces_stale_zhezhi_with_stable_danjin(self):
        task = combat_task()
        old = BaseChar(task, 2, char_name=Labels.char_zhezhi, confidence=.95)
        task.find_best_match_in_box = Mock(side_effect=lambda box, names, **kw:
            SimpleNamespace(name=Labels.char_danjin, confidence=.859)
            if Labels.char_danjin in names else SimpleNamespace(confidence=.70))
        char = old
        for token in (1, 1, 2, 3):
            task.executor._last_frame_time = token
            char = get_char_by_pos(task, object(), 2, char, force_full_scan=True)
            self.assertEqual(token != 3, char._identity_unconfirmed)
        self.assertEqual(Labels.char_danjin, char.char_name)
        self.assertIsNot(old, char)

    def test_timeout_rechecks_before_switch_and_does_not_repeat_full_wait(self):
        task = combat_task()
        char = task.chars[1]
        task.in_team.return_value = (True, 1, 3)
        char.is_current_char = True
        task.chars[0].is_current_char = False
        char.switch_next_char = Mock()
        char.forte3_available = char.forte2_available = Mock(return_value=False)
        char.try_e = Mock(return_value=False)
        char.click = char.cycle_sleep = Mock()
        char.time_elapsed_accounting_for_freeze = lambda start: 27
        with patch('src.runtime.diagnostic_lifecycle.record_combat_anomaly'):
            char.do_perform()
        char.switch_next_char.assert_not_called()
        self.assertTrue(task._rotation_roster_recheck)
        self.assertTrue(char.recent_rotation_failure())
        self.assertEqual(char.get_switch_priority(task.chars[2], False), SwitchPriority.NORMAL)
        task.load_chars = Mock(return_value=True)
        task.prepare_character_rotation(char)
        task.load_chars.assert_called_once_with(reset_state=False, force_full_scan=True)
        char.do_perform()
        char.switch_next_char.assert_called_once()

    def test_try_e_rotation_requests_only_one_switch(self):
        task = combat_task()
        char = task.chars[1]
        char.switch_next_char = Mock()
        char.forte3_available = char.forte2_available = Mock(return_value=False)
        char.try_e = Mock(return_value=True)
        char.time_elapsed_accounting_for_freeze = Mock(return_value=0)
        char.do_perform()
        char.switch_next_char.assert_called_once()

    def test_recent_failure_bounds_next_forte_wait_to_six_seconds(self):
        task = combat_task()
        char = task.chars[1]
        char.last_failed_rotation = 100
        char.time_elapsed_accounting_for_freeze = lambda start: 0 if start == 100 else 7
        char.forte3_available = char.forte2_available = Mock(return_value=False)
        char.click = Mock()
        with patch('src.runtime.diagnostic_lifecycle.record_combat_anomaly'):
            self.assertFalse(char.perform_forte3_rotation())
        char.click.assert_not_called()

    def test_skill_attempts_are_not_reported_as_skill_success(self):
        task = combat_task()
        char = task.chars[0]
        task.send_key = Mock()
        task.get_resonance_key = Mock(return_value='e')
        char.send_resonance_key()
        self.assertEqual(task._rotation_state.snapshot()['chars'][0]['actions'], {'resonance_send_attempt': 1})

    def test_rotation_warning_requests_existing_diagnostic_window(self):
        from src.runtime import diagnostic_lifecycle
        session = Mock()
        data = {'reason': 'suisui_forte_timeout', 'at_unix': 100}
        with patch.object(diagnostic_lifecycle, '_session', session):
            diagnostic_lifecycle.record_combat_anomaly(data)
        session.record_event.assert_called_once_with('combat_rotation_anomaly', data)
        session.record_error.assert_called_once_with(data)


if __name__ == '__main__':
    unittest.main()
