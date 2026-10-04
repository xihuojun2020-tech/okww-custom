import copy
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch, PropertyMock

from ok import TaskDisabledException
from src.config_integrity import ConfigIntegrityService
from src.task.BaseWWTask import BaseWWTask
from src.task.BaseCombatTask import CombatStateUnknown
from src.task.FarmEchoTask import FarmEchoTask, FarmCycleResult
from src.task.WorldBossMaterialTask import WorldBossMaterialTask, MaterialRunResult
from src.task.DailyTask import DailyTask
from src.task.MaterialPlannerTask import MaterialPlannerTask, MATERIAL_PLANNER
from src.task.TacetTask import TacetTask
from src.task.ForgeryTask import ForgeryTask
from src.task.SimulationTask import SimulationTask
from src.task.world_boss_materials import TARGETS_BY_ID, material_target_button, matches_health_title, matches_health_title_boxes, matches_target
from src.task.world_boss_material_plan import MATERIAL_TARGETS
from src.task.world_boss_material_progress import WorldBossMaterialProgress

A, B, C = 'world_crownless', 'world_tempest', 'world_thundering'


def plan(limits=(2, 1, 0)):
    return {MATERIAL_TARGETS: [{'boss': b, 'limit': n} for b, n in zip((A, B, C), limits)]}


def box(name, x=400, y=280, width=100):
    return SimpleNamespace(name=name, x=x, y=y, width=width, height=20)


class TestWorldBossMaterialTask(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = ConfigIntegrityService(self.temp.name)
        self.progress = WorldBossMaterialProgress(self.service, 'account-a')
        self.tasks = plan()
        executor = patch.object(WorldBossMaterialTask, 'executor', new_callable=PropertyMock,
                                return_value=SimpleNamespace(_daily_reserve_policy=None))
        executor.start()
        self.addCleanup(executor.stop)

    def runner(self):
        task = object.__new__(WorldBossMaterialTask)
        task.config = {'Teleport to Boss': 'No', 'Boss': 'Other', 'Use Liberation': False}
        task.use_liberation = False
        task.info = {}
        task.scene = Mock()
        task._in_realm = False
        for name in ('_stage', 'next_frame', 'manage_boss_parameters', 'teleport_to_configured_boss_and_prepare',
                     '_release_combat_inputs', '_release_movement', 'send_key', 'back', 'click_box',
                     'screenshot', 'ensure_main', 'log_warning'):
            setattr(task, name, Mock())
        task.farm_cycle = Mock(return_value=FarmCycleResult(True, False, False))
        def cycle(**kwargs):
            task._material_name_verified = True
            task.out_of_combat_reason = task.TARGET_GONE_END_REASON
            return FarmCycleResult(True, False, False)
        task.farm_cycle.side_effect = cycle
        task._resources_for_claim = Mock(return_value=True)
        task._material_combat_finished = Mock(return_value=True)
        task.has_target = task.check_health_bar = Mock(return_value=False)
        task.in_team_and_world = Mock(return_value=True)
        task.pickup_dropped_echo = Mock(return_value=False)
        def wait(probe, **kwargs):
            for _ in range(6):
                result = probe()
                if result:
                    return result
            return None
        task.wait_until = Mock(side_effect=wait)
        def verified():
            task._material_name_verified = True
        task.teleport_to_configured_boss_and_prepare.side_effect = verified
        return task

    def run_task(self, task, guard=None):
        return task.run_for_profile('account-a', lambda: self.tasks, guard or Mock(), self.service,
                                    activity_ready=True, used_stamina=0)

    def claim_task(self, shape='selection'):
        task = self.runner()
        task._material_target = TARGETS_BY_ID[A]
        task._material_progress = self.progress
        task._material_balance = (180, 100, 280)
        task._seek_reward_interaction = Mock()
        task.daily_stamina_budget = Mock(return_value=180)
        task._claim_dialog = Mock(return_value=(shape, (60,) if shape == 'selection' else (60, 180, box('确认'))))
        task.use_stamina = Mock(return_value=(True, 60))
        task._confirm_stamina_used = Mock(return_value=(120, 100, 220))
        task._claim_confirmation = Mock(return_value=None)
        task.has_claim = task.has_claim_stamina = Mock(return_value=False)
        task._text = Mock(return_value='')
        def wait(probe, **kwargs):
            for _ in range(4):
                value = probe()
                if value:
                    return value
            return None
        task.wait_until = Mock(side_effect=wait)
        return task

    def claim(self, task, guard=None):
        return task._claim_material_reward(lambda: self.tasks, guard or Mock(), True, 0)

    def test_same_run_advances_targets_counts_actual_claims_and_restores_preferences(self):
        task = self.runner()
        original, original_contents = task.config, copy.deepcopy(task.config)
        calls = []
        def collect(*args):
            boss = task._material_target.key
            event = task._material_progress.begin(boss, 60, 'test')
            task._material_progress.resolve(event, True)
            calls.append(boss)
            return 60
        task._claim_material_reward = Mock(side_effect=collect)
        self.assertEqual(MaterialRunResult(3, 180, 'complete'), self.run_task(task))
        self.assertEqual([A, A, B], calls)
        self.assertEqual({A: 2, B: 1}, self.progress.counts())
        self.assertIs(original, task.config)
        self.assertEqual(original_contents, task.config)
        self.assertFalse(task.use_liberation)
        task._release_combat_inputs.assert_called_once()
        self.assertEqual(2, task.teleport_to_configured_boss_and_prepare.call_count)

    def test_shortfall_keeps_targets_and_complete_does_not_farm_first_boss(self):
        task = self.runner()
        task._resources_for_claim.return_value = False
        self.assertEqual('resource_shortfall', self.run_task(task).status)
        task.farm_cycle.assert_not_called()
        for row in self.tasks[MATERIAL_TARGETS]:
            self.progress.correct(row['boss'], row['limit'])
        self.assertEqual('complete', self.run_task(task).status)
        task.teleport_to_configured_boss_and_prepare.assert_not_called()

    def test_pending_blocks_even_disabled_plan_and_stop_propagates_with_cleanup(self):
        event = self.progress.begin(A, 60, 'test')
        self.tasks = {MATERIAL_TARGETS: []}
        task = self.runner()
        with self.assertRaisesRegex(RuntimeError, '待核验'):
            self.run_task(task)
        task.farm_cycle.assert_not_called()
        self.progress.resolve(event, False)
        self.tasks = plan()
        original = task.config
        with self.assertRaises(TaskDisabledException):
            self.run_task(task, Mock(side_effect=TaskDisabledException()))
        self.assertIs(original, task.config)
        task._release_combat_inputs.assert_called_once()

    def test_revive_never_counts_as_claim_and_unknown_combat_never_claims(self):
        task = self.runner()
        task.farm_cycle.side_effect = [FarmCycleResult(True, True, False), FarmCycleResult(True, False, False)]
        task._material_combat_finished.return_value = False
        task._claim_material_reward = Mock()
        with self.assertRaises(CombatStateUnknown):
            self.run_task(task)
        task._claim_material_reward.assert_not_called()
        self.assertEqual({}, self.progress.counts())

    def test_normal_combat_without_visible_reward_reaches_echo_and_weekly_claim(self):
        task = self.claim_task()
        self.tasks = plan((1, 0, 0))
        task._material_combat_finished.return_value = False
        task._reward_available = task.find_treasure_icon = Mock(return_value=None)
        task.pickup_dropped_echo.return_value = True
        order = []
        task.pickup_dropped_echo.side_effect = lambda: order.append('echo') or True
        task._seek_reward_interaction.side_effect = lambda: order.append('reward')
        self.assertEqual(MaterialRunResult(1, 60, 'complete'), self.run_task(task))
        self.assertEqual(['echo', 'reward'], order)
        self.assertEqual({A: 1}, self.progress.counts())
        task.farm_cycle.assert_called_once_with(pickup_echo=False)
        task.use_stamina.assert_called_once_with(once=60, must_use=180, allow_backup=False, max_claims=1)

    def test_no_echo_still_claims_and_missing_combat_never_collects_or_claims(self):
        self.tasks = plan((1, 0, 0))
        task = self.claim_task()
        self.assertEqual(MaterialRunResult(1, 60, 'complete'), self.run_task(task))
        task.pickup_dropped_echo.assert_called_once()
        task.use_stamina.assert_called_once()
        self.progress.correct(A, 0)
        task = self.claim_task()
        task.farm_cycle.side_effect = None
        task.farm_cycle.return_value = FarmCycleResult(False, False, False)
        with self.assertRaises(CombatStateUnknown):
            self.run_task(task)
        task.pickup_dropped_echo.assert_not_called()
        task.use_stamina.assert_not_called()

    def test_echo_stop_propagates_without_reward_and_releases_movement(self):
        task = self.claim_task()
        task.pickup_dropped_echo.side_effect = TaskDisabledException('manual stop')
        with self.assertRaises(TaskDisabledException):
            self.run_task(task)
        task.use_stamina.assert_not_called()
        task._release_movement.assert_called_once()
        self.assertEqual({}, self.progress.pending())
        self.assertEqual({}, self.progress.counts())

    def test_post_combat_reappearance_resumes_battle_before_echo_or_reward(self):
        task = self.runner()
        task._material_name_verified = True
        task.has_target.return_value = True
        self.assertFalse(task._wait_material_post_combat(FarmCycleResult(True, False, False)))
        task.pickup_dropped_echo.assert_not_called()
        task.send_key.assert_not_called()

    def test_echo_f_never_triggers_reward_or_unselected_absorption(self):
        task = self.runner()
        task._material_phase = 'echo'
        task._selected_reward_interaction = Mock(return_value=None)
        task.find_f_with_text = Mock(return_value=True)  # Scrolled to absorption, not yet selected.
        task.has_claim = task.has_claim_stamina = Mock(return_value=False)
        self.assertFalse(task.pick_f())
        task.send_key.assert_not_called()
        task._selected_reward_interaction.side_effect = [None, box('吸收'), None]
        self.assertTrue(task.pick_echo())
        task.send_key.assert_called_once_with('f', after_sleep=.6)
        task._selected_reward_interaction.assert_called_with('吸收')

    def test_multi_phase_hint_prevents_early_post_combat_handoff(self):
        task = self.runner()
        task._material_name_verified = True
        task._task_hint_phase = Mock(return_value='combat')
        task.out_of_combat_reason = task.TARGET_GONE_END_REASON
        with self.assertRaises(CombatStateUnknown):
            task._wait_material_post_combat(FarmCycleResult(True, False, False))
        task.send_key.assert_not_called()
        self.assertFalse(task.skip_combat_check)

    def test_claim_f_retry_reuses_pending_event_and_confirms_cost_only_once(self):
        task = self.claim_task('confirm')
        task._claim_dialog.side_effect = [None, ('confirm', (60, 180, box('确认'))),
                                        ('confirm', (60, 180, box('确认'))),
                                        ('confirm', (60, 180, box('确认')))]
        task._reward_available = Mock(return_value=box('领取奖励'))
        with patch('src.task.WorldBossMaterialTask.time.monotonic', side_effect=[0, 4, 4]):
            self.assertEqual(60, self.claim(task))
        self.assertEqual(2, task.send_key.call_count)
        task.click_box.assert_called_once()
        self.assertEqual({A: 1}, self.progress.counts())
        self.assertEqual({}, self.progress.pending())

    def test_partial_reward_dialog_permanently_blocks_f_retry(self):
        task = self.claim_task()
        task._claim_dialog.return_value = None
        task._text.return_value = '领取奖励'
        task._reward_available = Mock(return_value=box('领取奖励'))
        with patch('src.task.WorldBossMaterialTask.time.monotonic', side_effect=[0]):
            with self.assertRaises(CombatStateUnknown):
                self.claim(task)
        task.send_key.assert_called_once_with('f', after_sleep=.6)
        task.use_stamina.assert_not_called()
        self.assertEqual({}, self.progress.counts())
        self.assertEqual(1, len(self.progress.pending()))

    def test_shared_echo_search_routes_all_methods_without_starting_another_fight(self):
        task = self.runner()
        task.log_info = task.incr_drop = Mock()
        task.pick_echo = Mock(return_value=False)
        task.yolo_find_echo = Mock(return_value=(True, False))
        task.run_in_circle_to_find_echo = Mock(return_value=False)
        task.walk_find_echo = Mock(return_value=True)
        task.yolo_time_out, task.yolo_threshold = 12, .5
        del task.pickup_dropped_echo
        for method, expected in (('Yolo', True), ('Run in Circle', False), ('Walk', True)):
            task.config['Echo Pickup Method'] = method
            self.assertEqual(expected, task.pickup_dropped_echo())
        task.yolo_find_echo.assert_called_once_with(turn=False, use_color=False, time_out=12, threshold=.5)
        task.run_in_circle_to_find_echo.assert_called_once_with(circle_count=2)
        task.walk_find_echo.assert_called_once()
        task.farm_cycle.assert_not_called()

    def test_pending_is_durable_before_f_and_failed_begin_sends_no_input(self):
        task = self.claim_task()
        task.send_key.side_effect = lambda *_args, **_kwargs: self.assertEqual(1, len(self.progress.pending()))
        self.assertEqual(60, self.claim(task))
        self.assertEqual({A: 1}, self.progress.counts())
        self.assertEqual({}, self.progress.pending())
        task.use_stamina.assert_called_once_with(once=60, must_use=180, allow_backup=False, max_claims=1)
        task = self.claim_task()
        with patch.object(task._material_progress, 'begin', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.claim(task)
        task.send_key.assert_not_called()

    def test_unknown_dialog_fee_debit_and_failed_commit_remain_pending(self):
        for failure in ('dialog', 'fee', 'debit', 'commit', 'changed_dialog'):
            with self.subTest(failure=failure):
                progress = WorldBossMaterialProgress(self.service, failure)
                task = self.claim_task()
                task._material_progress = progress
                if failure == 'dialog':
                    task._claim_dialog.return_value = None
                elif failure == 'fee':
                    task._claim_dialog.return_value = ('selection', (120,))
                elif failure == 'debit':
                    task.use_stamina.side_effect = RuntimeError('未确认扣除')
                elif failure == 'commit':
                    task._material_progress.resolve = Mock(side_effect=OSError('disk full'))
                elif failure == 'changed_dialog':
                    task._claim_dialog.side_effect = [('selection', (60,)), ('selection', (60,)), None]
                with self.assertRaises((RuntimeError, OSError)):
                    self.claim(task)
                self.assertEqual({}, progress.counts())
                self.assertEqual(1, len(progress.pending()))
                self.assertLessEqual(task.use_stamina.call_count, 1)

    def test_plan_change_before_final_click_cancels_without_spending(self):
        task = self.claim_task()
        guard = Mock(side_effect=[None, None])
        def change():
            if task.send_key.called:
                self.tasks = {MATERIAL_TARGETS: []}
        guard.side_effect = change
        self.assertIsNone(self.claim(task, guard))
        task.use_stamina.assert_not_called()
        self.assertEqual({}, self.progress.pending())

    def test_single_confirmation_once_debit_verified_and_evidence_failure_not_replayed(self):
        task = self.claim_task('confirm')
        task.screenshot.side_effect = OSError('screenshot failed')
        self.assertEqual(60, self.claim(task))
        task.click_box.assert_called_once()
        task._confirm_stamina_used.assert_called_once_with(280, 60, before_balance=(180, 100, 280))
        task.use_stamina.assert_not_called()
        self.assertEqual({A: 1}, self.progress.counts())
        self.assertEqual({}, self.progress.pending())

    def test_material_claim_handler_never_uses_echo_cancellation(self):
        task = self.runner()
        task.has_claim = Mock(return_value=True)
        with self.assertRaises(CombatStateUnknown):
            task.handle_claim_button()
        task.send_key.assert_not_called()
        task.wait_until = Mock(side_effect=[True, False])
        task.sleep = Mock()
        BaseWWTask.handle_claim_button(task)
        task.send_key.assert_called_once_with('esc')

    def test_name_matching_own_row_fragmented_alias_and_rejects_nightmare(self):
        target = TARGETS_BY_ID[A]
        title, action = box(target.name), box('前往', 800, 320)
        self.assertIs(action, material_target_button([box('其他首领', y=200), title, action], target, 1080))
        self.assertIsNone(material_target_button([title, box('前往', 800, 480)], target, 1080))
        self.assertIsNone(material_target_button([title, box(target.name, y=380), action], target, 1080))
        self.assertIs(action, material_target_button([box('无', width=25), box('冠者', x=426, width=55), action], target, 1080))
        self.assertTrue(matches_health_title('无冠者 Lv.90', target))
        self.assertFalse(matches_health_title('梦魇·无冠者 Lv.90', target))
        self.assertTrue(matches_health_title('异构武装·加尔古耶', TARGETS_BY_ID['world_sentry']))

    def test_boss_identity_probe_does_not_recurse_into_combat_check(self):
        task = self.runner()
        task._material_name_verified = False
        task.has_target = Mock(return_value=True)
        task.in_combat = Mock(side_effect=AssertionError('recursive combat detection'))
        task._verify_material_boss_title = Mock()
        task.check_boss_name()
        task._verify_material_boss_title.assert_called_once()
        task.in_combat.assert_not_called()
        task.in_realm_check = Mock()
        self.assertTrue(task.on_combat_check())
        task.in_combat.assert_not_called()

    def test_lady_health_full_name_and_split_level_without_broadening_list_names(self):
        target = TARGETS_BY_ID['world_lady_of_the_sea']
        self.assertTrue(matches_health_title('Lv.85海之女·荣光的灰烬', target))
        self.assertTrue(matches_health_title('Lv.85海之女・荣光的灰烬', target))
        self.assertFalse(matches_target('海之女·荣光的灰烬', target))
        for value in ('梦魇·海之女·荣光的灰烬', '海之女·其他形态', '85海之女·荣光的灰烬'):
            self.assertFalse(matches_health_title(value, target))
        parts = [box('LV.', 1067, 20, 49), box('85海之女·荣光的灰烬', 1118, 20, 388)]
        self.assertTrue(matches_health_title_boxes(parts, target, 1440))
        parts[0].y = 80
        self.assertFalse(matches_health_title_boxes(parts, target, 1440))
        parts[0].y = 20
        parts[1].x = 1300
        self.assertFalse(matches_health_title_boxes(parts, target, 1440))

    def test_standalone_entry_clears_stale_combat_before_delegated_navigation_and_on_failure(self):
        task = self.runner()
        task.config.update({'首领关卡': TARGETS_BY_ID[A].name, '领取次数': 1})
        task._in_combat = True
        task._in_liberation = True
        task.skip_combat_check = True
        task.in_combat = Mock(side_effect=AssertionError('stale combat sleep probe'))
        daily = Mock()
        def navigation(*args):
            self.assertFalse(task._in_combat)
            self.assertFalse(task.in_liberation)
            self.assertFalse(task.skip_combat_check)
            task.sleep_check()  # Executor dispatches sleep checks to the current material task.
            task._in_combat = True
            task.skip_combat_check = True
            raise RuntimeError('battle failure')
        daily.run_world_boss_material_only.side_effect = navigation
        task.get_task_by_class = Mock(return_value=daily)
        with self.assertRaisesRegex(RuntimeError, 'battle failure'):
            task.run()
        self.assertFalse(task._in_combat)
        self.assertFalse(task.skip_combat_check)
        task.in_combat.assert_not_called()

    def test_profile_failure_clears_combat_state_and_allows_repeated_entry(self):
        task = self.runner()
        def fail(**kwargs):
            task._in_combat = True
            task._in_liberation = True
            raise CombatStateUnknown('boss identity failed')
        task.farm_cycle.side_effect = fail
        with self.assertRaises(CombatStateUnknown):
            self.run_task(task)
        self.assertFalse(task._in_combat)
        self.assertFalse(task.in_liberation)
        self.assertFalse(task.skip_combat_check)
        self.assertIsNone(task._material_target)
        self.assertEqual({}, self.progress.counts())
        self.assertEqual({}, self.progress.pending())
        def next_resource_check(*args):
            self.assertFalse(task._in_combat)
            task.sleep_check()
            return False
        task._resources_for_claim.side_effect = next_resource_check
        self.assertEqual(MaterialRunResult(0, 0, 'resource_shortfall'), self.run_task(task))

    def test_old_reward_without_verified_boss_never_claimed(self):
        task = self.runner()
        task.teleport_to_configured_boss_and_prepare.side_effect = None
        task.farm_cycle.side_effect = None
        task._claim_material_reward = Mock()
        with self.assertRaises(CombatStateUnknown):
            self.run_task(task)
        task._claim_material_reward.assert_not_called()

    def test_successful_claim_survives_exit_failure_and_next_entry_does_not_repeat(self):
        self.tasks = plan((1, 0, 0))
        task = self.claim_task()
        task.ensure_main.side_effect = RuntimeError('exit failed')
        with self.assertRaisesRegex(RuntimeError, 'exit failed'):
            self.claim(task)
        self.assertEqual({A: 1}, self.progress.counts())
        fresh = self.runner()
        self.assertEqual('complete', self.run_task(fresh).status)
        fresh.farm_cycle.assert_not_called()

    def test_resource_refresh_rechecks_authorization_and_reenters_scene(self):
        task = self.runner()
        del task._resources_for_claim
        task.openF2Book = Mock()
        task.daily_stamina_budget = BaseWWTask.daily_stamina_budget
        task.prepare_daily_reserve = Mock(side_effect=[(20, 60, 80), (60, 20, 80)])
        policy = SimpleNamespace(refresh=Mock(), activity_ready=False)
        with patch.object(WorldBossMaterialTask, 'executor', new_callable=PropertyMock,
                          return_value=SimpleNamespace(_daily_reserve_policy=policy)):
            self.assertTrue(task._resources_for_claim(60, False, 120))
        policy.refresh.assert_called_once()
        self.assertTrue(task._material_reenter)
        self.assertEqual((60, 20, 80), task._material_balance)
        self.assertEqual(2, task.prepare_daily_reserve.call_count)

    def test_second_daily_entry_same_uuid_sees_committed_claim_other_uuid_is_empty(self):
        self.tasks = plan((1, 0, 0))
        self.assertEqual(60, self.claim(self.claim_task()))
        task = self.runner()
        self.assertEqual(MaterialRunResult(0, 0, 'complete'), self.run_task(task))
        task.farm_cycle.assert_not_called()
        self.assertEqual({}, WorldBossMaterialProgress(self.service, 'account-b').counts())

    def test_fee_reader_requires_dialog_and_never_uses_reward_amount(self):
        task = self.runner()
        task.has_claim_stamina = Mock(return_value=True)
        task.ocr = Mock(return_value=[box('消耗：60结晶波片')])
        self.assertEqual(60, task._read_claim_cost())
        task.ocr.return_value = [box('4'), box('5'), box('60')]
        self.assertIsNone(task._read_claim_cost())
        task.ocr.return_value = [box('×60'), box('×120')]
        self.assertIsNone(task._read_claim_cost())
        task.has_claim_stamina.return_value = False
        self.assertIsNone(task._read_claim_cost())

    def test_shared_cycle_material_skips_echo_ordinary_still_picks_it(self):
        task = self.runner()
        del task.farm_cycle
        del task.pickup_dropped_echo
        task._just_entered_boss_realm = True
        task._has_treasure, task.is_revived, task.combat_wait_time = False, False, 0
        task.bypass_end_wait = True
        for name in ('in_realm_check', 'manage_boss_interactions', 'log_debug', 'log_info', 'sleep',
                     'check_boss_name', 'incr_drop'):
            setattr(task, name, Mock())
        task.in_combat = Mock(return_value=True)
        task.combat_once = Mock(return_value=True)
        task.pick_echo = Mock(return_value=True)
        self.assertEqual(FarmCycleResult(True, False, False), task.farm_cycle(pickup_echo=False))
        task.pick_echo.assert_not_called()
        task._just_entered_boss_realm = True
        self.assertEqual(FarmCycleResult(True, False, True), task.farm_cycle())
        task.pick_echo.assert_called_once()

    def daily(self):
        task = object.__new__(DailyTask)
        task.support_tasks = ['Tacet Suppression', 'Forgery Challenge', 'Simulation Challenge']
        task._verified_profile_id = 'account-a'
        task.integrity_service = self.service
        task._active_profile_id = Mock(return_value='account-a')
        task._material_plan_tasks = Mock(side_effect=lambda: self.tasks)
        task._profile_get = Mock(side_effect=lambda key, default=None: self.tasks.get(key, default))
        task._guard_bound_profile_identity = Mock()
        task._publish_daily_stage, task.info_set, task.log_info, task.ensure_main = Mock(), Mock(), Mock(), Mock()
        task.open_daily = Mock(return_value=(120, True))
        children = {cls: Mock() for cls in (WorldBossMaterialTask, TacetTask, ForgeryTask, SimulationTask, MaterialPlannerTask)}
        task.get_task_by_class = Mock(side_effect=children.__getitem__)
        return task, children

    def test_daily_fallback_uses_each_account_choice_and_planner(self):
        for target, cls, method in [('Tacet Suppression', TacetTask, 'farm_tacet'),
                                    ('Forgery Challenge', ForgeryTask, 'farm_forgery'),
                                    ('Simulation Challenge', SimulationTask, 'farm_simulation')]:
            with self.subTest(target=target):
                self.tasks = {**plan(), 'Which to Farm': target}
                task, children = self.daily()
                children[WorldBossMaterialTask].run_for_profile.return_value = MaterialRunResult(2, 120, 'complete')
                self.assertEqual(target, task._run_profile_stamina(self.tasks, activity_ready=False, used_stamina=0))
                getattr(children[cls], method).assert_called_once_with(daily=True, config=self.tasks,
                                                                       activity_ready=True, used_stamina=120)
                self.assertEqual('account-a', children[WorldBossMaterialTask].run_for_profile.call_args.args[0])
        self.tasks[MATERIAL_PLANNER] = True
        task, children = self.daily()
        children[WorldBossMaterialTask].run_for_profile.return_value = MaterialRunResult(0, 0, 'complete')
        self.assertIsNone(task._run_profile_stamina(self.tasks, activity_ready=True, used_stamina=180))
        children[MaterialPlannerTask].run_for_profile.assert_called_once()
        children[SimulationTask].farm_simulation.assert_not_called()

    def test_daily_shortfall_has_no_normal_fallback_and_disabled_pending_reaches_guard(self):
        task, children = self.daily()
        children[WorldBossMaterialTask].run_for_profile.return_value = MaterialRunResult(1, 60, 'resource_shortfall')
        self.assertIsNone(task._run_profile_stamina(self.tasks, activity_ready=False, used_stamina=0))
        children[TacetTask].farm_tacet.assert_not_called()
        self.tasks = {MATERIAL_TARGETS: []}
        self.progress.begin(A, 60, 'test')
        children[WorldBossMaterialTask].run_for_profile.side_effect = RuntimeError('待核验')
        with self.assertRaises(RuntimeError):
            task._run_profile_stamina(self.tasks, activity_ready=True, used_stamina=180)

    def standalone_daily(self, material):
        task, children = self.daily()
        task._executor = SimpleNamespace(_daily_reserve_policy='previous', auto_combat_enabled=True)
        task.config = {}
        task._runtime_overrides = {}
        task.clear_profile_binding = Mock()
        task._ensure_run_account_confirmation = Mock()
        task._readonly_profile_config = Mock(side_effect=lambda: self.tasks)
        task._sync_sequence_options = task.ensure_daily_profiles = Mock()
        task.get_active_profile_name = Mock(return_value='Test account A')
        task.validate_daily_tasks = Mock(side_effect=AssertionError('unrelated daily validation'))
        task.check_weekly_boss = Mock(side_effect=AssertionError('weekly boss must not run'))
        task._run_profile_stamina = Mock(side_effect=AssertionError('normal stamina must not run'))
        task.record_last_completed = Mock()
        children[WorldBossMaterialTask] = material
        return task, children

    def standalone_run(self, task, boss=A, claims=1):
        with patch('src.task.DailyTask.require_account_runtime_for_task'), \
                patch.object(task.integrity_service, 'guard_task_start'), \
                patch.object(DailyTask, 'logged_in', False), \
                patch('src.task.DailyTask.WWOneTimeTask.run'):
            return task.run_world_boss_material_only(boss, claims)

    def test_standalone_real_claim_ledger_is_seen_by_next_daily_entry(self):
        self.tasks = plan((1, 0, 0))
        material = self.runner()
        def claim(*args):
            event = material._material_progress.begin(A, 60, 'test')
            material._material_progress.resolve(event, True)
            return 60
        material._claim_material_reward = Mock(side_effect=claim)
        task, children = self.standalone_daily(material)
        with patch('src.evidence.service.begin_daily_run') as begin:
            begin.side_effect = lambda daily: {'scope': 'world_boss_material', 'profile_id': daily._active_profile_id()}
            self.assertEqual(MaterialRunResult(1, 60, 'complete'), self.standalone_run(task))
        self.assertEqual({A: 1}, self.progress.counts())
        self.assertEqual('world_boss_material', task._completion_run_record['scope'])
        task.open_daily.assert_not_called()
        task.record_last_completed.assert_not_called()
        task.check_weekly_boss.assert_not_called()
        task._run_profile_stamina.assert_not_called()
        for cls, method in ((TacetTask, 'farm_tacet'), (ForgeryTask, 'farm_forgery'),
                            (SimulationTask, 'farm_simulation'), (MaterialPlannerTask, 'run_for_profile')):
            getattr(children[cls], method).assert_not_called()
        self.assertEqual('previous', task._executor._daily_reserve_policy)
        self.assertTrue(task._executor.auto_combat_enabled)
        self.assertEqual({}, task._runtime_overrides)
        material.farm_cycle.reset_mock()
        self.assertEqual(MaterialRunResult(0, 0, 'complete'), self.run_task(material))
        material.farm_cycle.assert_not_called()

    def test_standalone_shortfall_and_pending_ignore_daily_limits_and_do_not_fallback(self):
        for mode in ('disabled', 'complete', 'shortfall', 'pending'):
            with self.subTest(mode=mode):
                self.tasks = plan((0, 0, 0) if mode == 'disabled' else (1, 0, 0))
                self.progress.correct(A, 1 if mode == 'complete' else 0)
                material = self.runner()
                material._resources_for_claim.return_value = False
                task, children = self.standalone_daily(material)
                task.open_daily.return_value = (None, None)
                event = self.progress.begin(A, 60, 'test') if mode == 'pending' else None
                if event:
                    with self.assertRaisesRegex(RuntimeError, '待核验'):
                        self.standalone_run(task)
                    self.progress.resolve(event, False)
                else:
                    self.assertEqual(MaterialRunResult(0, 0, 'resource_shortfall'), self.standalone_run(task))
                material.farm_cycle.assert_not_called()
                task.open_daily.assert_not_called()
                task._run_profile_stamina.assert_not_called()
                task.record_last_completed.assert_not_called()
                self.assertFalse(task._profile_run_active)
                self.assertEqual({}, task._runtime_overrides)
                self.assertEqual('previous', task._executor._daily_reserve_policy)

    def test_standalone_stop_restores_scope_policy_and_releases_inputs(self):
        material = self.runner()
        material.farm_cycle.side_effect = TaskDisabledException('manual stop')
        task, _ = self.standalone_daily(material)
        task._runtime_overrides = {'unrelated': True}
        with self.assertRaises(TaskDisabledException):
            self.standalone_run(task)
        material._release_combat_inputs.assert_called_once()
        task.record_last_completed.assert_not_called()
        self.assertEqual({'unrelated': True}, task._runtime_overrides)
        self.assertEqual('previous', task._executor._daily_reserve_policy)
        self.assertTrue(task._executor.auto_combat_enabled)
        self.assertFalse(task._profile_run_active)

    def test_standalone_resources_never_refresh_daily_or_convert_reserve(self):
        material = self.runner()
        task, _ = self.standalone_daily(material)
        material.openF2Book = Mock()
        material.prepare_daily_reserve = Mock(return_value=(59, 500, 559))
        def resources(cost, ready, used):
            self.assertTrue(ready)
            self.assertIsNone(used)
            self.assertIsNone(task.executor._daily_reserve_policy.refresh)
            with patch.object(WorldBossMaterialTask, 'executor', new_callable=PropertyMock,
                              return_value=task.executor):
                return WorldBossMaterialTask._resources_for_claim(material, cost, ready, used)
        material._resources_for_claim.side_effect = resources
        result = self.standalone_run(task)
        self.assertEqual(MaterialRunResult(0, 0, 'resource_shortfall'), result)
        material.prepare_daily_reserve.assert_called_once_with(60, 0)
        task.open_daily.assert_not_called()
        self.assertEqual('previous', task.executor._daily_reserve_policy)

    def test_visible_entry_delegates_to_production_daily_boundary(self):
        task = object.__new__(WorldBossMaterialTask)
        task.scene = Mock()
        task.config = {'首领关卡': TARGETS_BY_ID[B].name, '领取次数': 3}
        daily = Mock()
        daily.run_world_boss_material_only.return_value = MaterialRunResult(1, 60, 'complete')
        task.get_task_by_class = Mock(return_value=daily)
        self.assertEqual(MaterialRunResult(1, 60, 'complete'), task.run())
        task.get_task_by_class.assert_called_once_with(DailyTask)
        daily.run_world_boss_material_only.assert_called_once_with(B, 3)

    def test_material_confirmation_describes_only_real_material_claims(self):
        from ok import og
        task, _ = self.daily()
        task._runtime_overrides = {'_world_boss_material_only': True, '_world_boss_material_request': (B, 3)}
        task._verified_profile_name = 'A1-Test'
        task._readonly_profile_config = Mock(return_value=self.tasks)
        task._profile_get.side_effect = AssertionError('unrelated daily setting in material prompt')
        bridge = Mock()
        bridge.confirm.return_value = True
        with patch.object(og, 'main_window', SimpleNamespace(daily_run_confirmation=bridge)):
            self.assertTrue(task._confirm_standalone_profile())
        text = bridge.confirm.call_args.args[1]
        self.assertIn('本次只执行世界首领突破材料', text)
        self.assertIn(TARGETS_BY_ID[B].name, text)
        self.assertNotIn(TARGETS_BY_ID[A].name, text)
        self.assertIn('本次领取 3 次', text)
        self.assertIn('不修改每日三目标计划', text)
        self.assertIn('实际消耗体力', text)
        self.assertNotIn('Weekly garden', text)

    def test_selected_boss_counts_exact_claims_above_daily_limit_without_changing_plan(self):
        for daily_tasks in (plan(), {MATERIAL_TARGETS: []}):
            with self.subTest(daily_tasks=daily_tasks):
                self.progress.correct(B, 999999)
                original_tasks = copy.deepcopy(daily_tasks)
                task = self.claim_task()
                original_config = task.config
                read_tasks = Mock(return_value=daily_tasks)
                result = task.run_for_profile('account-a', read_tasks, Mock(), self.service,
                    activity_ready=True, used_stamina=0, request=(B, 3))
                self.assertEqual(MaterialRunResult(3, 180, 'complete'), result)
                self.assertEqual({B: 1000002}, self.progress.counts())
                self.assertEqual(3, task.use_stamina.call_count)
                self.assertEqual(3, task.farm_cycle.call_count)
                read_tasks.assert_not_called()
                self.assertEqual(original_tasks, daily_tasks)
                self.assertIs(original_config, task.config)
                self.assertIsNone(task._material_run_rows)
                self.assertEqual({}, self.progress.pending())

    def test_selected_shortfall_preserves_only_successful_claims_and_new_run_uses_new_count(self):
        self.tasks = {MATERIAL_TARGETS: []}
        task = self.claim_task()
        task._resources_for_claim.side_effect = [True, False]
        self.assertEqual(MaterialRunResult(1, 60, 'resource_shortfall'),
                         self.run_selected(task, A, 3))
        self.assertEqual({A: 1}, self.progress.counts())
        next_run = self.claim_task()
        cycles = iter([FarmCycleResult(True, True, False), FarmCycleResult(True, False, False)])
        def cycle(**kwargs):
            next_run._material_name_verified = True
            return next(cycles)
        next_run.farm_cycle.side_effect = cycle
        self.assertEqual(MaterialRunResult(1, 60, 'complete'), self.run_selected(next_run, A, 1))
        self.assertEqual({A: 2}, self.progress.counts())
        self.assertEqual(2, next_run.farm_cycle.call_count)
        self.assertEqual(1, next_run.use_stamina.call_count)

    def run_selected(self, task, boss, claims):
        return task.run_for_profile('account-a', lambda: self.tasks, Mock(), self.service,
            activity_ready=True, used_stamina=0, request=(boss, claims))

    def test_invalid_standalone_choice_or_count_is_rejected_before_game_or_ledger(self):
        for boss, claims in (('none', 1), (A, 0), (A, -1), (A, True), (A, '2'), (A, 1.5), (A, 10000)):
            with self.subTest(boss=boss, claims=claims):
                task = self.runner()
                with self.assertRaises(ValueError):
                    self.run_selected(task, boss, claims)
                task.farm_cycle.assert_not_called()
                self.assertEqual({}, self.progress.counts())
                self.assertEqual({}, self.progress.pending())
