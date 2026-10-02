import copy
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from src.config_integrity import ConfigIntegrityService
from src.task.weekly_boss import WEEKLY_AUTO, WEEKLY_BOSSES, WEEKLY_TARGET, WeeklyBossResult
from src.task.weekly_boss_plan import WEEKLY_PLAN, weekly_plan, choose_weekly_target, plan_revision
from src.task.weekly_boss_progress import WeeklyBossProgress, preserve_weekly_progress
from src.task.WeeklyBossTask import WeeklyBossTask
from tests import TestWeeklyBossTask as weekly_tests

A, B, C, D = [b.key for b in WEEKLY_BOSSES[:4]]


class TestWeeklyBossPlan(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = ConfigIntegrityService(self.temp.name)
        self.progress = WeeklyBossProgress(self.service, 'profile-a')

    def rows(self, limits=(6, 4, 3)):
        return [{'boss': boss, 'limit': limit} for boss, limit in zip((A, B, C), limits)]

    def test_priority_remaining_and_game_first_fallback(self):
        rows = self.rows()
        self.assertEqual((A, 1, '优先目标'), choose_weekly_target(rows, {A: 5}))
        self.assertEqual((B, 4, '优先目标'), choose_weekly_target(rows, {A: 6}))
        self.assertEqual((WEEKLY_AUTO, None, '游戏列表首项保底'),
                         choose_weekly_target(rows, {A: 6, B: 4, C: 3}))
        self.assertIsNone(choose_weekly_target(self.rows((0, 0, 0)), {}))

    def test_legacy_and_validation(self):
        self.assertEqual({'boss': A, 'limit': -1}, weekly_plan({WEEKLY_TARGET: A})[0])
        self.assertIsNone(choose_weekly_target(weekly_plan({WEEKLY_TARGET: '无'}), {}))
        for rows in ([{'boss': A, 'limit': 1}], self.rows((True, 4, 3)),
                     self.rows((-2, 4, 3)), self.rows((10000, 4, 3)),
                     [{'boss': A, 'limit': 1}] * 3,
                     [{'boss': WEEKLY_AUTO, 'limit': 3}, *self.rows()[1:]]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                weekly_plan({WEEKLY_PLAN: rows})

    def test_atomic_confirmation_idempotence_restart_and_account_isolation(self):
        event = self.progress.begin(A, 'week1', 3, 'rev')
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.progress.resolve(event, True), range(4)))
        self.assertEqual({A: 1}, self.progress.counts())
        restarted = WeeklyBossProgress(ConfigIntegrityService(self.temp.name), 'profile-a')
        self.assertEqual({A: 1}, restarted.counts())
        event2 = restarted.begin(A, 'week2', 3, 'rev')
        restarted.resolve(event2, True)
        self.assertEqual({A: 2}, restarted.counts())
        self.assertEqual({}, WeeklyBossProgress(self.service, 'profile-b').counts())

    def test_pending_blocks_new_claim_and_manual_reconciliation_is_explicit(self):
        event = self.progress.begin(A, 'week', 3, 'rev')
        with self.assertRaises(RuntimeError):
            self.progress.begin(B, 'week', 2, 'rev')
        with self.assertRaises(RuntimeError):
            self.progress.correct(A, 3)
        self.progress.resolve(event, False)
        self.assertEqual({}, self.progress.counts())
        self.progress.correct(A, 3)
        self.assertEqual({A: 3}, self.progress.counts())
        self.assertEqual(1, len(self.progress.read()['corrections']))

    def test_write_failure_preserves_pending_and_forbids_claim_retry(self):
        event = self.progress.begin(A, 'week', 3, 'rev')
        with patch('src.config_integrity.atomic_write_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.progress.resolve(event, True)
        self.assertIn(event, self.progress.pending())
        self.assertEqual({}, self.progress.counts())

    def test_priority_and_limit_changes_keep_actual_counts(self):
        self.progress.correct(A, 8)
        rows = self.rows()
        self.assertEqual(B, choose_weekly_target(rows, self.progress.counts())[0])
        rows[0]['limit'] = 10
        self.assertEqual((A, 2, '优先目标'), choose_weekly_target(rows, self.progress.counts()))
        self.assertNotEqual(plan_revision(rows), plan_revision(self.rows()))
        rows.reverse()
        self.assertEqual({A: 8}, self.progress.counts())

    def test_restore_preserves_higher_local_count_and_pending_events(self):
        self.progress.correct(A, 8)
        event = self.progress.begin(B, 'week', 3, 'rev')
        current = {'progress': {self.progress.key: self.progress.read()}}
        incoming = {'progress': {self.progress.key: {'counts': {A: 2}, 'events': {}}}}
        restored = preserve_weekly_progress(incoming, copy.deepcopy(current))
        self.assertEqual(8, restored['progress'][self.progress.key]['counts'][A])
        self.assertIn(event, restored['progress'][self.progress.key]['events'])

    def scheduler(self, rows, remaining=3):
        task = object.__new__(WeeklyBossTask)
        task.info = {}
        task.sleep = Mock()
        task._stage = Mock()
        task._open_weekly_book = Mock()
        task._read_remaining = Mock(return_value=remaining)
        state = {'remaining': remaining}
        calls = []
        def segment(target, max_claims=None):
            actual = D if target == WEEKLY_AUTO else target
            before = state['remaining']
            count = min(before, max_claims) if max_claims is not None else before
            for index in range(count):
                event = self.progress.begin(actual, 'week', before - index, 'rev')
                self.progress.resolve(event, True)
            state['remaining'] -= count
            calls.append((target, count))
            return WeeklyBossResult(before, count, state['remaining'],
                                    '目标领取额度已达' if state['remaining'] else '')
        task.run_for_target = Mock(side_effect=segment)
        task.read_tasks = lambda: {WEEKLY_PLAN: rows}
        return task, calls

    def test_same_run_advances_to_second_without_overclaiming_first(self):
        self.progress.correct(A, 5)
        task, calls = self.scheduler(self.rows())
        result = task.run_for_plan('profile-a', task.read_tasks, self.service)
        self.assertEqual([(A, 1), (B, 2)], calls)
        self.assertEqual({A: 6, B: 2}, self.progress.counts())
        self.assertTrue(result.complete)
        self.assertEqual(3, result.claimed)

    def test_all_targets_met_use_game_list_first_not_priority_one(self):
        for row in self.rows():
            self.progress.correct(row['boss'], row['limit'])
        task, calls = self.scheduler(self.rows(), 2)
        task.run_for_plan('profile-a', task.read_tasks, self.service)
        self.assertEqual([(WEEKLY_AUTO, 2)], calls)
        self.assertEqual(6, self.progress.counts()[A])
        self.assertEqual(2, self.progress.counts()[D])

    def test_one_claim_resource_shortfall_preserves_progress_for_next_entry(self):
        task, calls = self.scheduler(self.rows())
        def partial(target, max_claims=None):
            event = self.progress.begin(A, 'week', 3, 'rev')
            self.progress.resolve(event, True)
            return WeeklyBossResult(3, 1, 2, '当前体力不足')
        task.run_for_target.side_effect = partial
        result = task.run_for_plan('profile-a', task.read_tasks, self.service)
        self.assertFalse(result.complete)
        self.assertEqual('当前体力不足', result.reason)
        self.assertEqual({A: 1}, self.progress.counts())
        task.run_for_target.assert_called_once()

    def test_pending_does_not_start_new_battle(self):
        self.progress.begin(A, 'week', 3, 'rev')
        task, _ = self.scheduler(self.rows())
        task.info_set = Mock()
        with self.assertRaisesRegex(RuntimeError, '未核验'):
            task.run_for_plan('profile-a', task.read_tasks, self.service)
        task.run_for_target.assert_not_called()
        task._read_remaining.assert_called_once()

    def test_production_limit_exits_even_with_weekly_rewards_left(self):
        task = weekly_tests.TestWeeklyBossFlow().task(3, final=2)
        result = task.run_weekly(A, max_claims=1)
        self.assertEqual('目标领取额度已达', result.reason)
        self.assertEqual(1, result.claimed)
        self.assertFalse(result.complete)
        task._leave_settlement.assert_called_once_with(False)

    def claim_task(self):
        task = object.__new__(WeeklyBossTask)
        task._fight = Mock()
        task._stage = Mock()
        task._seek_reward_interaction = Mock()
        task.send_key = Mock()
        task._confirm_claim_if_needed = Mock()
        task._settlement = Mock(return_value=True)
        task._wait_for = Mock(return_value=True)
        task._stable_value = Mock(return_value=120)
        task.info_set = Mock()
        task._entry_boss = WEEKLY_BOSSES[0]
        task._claim_progress = self.progress
        task._claim_week, task._claim_remaining, task._claim_revision = 'week', 3, 'rev'
        return task

    def test_real_claim_saves_before_balance_or_exit_failure(self):
        task = self.claim_task()
        task._stable_value.side_effect = RuntimeError('capture lost after settlement')
        with self.assertRaises(RuntimeError):
            task._fight_and_claim(60)
        self.assertEqual({A: 1}, self.progress.counts())
        self.assertFalse(self.progress.pending())

    def test_real_claim_unknown_result_keeps_pending_without_increment(self):
        task = self.claim_task()
        task._wait_for.side_effect = RuntimeError('settlement unknown')
        with self.assertRaises(RuntimeError):
            task._fight_and_claim(60)
        self.assertEqual({}, self.progress.counts())
        self.assertEqual(1, len(self.progress.pending()))
        task.send_key.assert_called_once_with('f')

    def test_real_claim_begin_write_failure_never_sends_f(self):
        task = self.claim_task()
        with patch('src.config_integrity.atomic_write_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                task._fight_and_claim(60)
        task.send_key.assert_not_called()

    def test_real_claim_confirmation_write_failure_does_not_continue(self):
        task = self.claim_task()
        with patch.object(self.progress, 'resolve', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                task._fight_and_claim(60)
        task._stable_value.assert_not_called()
        self.assertEqual(1, len(self.progress.pending()))

    def test_saved_plan_change_exits_current_boss_before_retry(self):
        task = weekly_tests.TestWeeklyBossFlow().task(3, final=2)
        task._claim_progress = self.progress
        task._claim_revision = plan_revision(self.rows())
        task._claim_read_tasks = lambda: {WEEKLY_PLAN: list(reversed(self.rows()))}
        result = task.run_weekly(A)
        self.assertEqual(1, result.claimed)
        self.assertEqual('目标领取额度已达', result.reason)
        task._leave_settlement.assert_called_once_with(False)


if __name__ == '__main__':
    unittest.main()
