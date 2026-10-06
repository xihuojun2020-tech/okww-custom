import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from src.config_integrity import ConfigIntegrityService
from src.task.ForgeryTask import ForgeryTask
from src.task.DailyTask import DailyTask, DailyActivityIncomplete, DailyActivityDetectionError
from src.task.TacetTask import TacetTask
from src.task.NightmareNestTask import NightmareNestTask
from src.task.forgery_quota_plan import FORGERY_GOALS
from src.task.forgery_quota_progress import ForgeryQuotaProgress
from src.task.daily_reserve_policy import DailyReservePolicy
from tests.TestForgeryQuotaPlan import goal


class TestForgeryQuotaIntegration(unittest.TestCase):
    def test_migrated_legacy_forgery_uses_unlimited_path_without_tacet_handoff(self):
        from src.account_task_policy import migrate_task_policy
        config = {'Which to Farm': 'Forgery Challenge', 'Which Forgery Challenge to Farm': 7,
                  FORGERY_GOALS: [goal(7, 25)]}
        migrated, _ = migrate_task_policy({'profiles': {'one': {'task_config': config}}})
        config = migrated['profiles']['one']['task_config']
        task = Mock(spec=DailyTask)
        task.integrity_service = Mock(spec=ConfigIntegrityService)
        task.integrity_service.get_progress_entries.return_value = {}
        task.integrity_service.get_progress.side_effect = lambda key, default=None: default
        task._active_profile_id.return_value = 'one'
        task._material_plan_tasks.return_value = config
        task._verified_profile_id = 'one'
        task.support_tasks = ['Tacet Suppression', 'Forgery Challenge', 'Simulation Challenge']
        task._profile_get.side_effect = lambda key, default=None: config.get(key, default)
        forgery, tacet = Mock(), Mock()
        task.get_task_by_class.side_effect = lambda cls: {ForgeryTask: forgery, TacetTask: tacet}[cls]
        DailyTask._run_profile_stamina(task, config, activity_ready=True, used_stamina=0)
        from src.task.farming_task_queue import project_task, FARMING_TASKS
        forgery.farm_forgery.assert_called_once_with(daily=True, config={**config, **project_task(next(row for row in config[FARMING_TASKS] if row['kind'] == 'forgery'))}, activity_ready=True, used_stamina=0)
        forgery.farm_quota.assert_not_called()
        tacet.farm_tacet.assert_not_called()
        legacy = Mock(spec=DailyTask)
        legacy.integrity_service = None
        legacy.default_config = {}
        old = dict(config)
        old.pop('Forgery Limit Mode')
        legacy.load_daily_profiles.return_value = {'old': old}
        DailyTask._migrate_profiles(legacy)
        legacy.log_error.assert_not_called()
        legacy.save_daily_profiles.assert_called_once()
        self.assertEqual('unlimited', old['Forgery Limit Mode'])
        self.assertEqual(7, old['Which Forgery Challenge to Farm'])

    def test_quota_claims_sequence_and_confirmed_downshift(self):
        with tempfile.TemporaryDirectory() as root:
            service = ConfigIntegrityService(root)
            rows = [goal(1, 49), goal(2, 50)]
            task = Mock(spec=ForgeryTask)
            task.executor = SimpleNamespace(_daily_reserve_policy=None)
            task.daily_stamina_budget.return_value = 180
            task.prepare_daily_stamina.return_value = (80, 0, 80)
            claims = []
            def farm(*args, **kwargs):
                tracker = task.claim_tracker
                tracker.begin_claim()
                claims.append((tracker.row['domain'], tracker.max_claims))
                tracker.collect_claim(40 * tracker.max_claims)
            task.farm_domain_with_recovery_loop.side_effect = farm
            self.assertEqual('complete', ForgeryTask.farm_quota(task, 'a1',
                lambda: {FORGERY_GOALS: rows}, service, Mock()))
            self.assertEqual([(1, 1), (1, 1), (2, 2)], claims)
            self.assertEqual([50, 50], list(ForgeryQuotaProgress(service, 'a1').earned().values()))

    def test_pending_and_mid_combat_edit_stop_consumption(self):
        with tempfile.TemporaryDirectory() as root:
            service = ConfigIntegrityService(root)
            row = goal()
            task = Mock(spec=ForgeryTask)
            task.executor = SimpleNamespace(_daily_reserve_policy=None)
            task.daily_stamina_budget.return_value = 0
            task.prepare_daily_stamina.return_value = (80, 0, 80)
            tasks = {FORGERY_GOALS: [row]}
            def edited(*args, **kwargs):
                tasks[FORGERY_GOALS][0]['need']['green'] += 1
                task.claim_tracker.begin_claim()
            task.farm_domain_with_recovery_loop.side_effect = edited
            with self.assertRaisesRegex(RuntimeError, '已修改'):
                ForgeryTask.farm_quota(task, 'a1', lambda: tasks, service, Mock())
            self.assertEqual({}, ForgeryQuotaProgress(service, 'a1').pending())
            p = ForgeryQuotaProgress(service, 'a1')
            p.begin(row['goal_id'], 1, 40, 'rev')
            with self.assertRaisesRegex(RuntimeError, '待核验'):
                ForgeryTask.farm_quota(task, 'a1', lambda: tasks, service, Mock())

    def test_quota_complete_hands_off_account_tacet_without_scanner(self):
        task = Mock(spec=DailyTask)
        task._verified_profile_id = 'a1'
        task.integrity_service = None
        task.support_tasks = ['Tacet Suppression', 'Forgery Challenge', 'Simulation Challenge']
        config = {'Which to Farm': 'Forgery Challenge', 'Which Tacet Suppression to Farm': 3,
                  'Material Planner Enabled': True, FORGERY_GOALS: [goal()]}
        task._profile_get.side_effect = lambda key, default=None: config.get(key, default)
        forgery, tacet = Mock(), Mock()
        forgery.farm_quota.return_value = 'complete'
        task.get_task_by_class.side_effect = lambda cls: {ForgeryTask: forgery, TacetTask: tacet}[cls]
        self.assertEqual('Forgery Challenge', DailyTask._run_profile_stamina(task, config,
                         activity_ready=False, used_stamina=0))
        tacet.farm_tacet.assert_called_once_with(daily=True, config=config, activity_ready=False, used_stamina=0)

    def test_daily_sequence_selected_lists_ignore_legacy_flags_and_no_middle_reads(self):
        for selected, final in ((True, True), (False, True), (False, False), (False, None)):
            with self.subTest(selected=selected, final=final):
                task = Mock(spec=DailyTask)
                task.integrity_service = None
                task._runtime_overrides = {}
                task._verified_profile_id = 'a1'
                task.support_tasks = ['Tacet Suppression', 'Forgery Challenge', 'Simulation Challenge']
                config = {'Tacet Discord Nests to Farm': ['a'] if selected else [],
                          'Auto Farm all Nightmare Nest': False, 'Farm Nightmare Nest for Daily Echo': False,
                          'Logout PC After Daily Task': False, 'Screenshot After Daily Task': False,
                          'Record After Daily Task': False}
                task._profile_get.side_effect = lambda key, default=None: config.get(key, default)
                task._daily_step_completed.return_value = False
                task._readonly_profile_config.return_value = config
                task.open_daily.return_value = (0, False)
                task._run_profile_stamina.return_value = None
                task.claim_daily.return_value = final
                task._finish_daily_rewards.side_effect = lambda ready: DailyTask._finish_daily_rewards(task, ready)
                task.executor = SimpleNamespace(_daily_reserve_policy=None)
                order = Mock()
                for name in ('open_daily', 'check_weekly_boss', 'run_task_by_class', '_run_profile_stamina', 'claim_daily'):
                    order.attach_mock(getattr(task, name), name)
                with patch('src.task.DailyTask.require_account_runtime_for_task'), \
                        patch('src.task.DailyTask.WWOneTimeTask.run'), patch('src.evidence.service.begin_daily_run'):
                    if final is True:
                        DailyTask._run_daily_inner(task)
                    else:
                        with self.assertRaises(DailyActivityDetectionError if final is None else DailyActivityIncomplete):
                            DailyTask._run_daily_inner(task)
                names = [call[0] for call in order.mock_calls]
                self.assertEqual(['open_daily', 'check_weekly_boss'] + (['run_task_by_class'] if selected else []) +
                                 ['_run_profile_stamina', 'claim_daily'], names)
                task._complete_missing_daily_echo.assert_not_called()
                task._complete_missing_daily_stamina.assert_not_called()

    def test_conversion_refresh_only_when_needed_and_fresh_budget(self):
        from src.task.BaseWWTask import BaseWWTask
        task = Mock(spec=BaseWWTask)
        policy = DailyReservePolicy('a1', stamina_used=0)
        task.executor = SimpleNamespace(_daily_reserve_policy=policy)
        task.daily_stamina_budget = BaseWWTask.daily_stamina_budget
        task.get_verified_stamina.return_value = (40, 500, 540)
        policy.refresh = Mock(side_effect=lambda: (policy.observe(False), setattr(policy, 'stamina_used', 180)))
        BaseWWTask.prepare_daily_stamina(task, 40, 180)
        policy.refresh.assert_not_called()
        task.get_verified_stamina.return_value = (20, 500, 520)
        BaseWWTask.prepare_daily_stamina(task, 40, 180)
        policy.refresh.assert_called_once()
        task.prepare_daily_reserve.assert_called_once_with(40, 0)

    def test_existing_stamina_not_capped_by_daily_budget(self):
        from tests.TestStaminaAccounting import TestStaminaAccounting
        from src.task.BaseWWTask import BaseWWTask
        task = TestStaminaAccounting._stamina_task(200, 0)
        self.assertEqual((True, 80), BaseWWTask.use_stamina(task, 40, 40, exhaust_current=True))

    def test_zero_claim_ends_exhaustion_loop_without_reentry(self):
        from src.task.DomainTask import DomainTask
        task = Mock(spec=DomainTask)
        task.executor = SimpleNamespace(_daily_reserve_policy=None)
        task.stamina_once = 40
        task.open_F2_book_and_get_stamina.return_value = (80, 0, 80)
        task.farm_in_domain.return_value = (True, 40)
        teleport = Mock()
        DomainTask.farm_domain_with_recovery_loop(task, 40, teleport, exhaust_current=True)
        teleport.assert_called_once()
        task.farm_in_domain.assert_called_once()

    def test_deselection_stops_before_claim_and_keeps_progress_empty(self):
        with tempfile.TemporaryDirectory() as root:
            service = ConfigIntegrityService(root)
            tasks = {FORGERY_GOALS: [goal()], 'Which to Farm': 'Forgery Challenge'}
            task = Mock(spec=ForgeryTask)
            task.executor = SimpleNamespace(_daily_reserve_policy=None)
            task.daily_stamina_budget.return_value = 0
            task.prepare_daily_stamina.return_value = (80, 0, 80)
            def deselected(*args, **kwargs):
                tasks['Which to Farm'] = '无'
                task.claim_tracker.begin_claim()
            task.farm_domain_with_recovery_loop.side_effect = deselected
            with self.assertRaisesRegex(RuntimeError, '已修改'):
                ForgeryTask.farm_quota(task, 'a1', lambda: tasks, service, Mock())
            self.assertEqual({}, ForgeryQuotaProgress(service, 'a1').earned())
            self.assertEqual({}, ForgeryQuotaProgress(service, 'a1').pending())
