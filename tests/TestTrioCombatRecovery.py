import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from src.char.BaseChar import BaseChar, CharType, SwitchPriority
from src.char.TrialGenericChar import TrialGenericChar
from src.char.Qingxiao import Qingxiao
from src.char.Suisui import Suisui
from src.char.Iuno import Iuno
from src.char.Denia import Denia
from src.char.Mornye import Mornye
from src.char.CharFactory import get_char_by_pos
from src.Labels import Labels
from src.combat.roster_context import advance_roster_context, roster_context
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
    def load_unconfirmed_roster(self, task, slots=(1,)):
        task._in_combat = True
        task._refresh_battle_roster = Mock()
        for index in slots:
            unknown = BaseChar(task, index, char_name='unknown', confidence=0)
            unknown._identity_unconfirmed = True
            unknown._identity_evidence = (
                (Labels.char_suisui, (*roster_context(task), (720, 1280), index)), 1, 1, 0)
            unknown._identity_observation = ('unmatched', .7, .01, 0)
            task.chars[index] = unknown
        with patch('src.task.BaseCombatTask.get_char_by_pos', side_effect=lambda t,b,i,c,**kw: c), \
                patch('src.runtime.diagnostic_lifecycle.record_combat_anomaly'):
            self.assertTrue(task.load_chars(force_full_scan=True))

    def test_one_unconfirmed_slot_uses_generic_actions_without_blocking_known_chars(self):
        task = combat_task()
        main, _, sub = task.chars
        main.last_failed_rotation = 123
        main.last_res = 456
        task.in_team.return_value = (True, 1, 3)
        self.load_unconfirmed_roster(task)
        generic = task.chars[1]
        self.assertIsInstance(generic, TrialGenericChar)
        self.assertEqual((generic.char_name, generic.confidence), ('unknown', 0))
        self.assertTrue(generic._identity_unconfirmed)
        self.assertEqual(generic._identity_observation, ('unmatched', .7, .01, 0))
        self.assertEqual(generic._identity_evidence,
                         ((Labels.char_suisui, (*roster_context(task), (720, 1280), 1)), 1, 1, 0))
        self.assertIs(task.chars[0], main)
        self.assertIs(task.chars[2], sub)
        self.assertEqual((main.last_failed_rotation, main.last_res), (123, 456))
        self.assertTrue(task._in_combat)
        for name in ('wait_intro', 'click_echo', 'click_liberation', 'click_resonance',
                     'continues_normal_attack', 'heavy_attack', 'switch_next_char'):
            setattr(generic, name, Mock())
        generic.is_forte_full = Mock(return_value=False)
        with patch('src.task.BaseCombatTask.get_char_by_pos', return_value=generic) as identify:
            generic.perform()
        identify.assert_called_once()
        self.assertEqual(identify.call_args.args[2], 1)
        generic.click_echo.assert_called_once()
        generic.click_liberation.assert_called_once()
        generic.click_resonance.assert_called_once_with(time_out=1.5)
        generic.continues_normal_attack.assert_called_once_with(1.5)
        generic.switch_next_char.assert_called_once()
        self.assertIs(task.chars[0], main)
        self.assertIs(task.chars[2], sub)

    def test_all_unconfirmed_slots_can_load_generic_roster(self):
        task = combat_task()
        self.load_unconfirmed_roster(task, (0, 1, 2))
        self.assertTrue(all(isinstance(char, TrialGenericChar) for char in task.chars))
        self.assertTrue(all(char._identity_unconfirmed for char in task.chars))
        self.assertEqual([char.index for char in task.chars], [0, 1, 2])
        self.assertTrue(task._in_combat)

    def test_unconfirmed_specialist_is_replaced_without_calling_its_helpers(self):
        task = combat_task()
        task.in_team.return_value = (True, 1, 3)
        old = task.chars[1]
        old._identity_unconfirmed = True
        old.perform_forte3_rotation = Mock(side_effect=AssertionError('stale Suisui rotation'))
        old.try_e = Mock(side_effect=AssertionError('stale Suisui skill helper'))
        self.load_unconfirmed_roster(task, slots=())
        generic = task.chars[1]
        self.assertIsNot(generic, old)
        self.assertIsInstance(generic, TrialGenericChar)
        self.assertEqual((generic.char_name, generic.confidence), ('unknown', 0))
        self.assertTrue(generic._identity_unconfirmed)
        for name in ('wait_intro', 'click_echo', 'click_liberation', 'click_resonance',
                     'continues_normal_attack', 'switch_next_char'):
            setattr(generic, name, Mock())
        generic.is_forte_full = Mock(return_value=False)
        with patch('src.task.BaseCombatTask.get_char_by_pos', return_value=generic):
            generic.perform()
        generic.click_resonance.assert_called_once_with(time_out=1.5)
        generic.continues_normal_attack.assert_called_once_with(1.5)
        old.perform_forte3_rotation.assert_not_called()
        old.try_e.assert_not_called()

    def test_unconfirmed_slot_recovers_after_three_frames_without_resetting_rotation(self):
        task = combat_task()
        task.in_team.return_value = (True, 1, 3)
        self.load_unconfirmed_roster(task)
        main, generic, sub = task.chars
        main.has_intro = True
        main.last_failed_rotation = 123
        generic.has_intro = True
        generic.has_sub_dps_intro = True
        generic.last_switch_time = 101
        generic.last_switch_in_time = 102
        generic.last_res = 103
        generic.last_echo = 104
        generic.last_liberation = 105
        state = task._rotation_state
        state.rows[1].update(turns=4, switches=2, field_seconds=3)
        state.action(generic, 'echo_send_attempt')
        task.find_best_match_in_box = Mock(side_effect=lambda box, names, **kw:
            SimpleNamespace(name=Labels.char_suisui, confidence=.846)
            if Labels.char_suisui in names else SimpleNamespace(confidence=.71))
        for token in (1, 2):
            task.executor._last_frame_time = token
            self.assertTrue(task.prepare_character_rotation(generic))
        task.executor._last_frame_time = 3
        generic.do_perform = Mock()
        generic.perform()
        generic.do_perform.assert_not_called()
        recovered = task.chars[1]
        self.assertIsInstance(recovered, Suisui)
        self.assertFalse(recovered._identity_unconfirmed)
        self.assertEqual(recovered.char_name, Labels.char_suisui)
        self.assertTrue(recovered.has_intro)
        self.assertTrue(recovered.has_sub_dps_intro)
        self.assertEqual((recovered.last_switch_time, recovered.last_switch_in_time,
                          recovered.last_res, recovered.last_echo, recovered.last_liberation),
                         (101, 102, 103, 104, 105))
        self.assertIs(task.chars[0], main)
        self.assertIs(task.chars[2], sub)
        self.assertTrue(main.has_intro)
        self.assertEqual(main.last_failed_rotation, 123)
        self.assertIs(task._rotation_state, state)
        row = state.rows[1]
        self.assertEqual((row['script'], row['identity'], row['confidence'], row['role']),
                         (recovered.name, str(Labels.char_suisui), .846, str(recovered.char_type)))
        self.assertEqual((row['turns'], row['switches'], row['field_seconds']), (6, 2, 3))
        self.assertEqual(dict(row['actions']), {'echo_send_attempt': 1})
        self.assertTrue(task.prepare_character_rotation(recovered))

    def test_dead_unconfirmed_slot_is_not_reidentified_or_selected(self):
        task = combat_task()
        self.load_unconfirmed_roster(task)
        main, generic, sub = task.chars
        generic._switch_unrevivable = True
        with patch('src.task.BaseCombatTask.get_char_by_pos') as identify:
            self.assertTrue(task.prepare_character_rotation(main))
        identify.assert_not_called()
        self.assertIs(task._choose_switch_target(main, False), sub)

    def test_confirmation_hud_loss_prevents_generic_actions(self):
        task = combat_task()
        task._in_combat = True
        unknown = BaseChar(task, 1, char_name='unknown', confidence=0)
        unknown._identity_unconfirmed = True
        task.chars[1] = unknown
        task.in_team.side_effect = [(True, 1, 3), (False, -1, 0)]
        with patch('src.task.BaseCombatTask.get_char_by_pos', side_effect=lambda t,b,i,c,**kw: c):
            self.assertFalse(task.load_chars(force_full_scan=True))
        self.assertFalse(task._in_combat)
        self.assertFalse(any(isinstance(char, TrialGenericChar) for char in task.chars))
        task.in_team.side_effect = None
        task.in_team.return_value = (False, -1, 0)
        task._rotation_roster_recheck = True
        unknown.do_perform = Mock()
        with self.assertRaises(CombatStateUnknown):
            unknown.perform()
        unknown.do_perform.assert_not_called()

    def test_generic_fallback_survives_screenshot_save_failure(self):
        task = combat_task()
        task.screenshot.side_effect = OSError('disk full')
        self.load_unconfirmed_roster(task)
        self.assertIsInstance(task.chars[1], TrialGenericChar)
        self.assertTrue(task._in_combat)
        task.screenshot.assert_called()

    def test_context_change_discards_old_generic_identity_evidence(self):
        for change in ('window', 'account'):
            with self.subTest(change=change):
                task = combat_task()
                self.load_unconfirmed_roster(task)
                generic = task.chars[1]
                old_evidence = (('candidate', roster_context(task)), 1, 2, 0)
                generic._identity_evidence = old_evidence
                if change == 'window':
                    task.executor.device_manager.hwnd_window.hwnd = 456
                else:
                    advance_roster_context(task, 'new-account')
                def recognize(owner, box, index, cached, **kwargs):
                    fresh = cached or BaseChar(owner, index, char_name='unknown', confidence=0)
                    fresh._identity_unconfirmed = True
                    return fresh
                with patch('src.task.BaseCombatTask.get_char_by_pos', side_effect=recognize) as identify, \
                        patch('src.runtime.diagnostic_lifecycle.record_combat_anomaly'):
                    self.assertTrue(task.load_chars(force_full_scan=True))
                self.assertTrue(all(call.args[3] is None for call in identify.call_args_list[:3]))
                self.assertIsNot(task.chars[1], generic)
                self.assertIsNone(task.chars[1].__dict__.get('_identity_evidence'))

    def test_confirmed_battle_rechecks_status_without_identity_scan_or_state_reset(self):
        task = combat_task()
        task._battle_roster_confirmed = True
        task._refresh_battle_roster = Mock()
        old = tuple(task.chars)
        old[1].has_intro = True
        with patch('src.task.BaseCombatTask.get_char_by_pos') as identify:
            self.assertTrue(task.load_chars(force_full_scan=True))
            task._rotation_roster_recheck = True
            self.assertTrue(task.prepare_character_rotation(old[0]))
        identify.assert_not_called()
        self.assertEqual(tuple(task.chars), old)
        self.assertTrue(old[1].has_intro)
        self.assertEqual(task._refresh_battle_roster.call_count, 2)

    def test_explicit_end_invalidates_identity_but_recovery_reset_preserves_it(self):
        from src.combat.CombatCheck import CombatCheck
        task = combat_task()
        task._battle_roster_confirmed = True
        task.do_reset_to_false = Mock()
        task.reset_to_false('temporary HUD loss')
        self.assertTrue(task._battle_roster_confirmed)
        task.reset_to_false(CombatCheck.EXPLICIT_END_REASON)
        self.assertFalse(task._battle_roster_confirmed)
        with patch('src.task.BaseCombatTask.get_char_by_pos', side_effect=lambda t,b,i,c,**kw: c) as identify:
            task.load_chars(force_full_scan=True)
        self.assertEqual(identify.call_count, 3)
        self.assertTrue(all(c.kwargs['force_full_scan'] for c in identify.call_args_list))

    def test_dead_slots_keep_numbers_and_do_not_block_remaining_characters(self):
        task = combat_task()
        task._battle_roster_confirmed = True
        task._refresh_battle_roster = Mock()
        main, healer, sub = task.chars
        healer._switch_unrevivable = True
        self.assertIs(task._choose_switch_target(main, False), sub)
        self.assertEqual(sub.index, 2)
        sub._switch_unrevivable = True
        self.assertIs(task._choose_switch_target(main, False), main)
        task.switch_healer_enabled = Mock(return_value=True)
        main.switch_other_char = Mock()
        task.switch_healer()
        main.switch_other_char.assert_not_called()

    def test_context_change_discards_confirmed_battle_identity(self):
        task = combat_task()
        task._battle_roster_confirmed = True
        task.executor.device_manager.hwnd_window.hwnd = 456
        with patch('src.task.BaseCombatTask.get_char_by_pos', side_effect=lambda t,b,i,c,**kw: BaseChar(t,i)) as identify:
            task.load_chars()
        self.assertEqual(identify.call_count, 3)
        self.assertTrue(all(call.args[3] is None for call in identify.call_args_list))
        self.assertFalse(task._battle_roster_confirmed)

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
        task.load_chars.assert_called_once_with(reset_state=False, force_full_scan=False)
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
