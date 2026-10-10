import copy
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from tests.fixture_support import make_account_environment, synthetic_identity
from src.task.farming_task_queue import (FARMING_TASKS, new_task, migrate_farming_tasks,
    farming_tasks, ordered_tasks, task_progress, task_status, fresh_farming_tasks,
    instance_reader, require_resolved_claims)
from src.task.world_boss_materials import TARGETS_BY_ID
from src.task.weekly_boss import WEEKLY_AUTO, WEEKLY_BOSSES, WeeklyBossResult
from src.task.forgery_quota_plan import FORGERY_GOALS, FORGERY_MODE


class TestFarmingTaskQueue(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = make_account_environment(self.temp.name)
        self.identity = synthetic_identity('A1')['profile_id']
        self.boss = next(iter(TARGETS_BY_ID))
        self.weekly = WEEKLY_BOSSES[0].key

    def quota(self, domain=1):
        return new_task('forgery', dict(mode='materials', domain=domain, goal=dict(
            goal_id=str(uuid4()), domain=domain, inventory=dict(gold=0, purple=0, blue=0, green=0),
            need=dict(gold=1, purple=0, blue=0, green=0))))

    def test_module_order_and_unlimited_weekly_is_last(self):
        tacet = new_task('tacet', dict(target=2))
        quota = self.quota()
        boss1 = new_task('world_boss', dict(boss=self.boss, limit=2))
        boss2 = new_task('world_boss', dict(boss=self.boss, limit=3))
        long = new_task('weekly', dict(boss=self.weekly, limit=-1))
        weekly = new_task('weekly', dict(boss=self.weekly, limit=2))
        tasks = {FARMING_TASKS: [tacet, quota, boss1, long, boss2, weekly]}
        self.assertEqual([r['id'] for r in ordered_tasks(tasks)], [boss1['id'], boss2['id'], quota['id'], tacet['id']])
        self.assertEqual([r['id'] for r in ordered_tasks(tasks, weekly=True)], [weekly['id'], long['id']])

    def test_same_boss_instances_and_accounts_do_not_share_claims(self):
        a = new_task('world_boss', dict(boss=self.boss, limit=1))
        b = new_task('world_boss', dict(boss=self.boss, limit=1))
        progress = task_progress(a, self.env.integrity, self.identity)
        event = progress.begin(self.boss, 60, 'r')
        progress.resolve(event, True)
        self.assertTrue(task_status(a, self.env.integrity, self.identity)[0])
        self.assertFalse(task_status(b, self.env.integrity, self.identity)[0])
        self.assertFalse(task_status(a, self.env.integrity, synthetic_identity('A3')['profile_id'])[0])

    def test_legacy_migration_is_idempotent_retains_progress_and_unlimited(self):
        from src.task.world_boss_material_plan import MATERIAL_TARGETS
        from src.task.world_boss_material_progress import WorldBossMaterialProgress
        tasks = {MATERIAL_TARGETS: [dict(boss=self.boss, limit=3)] + [dict(boss='none', limit=0)] * 2,
                 'Weekly Boss Target': '无', 'Which to Farm': 'Forgery Challenge',
                 'Which Forgery Challenge to Farm': 7, FORGERY_MODE: 'unlimited'}
        WorldBossMaterialProgress(self.env.integrity, self.identity).correct(self.boss, 2)
        migrate_farming_tasks(tasks)
        rows = farming_tasks(tasks)
        self.assertEqual(rows[1]['params'], dict(mode='unlimited', domain=7))
        self.assertIn('2 / 3', task_status(rows[0], self.env.integrity, self.identity)[2])
        before = copy.deepcopy(tasks)
        migrate_farming_tasks(tasks)
        self.assertEqual(before, tasks)
        new = fresh_farming_tasks(tasks)
        self.assertNotEqual(new[FARMING_TASKS][0]['id'], rows[0]['id'])
        self.assertNotIn('legacy_progress', new[FARMING_TASKS][0])
        self.assertIn('0 / 3', task_status(new[FARMING_TASKS][0], self.env.integrity, self.identity)[2])

    def test_forgery_migration_preserves_goal_and_creates_tacet_fallback(self):
        item = self.quota()
        tasks = {'Which to Farm': 'Forgery Challenge', FORGERY_MODE: 'materials',
                 FORGERY_GOALS: [item['params']['goal']], 'Which Tacet Suppression to Farm': 2,
                 'Weekly Boss Target': '无'}
        progress = task_progress(item, self.env.integrity, self.identity)
        event = progress.begin(item['params']['goal']['goal_id'], 1, 40, 'r')
        progress.resolve(event, 40)
        migrate_farming_tasks(tasks)
        self.assertEqual(tasks[FARMING_TASKS][0]['params']['goal'], item['params']['goal'])
        self.assertIn('25 / 27', task_status(tasks[FARMING_TASKS][0], self.env.integrity, self.identity)[2])
        self.assertEqual(tasks[FARMING_TASKS][1]['params']['target'], 2)

    def test_deleted_pending_instance_still_blocks_claims(self):
        item = new_task('world_boss', dict(boss=self.boss, limit=1))
        journal = task_progress(item, self.env.integrity, self.identity)
        event = journal.begin(self.boss, 60, 'r')
        with self.assertRaisesRegex(RuntimeError, '待核验'):
            require_resolved_claims({FARMING_TASKS: []}, self.env.integrity, self.identity)
        journal.resolve(event, False)
        require_resolved_claims({FARMING_TASKS: []}, self.env.integrity, self.identity)

    def test_current_instance_changes_stop_claim_callback(self):
        item = new_task('world_boss', dict(boss=self.boss, limit=1))
        tasks = {FARMING_TASKS: [copy.deepcopy(item)]}
        reader = instance_reader(lambda: tasks, item)
        tasks[FARMING_TASKS][0]['params']['limit'] = 2
        with self.assertRaisesRegex(RuntimeError, '目标已修改'):
            reader()

    def daily(self, tasks, runner):
        return SimpleNamespace(integrity_service=self.env.integrity, _active_profile_id=lambda: self.identity,
            _material_plan_tasks=lambda: tasks, _weekly_plan_tasks=lambda: tasks,
            _guard_bound_profile_identity=Mock(), sleep=Mock(), _publish_daily_stage=Mock(),
            _overview_event=Mock(), get_task_by_class=lambda cls: runner[cls.__name__])

    def test_production_stamina_dispatch_passes_independent_journals_and_order(self):
        from src.task.farming_task_scheduler import run_stamina_queue
        tacet, quota = new_task('tacet', dict(target=2)), self.quota()
        a = new_task('world_boss', dict(boss=self.boss, limit=1))
        b = new_task('world_boss', dict(boss=self.boss, limit=1))
        tasks = {FARMING_TASKS: [tacet, quota, a, b]}
        calls = []
        def world(*args, progress, **kw):
            calls.append(progress.key)
            event = progress.begin(self.boss, 60, 'r')
            progress.resolve(event, True)
            return SimpleNamespace(spent=60, status='complete')
        runners = {'WorldBossMaterialTask': SimpleNamespace(run_for_profile=world),
                   'ForgeryTask': SimpleNamespace(farm_quota=lambda *a, **kw: calls.append('forgery') or 'complete'),
                   'TacetTask': SimpleNamespace(farm_tacet=lambda **kw: calls.append('tacet'))}
        run_stamina_queue(self.daily(tasks, runners), tasks, activity_ready=False, used_stamina=0)
        self.assertEqual(calls, ['world_boss_material_claims:' + self.identity + ':' + a['id'],
                                'world_boss_material_claims:' + self.identity + ':' + b['id'], 'forgery', 'tacet'])

    def test_weekly_finite_goals_then_game_list_first_exhaust_remaining_claims(self):
        from src.task.WeeklyBossTask import WeeklyBossTask
        from src.task.farming_task_scheduler import run_weekly_queue
        from src.task.weekly_boss_progress import WeeklyBossProgress
        target = WEEKLY_BOSSES[1].key
        a = new_task('weekly', dict(boss=target, limit=1))
        b = new_task('weekly', dict(boss=target, limit=1))
        tasks = {FARMING_TASKS: [a, b]}
        remaining = [3]
        task = object.__new__(WeeklyBossTask)
        task.sleep = Mock()
        task._stage = Mock()
        def run(target, max_claims=None):
            before = remaining[0]
            claims = min(before, max_claims) if max_claims is not None else before
            boss = self.weekly if target == WEEKLY_AUTO else target
            for _ in range(claims):
                progress = task._claim_progress
                progress.resolve(progress.begin(boss, task._claim_week, remaining[0], 'r'), True)
                remaining[0] -= 1
            return WeeklyBossResult(before, claims, remaining[0],
                                    '目标领取额度已达' if remaining[0] else '')
        task.run_for_target = Mock(side_effect=run)
        runner = {'WeeklyBossTask': task}
        result = run_weekly_queue(self.daily(tasks, runner), tasks)
        self.assertEqual((result.initial, result.claimed, result.remaining), (3, 3, 0))
        self.assertEqual([call.args[0] for call in task.run_for_target.call_args_list],
                         [target, target, WEEKLY_AUTO])
        self.assertEqual(task_progress(a, self.env.integrity, self.identity).counts(), {target: 1})
        self.assertEqual(task_progress(b, self.env.integrity, self.identity).counts(), {target: 1})
        self.assertEqual(WeeklyBossProgress(self.env.integrity, self.identity).counts(), {self.weekly: 1})
        result = run_weekly_queue(self.daily(tasks, runner), tasks)
        self.assertEqual((result.initial, result.claimed, result.remaining), (0, 0, 0))

    def test_weekly_historical_material_goals_still_read_and_claim_current_week(self):
        from src.task.WeeklyBossTask import WeeklyBossTask
        from src.task.farming_task_scheduler import run_weekly_queue
        item = new_task('weekly', dict(boss=self.weekly, limit=1))
        tasks = {FARMING_TASKS: [item]}
        task_progress(item, self.env.integrity, self.identity).correct(self.weekly, 1)
        task = object.__new__(WeeklyBossTask)
        task.sleep = Mock()
        task._stage = Mock()
        task.run_for_target = Mock(return_value=WeeklyBossResult(2, 2, 0))
        result = run_weekly_queue(self.daily(tasks, {'WeeklyBossTask': task}), tasks)
        self.assertEqual((result.initial, result.claimed, result.remaining), (2, 2, 0))
        task.run_for_target.assert_called_once_with(WEEKLY_AUTO, max_claims=None)

    def test_weekly_disabled_queue_does_not_start_fallback(self):
        from src.task.farming_task_scheduler import run_weekly_queue
        item = new_task('weekly', dict(boss=self.weekly, limit=1))
        item['enabled'] = False
        task = SimpleNamespace(run_for_plan=Mock())
        result = run_weekly_queue(self.daily({FARMING_TASKS: [item]}, {'WeeklyBossTask': task}),
                                  {FARMING_TASKS: [item]})
        self.assertFalse(result.complete)
        self.assertEqual(result.reason, '计划未启用')
        task.run_for_plan.assert_not_called()

    def test_weekly_partial_claim_returns_without_fallback(self):
        from src.task.farming_task_scheduler import run_weekly_queue
        item = new_task('weekly', dict(boss=self.weekly, limit=2))
        tasks = {FARMING_TASKS: [item]}
        run = Mock(return_value=WeeklyBossResult(3, 1, 2, '当前体力不足'))
        result = run_weekly_queue(self.daily(tasks, {'WeeklyBossTask': SimpleNamespace(run_for_plan=run)}), tasks)
        self.assertEqual((result.claimed, result.remaining, result.reason), (1, 2, '当前体力不足'))
        run.assert_called_once()

    def test_weekly_plan_only_zero_does_not_replace_actual_remaining_check(self):
        from src.task.farming_task_scheduler import run_weekly_queue
        for reason in ('目标已达标', '计划未启用'):
            with self.subTest(reason=reason):
                item = new_task('weekly', dict(boss=self.weekly, limit=1))
                tasks = {FARMING_TASKS: [item]}
                run = Mock(side_effect=[WeeklyBossResult(0, 0, 0, reason),
                                        WeeklyBossResult(3, 0, 3, '当前体力不足')])
                result = run_weekly_queue(
                    self.daily(tasks, {'WeeklyBossTask': SimpleNamespace(run_for_plan=run)}), tasks)
                self.assertEqual((result.initial, result.claimed, result.remaining), (3, 0, 3))
                self.assertFalse(result.complete)
                self.assertEqual(run.call_count, 2)

    def test_weekly_pending_deleted_task_blocks_fallback(self):
        from src.task.farming_task_scheduler import run_weekly_queue
        item = new_task('weekly', dict(boss=self.weekly, limit=1))
        task_progress(item, self.env.integrity, self.identity).begin(self.weekly, 'week', 3, 'r')
        replacement = new_task('weekly', dict(boss=WEEKLY_BOSSES[1].key, limit=1))
        tasks = {FARMING_TASKS: [replacement]}
        task = SimpleNamespace(run_for_plan=Mock())
        with self.assertRaisesRegex(RuntimeError, '待核验'):
            run_weekly_queue(self.daily(tasks, {'WeeklyBossTask': task}), tasks)
        task.run_for_plan.assert_not_called()

    def test_weekly_quota_exhausted_preserves_next_target(self):
        from src.task.farming_task_scheduler import run_weekly_queue
        a = new_task('weekly', dict(boss=self.weekly, limit=5))
        b = new_task('weekly', dict(boss=self.weekly, limit=1))
        tasks = {FARMING_TASKS: [a, b]}
        def run(*args, progress, **kw):
            for remaining in (3, 2, 1):
                progress.resolve(progress.begin(self.weekly, 'week', remaining, 'r'), True)
            return WeeklyBossResult(3, 3, 0)
        result = run_weekly_queue(self.daily(tasks, {'WeeklyBossTask': SimpleNamespace(run_for_plan=run)}), tasks)
        self.assertTrue(result.complete)
        self.assertEqual(task_progress(a, self.env.integrity, self.identity).counts()[self.weekly], 3)
        self.assertEqual(task_progress(b, self.env.integrity, self.identity).counts(), {})

    def test_production_weekly_plan_stops_at_finite_target_with_remaining_allowance(self):
        from src.task.WeeklyBossTask import WeeklyBossTask
        item = new_task('weekly', dict(boss=self.weekly, limit=1))
        tasks = {FARMING_TASKS: [item]}
        progress = task_progress(item, self.env.integrity, self.identity)
        task = object.__new__(WeeklyBossTask)
        task.sleep = Mock()
        task._stage = Mock()
        def run(target, max_claims):
            self.assertEqual(target, self.weekly)
            self.assertEqual(max_claims, 1)
            task._claim_progress.resolve(task._claim_progress.begin(target, 'week', 3, 'r'), True)
            return WeeklyBossResult(3, 1, 2, '目标领取额度已达')
        task.run_for_target = Mock(side_effect=run)
        result = task.run_for_plan(self.identity, instance_reader(lambda: tasks, item), self.env.integrity,
                                   progress=progress, fallback=False)
        self.assertEqual((result.claimed, result.remaining, result.reason), (1, 2, '目标已达标'))
        task.run_for_target.assert_called_once()

    def test_overview_finite_goal_survives_daily_reset_and_infinite_resets(self):
        from src.account_task_state import build_account_task_cards, task_signature
        from src.game_period import game_day_key
        profile = self.env.repository.load_profile(self.identity)
        a = new_task('world_boss', dict(boss=self.boss, limit=1))
        tacet = new_task('tacet', dict(target=2))
        profile.tasks[FARMING_TASKS] = [a, tacet]
        journal = task_progress(a, self.env.integrity, self.identity)
        journal.resolve(journal.begin(self.boss, 60, 'r'), True)
        stamp = '2026-10-06T03:59:00+08:00'
        self.env.integrity.record_completion(self.identity, 'Daily Task', stamp)
        self.env.integrity.set_progress('task_state_v1:' + self.identity, {'farming:' + tacet['id']: dict(
            result='returned', period_id=game_day_key(stamp), signature=task_signature('farming:' + tacet['id'], profile.tasks),
            finished_at=stamp)})
        before = {c.task_id: c for c in build_account_task_cards(profile, self.env.integrity, now=stamp)}
        after = {c.task_id: c for c in build_account_task_cards(profile, self.env.integrity, now='2026-10-06T04:00:00+08:00')}
        self.assertEqual(before['farming:' + tacet['id']].state, 'completed')
        self.assertEqual(after['farming:' + tacet['id']].state, 'pending')
        self.assertEqual(after['farming:' + a['id']].state, 'completed')


if __name__ == '__main__':
    unittest.main()
