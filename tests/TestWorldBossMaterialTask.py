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
from src.task.world_boss_materials import WORLD_BOSS_TARGETS, material_target_button, matches_health_title
from src.task.world_boss_material_plan import MATERIAL_TARGETS
from src.task.world_boss_material_progress import WorldBossMaterialProgress

A, B, C = [b.key for b in WORLD_BOSS_TARGETS[:3]]


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
        task._in_realm = False
        for name in ('_stage', 'next_frame', 'manage_boss_parameters', 'teleport_to_configured_boss_and_prepare',
                     '_release_combat_inputs', 'send_key', 'back', 'click_box', 'screenshot', 'ensure_main', 'log_warning'):
            setattr(task, name, Mock())
        task.farm_cycle = Mock(return_value=FarmCycleResult(True, False, False))
        def cycle(**kwargs):
            task._material_name_verified = True
            return FarmCycleResult(True, False, False)
        task.farm_cycle.side_effect = cycle
        task._resources_for_claim = Mock(return_value=True)
        task._material_combat_finished = Mock(return_value=True)
        def verified():
            task._material_name_verified = True
        task.teleport_to_configured_boss_and_prepare.side_effect = verified
        return task

    def run_task(self, task, guard=None):
        return task.run_for_profile('account-a', lambda: self.tasks, guard or Mock(), self.service,
                                    activity_ready=True, used_stamina=0)

    def claim_task(self, shape='selection'):
        task = self.runner()
        task._material_target = WORLD_BOSS_TARGETS[0]
        task._material_progress = self.progress
        task._material_balance = (180, 100, 280)
        task._seek_reward_interaction = Mock()
        task.daily_stamina_budget = Mock(return_value=180)
        task._claim_dialog = Mock(return_value=(shape, (60,) if shape == 'selection' else (60, 180, box('确认'))))
        task.use_stamina = Mock(return_value=(True, 60))
        task._confirm_stamina_used = Mock(return_value=(120, 100, 220))
        task._claim_confirmation = Mock(return_value=None)
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
        target = WORLD_BOSS_TARGETS[0]
        title, action = box(target.name), box('前往', 800, 320)
        self.assertIs(action, material_target_button([box('其他首领', y=200), title, action], target, 1080))
        self.assertIsNone(material_target_button([title, box('前往', 800, 480)], target, 1080))
        self.assertIsNone(material_target_button([title, box(target.name, y=380), action], target, 1080))
        self.assertIs(action, material_target_button([box('无', width=25), box('冠者', x=426, width=55), action], target, 1080))
        self.assertTrue(matches_health_title('无冠者 Lv.90', target))
        self.assertFalse(matches_health_title('梦魇·无冠者 Lv.90', target))
        self.assertTrue(matches_health_title('异构武装·加尔古耶', WORLD_BOSS_TARGETS[11]))

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
