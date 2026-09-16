import unittest
from types import SimpleNamespace, MethodType
from unittest.mock import Mock, patch
import numpy as np
from ok import TaskDisabledException
from src.task.DailyTask import DailyTask, DailyActivityIncomplete
from src.task.BaseCombatTask import BaseCombatTask, CharRevivedInPlace, CharRevivedException, CharDeadException
from src.task.DomainTask import DomainTask
from src.runtime.game_runtime_errors import FrameUnavailable, GameProcessLost
from src.config_integrity import ConfigIntegrityBlocked, ConfigWriteBlocked


class TestDailyRegressionFlow(unittest.TestCase):
    def objective_task(self, stuck=False, points_known=True):
        task = Mock(spec=DailyTask)
        state = {'pending': [20, 60, 20, 20], 'points': 0, 'chests': []}
        task.require_game_frame.return_value = np.zeros((90, 160, 3), np.uint8)
        task._daily_page_ready.return_value = True
        task._daily_objective_claim_buttons.side_effect = lambda: [
            SimpleNamespace(y=200+i*100, name='领取') for i in range(len(state['pending']))]
        task.get_total_daily_points.side_effect = lambda **kw: state['points'] if points_known else None
        def click(*a, **kw):
            if not stuck:
                state['points'] += state['pending'].pop(0)
                state['chests'] = [20, 40, 60, 80, 100]
        task.click.side_effect = click
        task._claim_daily_objectives = MethodType(DailyTask._claim_daily_objectives, task)
        task.click_relative.side_effect = lambda *a, **kw: state['chests'].pop(0)
        return task, state

    def test_real_claim_flow_claims_objectives_before_chests_and_is_idempotent(self):
        task, state = self.objective_task()
        with patch('src.task.daily_observation.claimable_tiers', side_effect=lambda _:list(state['chests'])):
            DailyTask.claim_daily(task)
            DailyTask.claim_daily(task)
        self.assertEqual(state['points'], 120)
        self.assertEqual(task.click.call_count, 4)
        self.assertEqual(task.click_relative.call_count, 5)
        self.assertEqual(state['chests'], [])

    def test_no_response_is_bounded_and_does_not_claim_success(self):
        task, _ = self.objective_task(stuck=True)
        with self.assertRaises(DailyActivityIncomplete):
            task._claim_daily_objectives()
        self.assertEqual(task.click.call_count, 2)

    def test_unknown_points_can_claim_but_must_observe_button_progress(self):
        task, state = self.objective_task(points_known=False)
        task._claim_daily_objectives()
        self.assertEqual(state['pending'], [])
        task, _ = self.objective_task(stuck=True, points_known=False)
        with self.assertRaises(DailyActivityIncomplete):
            task._claim_daily_objectives()

    def test_objective_claim_filter_excludes_go_and_already_claimed(self):
        task = Mock(spec=DailyTask)
        task._daily_page_ready.return_value = True
        task.ocr.return_value = [SimpleNamespace(name=name, y=i) for i,name in enumerate(
            ['前往', '已领取', 'Claimed', '领取', 'Claim', '領取'])]
        self.assertEqual([b.name for b in DailyTask._daily_objective_claim_buttons(task)],
                         ['领取', 'Claim', '領取'])

    def test_open_daily_claims_before_policy_authorization(self):
        from src.task.daily_reserve_policy import DailyReservePolicy
        task, state = self.objective_task()
        policy = DailyReservePolicy('synthetic', remaining=180)
        task.executor = SimpleNamespace(_daily_reserve_policy=policy)
        task._verified_profile_id = 'synthetic'
        task._daily_objective.return_value = (0, 180)
        self.assertEqual(DailyTask.open_daily(task), (0, True))
        self.assertTrue(policy.full_seen)
        self.assertEqual(policy.allowance(0, 180), 0)
        self.assertEqual(state['points'], 120)

    def test_claim_modal_restored_before_next_action(self):
        task = Mock(spec=DailyTask)
        task._daily_page_ready.return_value = False
        task.ocr.return_value = [SimpleNamespace(name='获得奖励')]
        DailyTask._restore_daily_claim_page(task)
        task.click_relative.assert_called_once_with(.50, .78, after_sleep=.5)
        task._open_daily_page.assert_called_once()

    def test_local_revive_success_does_not_call_exit_recovery(self):
        task = Mock(spec=BaseCombatTask)
        task._local_revive_active = True
        task._local_revive_count = 0
        task.reset_to_false.return_value = False
        task._try_revive_in_place.return_value = True
        with self.assertRaises(CharRevivedInPlace):
            BaseCombatTask.raise_not_in_combat(task, 'revive dialog')
        task.revive_action.assert_not_called()
        self.assertEqual(task._local_revive_count, 1)
        self.assertFalse(issubclass(CharRevivedInPlace, CharDeadException))

    def test_failed_or_exhausted_local_revive_preserves_legacy_recovery(self):
        for count in (0, 3):
            task = Mock(spec=BaseCombatTask)
            task._local_revive_active = True
            task._local_revive_count = count
            task.reset_to_false.return_value = False
            task._try_revive_in_place.return_value = False
            task.revive_action.return_value = True
            with self.assertRaises(CharRevivedException):
                BaseCombatTask.raise_not_in_combat(task, 'cannot revive')
            task.revive_action.assert_called_once()
            if count == 3:
                task._try_revive_in_place.assert_not_called()

    def test_confirm_requires_dialog_gone_and_team_returned(self):
        for success in (True, False):
            task = Mock(spec=BaseCombatTask)
            button = object()
            task._local_revive_button.side_effect = lambda: None if success and task.click.called else button
            task.find_one.side_effect = lambda *a,**kw: None if success else button
            task.in_team.return_value = (True, 0, 3)
            task.wait_until.side_effect = lambda predicate,**kw: predicate()
            self.assertEqual(BaseCombatTask._try_revive_in_place(task), success)
            self.assertEqual(task.click.call_count, 1 if success else 2)
            task.send_key.assert_not_called()

    def test_local_revive_continues_production_domain_combat_without_reentry(self):
        task = Mock(spec=DomainTask)
        task.info = {}
        task.chars = []
        task.switch_healer_enabled.return_value = False
        task.in_combat.side_effect = [True, True, False]
        task.get_current_char.return_value.perform.side_effect = [CharRevivedInPlace(), None]
        task.load_chars.return_value = True
        task.combat_once = MethodType(BaseCombatTask.combat_once, task)
        task.executor = SimpleNamespace(check_enabled=Mock(), next_frame=Mock())
        task._domain_reward_state.return_value = 'claim'
        self.assertEqual(DomainTask._finish_domain_combat(task), 'claim')
        self.assertEqual(task.get_current_char.return_value.perform.call_count, 2)
        task.make_sure_in_world.assert_not_called()
        task.revive_action.assert_not_called()
        task.use_stamina.assert_not_called()
        self.assertEqual(task.info['Combat Count'], 1)

    def test_control_exceptions_are_not_swallowed_in_recovery(self):
        for cls in (TaskDisabledException, FrameUnavailable, GameProcessLost,
                    ConfigIntegrityBlocked, ConfigWriteBlocked):
            with self.subTest(error=cls.__name__):
                task = Mock(spec=BaseCombatTask)
                task.close_revive_popup.side_effect = cls('stop')
                with self.assertRaises(cls):
                    BaseCombatTask.revive_action(task)
                task.revive_at_tower_and_heal.assert_not_called()

    def test_no_local_dialog_never_clicks(self):
        task = Mock(spec=BaseCombatTask)
        task._local_revive_button.return_value = None
        self.assertFalse(BaseCombatTask._try_revive_in_place(task))
        task.click.assert_not_called()

    def test_stop_during_confirm_propagates_without_more_clicks(self):
        task = Mock(spec=BaseCombatTask)
        task.click.side_effect = TaskDisabledException('stop')
        with self.assertRaises(TaskDisabledException):
            BaseCombatTask._try_revive_in_place(task)
        self.assertEqual(task.click.call_count, 1)
        task.revive_action.assert_not_called()

    def test_repeated_in_place_recovery_cannot_loop_forever(self):
        from src.task.BaseCombatTask import CombatStateUnknown
        task = Mock(spec=BaseCombatTask)
        task.info = {}
        task.chars = []
        task.switch_healer_enabled.return_value = False
        task.in_combat.return_value = True
        task.load_chars.return_value = True
        task.get_current_char.return_value.perform.side_effect = CharRevivedInPlace()
        with self.assertRaises(CombatStateUnknown):
            BaseCombatTask.combat_once(task)
        self.assertEqual(task.get_current_char.return_value.perform.call_count, 4)

    def test_digit_range_and_unknown(self):
        for value in (0, 20, 90, 100, 110, 180, 181, -1, 'unknown'):
            task = Mock(spec=DailyTask)
            task.ocr.return_value = [SimpleNamespace(name=str(value))]
            with patch('src.evidence.service.evidence_frame', return_value=None), \
                    patch('src.evidence.service.record_task_evidence'):
                self.assertEqual(DailyTask.get_total_daily_points(task, attempts=1),
                                 value if isinstance(value,int) and 0 <= value <= 180 else None)


if __name__ == '__main__':
    unittest.main()
