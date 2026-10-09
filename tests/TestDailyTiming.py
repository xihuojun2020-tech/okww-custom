import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ok import TaskDisabledException
from src.daily_timing import DailyTiming, note_requested_start, record_daily_duration
from src.evidence.repository import EvidenceRepository
from src.gui.DailyTimingDialog import history_rows, DailyTimingDialog
from src.task.MultiAccountDailyTask import MultiAccountDailyTask


def stamp(seconds):
    return (datetime.fromisoformat('2026-10-09T09:00:00+08:00') + timedelta(seconds=seconds)).isoformat(), seconds


def task_named(name='MultiAccountDailyTask'):
    task = type(name, (), {})()
    task.info = {}
    task.log_info = Mock()
    task.executor = SimpleNamespace()
    return task


class TestDailyTiming(unittest.TestCase):
    def test_handoff_retry_and_day_total_preserve_first_attempt(self):
        with tempfile.TemporaryDirectory() as root, patch('src.daily_timing.clock', return_value=stamp(100)) as now:
            repo = EvidenceRepository(root)
            task = task_named()
            timer = DailyTiming(task, repo)
            timer.begin_account('one', 'A1')
            timer.executing()
            timer.result(True)
            now.return_value = stamp(160)
            timer.handoff('two', 'A2', '首次')
            timer.executing()
            timer.result(False, ValueError('挑战失败'))
            now.return_value = stamp(260)
            timer.handoff('three', 'A3', '首次')
            timer.result(True)
            now.return_value = stamp(310)
            timer.handoff('two', 'A2', '补跑')
            timer.executing()
            timer.result(True)
            now.return_value = stamp(350)
            timer.finish()
            batch = repo.daily_timings('two')[0]
            attempts = batch['attempts']
            self.assertEqual([a['elapsed_seconds'] for a in attempts], [60, 100, 50, 40])
            self.assertEqual(attempts[1]['finished_at'], attempts[2]['started_at'])
            self.assertEqual(attempts[1]['result'], 'failed')
            self.assertEqual(attempts[1]['reason'], '挑战失败')
            self.assertEqual(attempts[3]['attempt_number'], 2)
            self.assertEqual(batch['elapsed_seconds'], 250)
            self.assertEqual(history_rows([batch], 'two')['2026-10-09']['total'], 140)
            # A manual second run creates a new batch, retaining both earlier attempts.
            now.return_value = stamp(500)
            again = DailyTiming(task, repo)
            again.begin_account('two', 'A2')
            again.result(True)
            now.return_value = stamp(510)
            again.finish()
            batches = repo.daily_timings('two')
            self.assertEqual(len(batches), 2)
            self.assertEqual(batches[0]['attempts'][0]['attempt_number'], 3)
            self.assertEqual(batches[0]['attempts'][0]['phase'], '再次执行')
            self.assertEqual(history_rows(batches, 'two')['2026-10-09']['total'], 150)

    def test_click_start_includes_preparation_and_child_does_not_double_count(self):
        task = task_named()
        child = task_named('DailyTask')
        child.executor = task.executor
        with tempfile.TemporaryDirectory() as root, patch('src.daily_timing.clock', return_value=stamp(0)) as now:
            repo = EvidenceRepository(root)
            with patch('src.evidence.service.get_evidence_service', return_value=SimpleNamespace(repository=repo)):
                note_requested_start(task)
                now.return_value = stamp(20)
                @record_daily_duration
                def child_run(owner):
                    self.assertIsNone(owner.__dict__.get('_daily_timer'))
                    return 'child-result'
                @record_daily_duration
                def parent_run(owner):
                    owner._daily_timer.begin_account('one', 'A1')
                    self.assertEqual(child_run(child), 'child-result')
                    owner._daily_timer.result(True)
                    now.return_value = stamp(70)
                    return 'original-result'
                self.assertEqual(parent_run(task), 'original-result')
            self.assertEqual(repo.daily_timings('one')[0]['attempts'][0]['elapsed_seconds'], 70)
            self.assertIsNone(task.executor._daily_timing_owner)

    def test_save_failure_never_changes_return_value_or_exception(self):
        task = task_named('DailyTask')
        repo = Mock()
        repo.save_daily_timing.side_effect = OSError('disk full')
        repo.daily_timings.return_value = []
        error = ValueError('actual task error')
        with patch('src.evidence.service.get_evidence_service', return_value=SimpleNamespace(repository=repo)):
            @record_daily_duration
            def work(owner, fail=False):
                owner._daily_timer.begin_account('one', 'A1')
                if fail:
                    raise error
                owner._daily_timer.result(True)
                return 42
            self.assertEqual(work(task), 42)
            with self.assertRaises(ValueError) as raised:
                work(task, True)
            self.assertIs(raised.exception, error)
            self.assertIn('耗时记录错误', task.info)

    def test_weekly_garden_and_material_only_do_not_create_daily_records(self):
        for kind, overrides in [('MultiAccountWeeklyGardenTask', {}),
                                ('DailyTask', {'_world_boss_material_only': True}),
                                ('DailyTask', {'_weekly_boss_only': True})]:
            task = task_named(kind)
            task._runtime_overrides = overrides
            with patch('src.evidence.service.get_evidence_service') as service:
                self.assertEqual(record_daily_duration(lambda owner: 42)(task), 42)
            service.assert_not_called()

    def test_stop_and_switch_failure_remain_separate_from_completion(self):
        with tempfile.TemporaryDirectory() as root, patch('src.daily_timing.clock', return_value=stamp(0)) as now:
            repo = EvidenceRepository(root)
            timer = DailyTiming(task_named(), repo)
            timer.begin_account('one', 'A1')
            now.return_value = stamp(60)
            timer.finish(TaskDisabledException())
            self.assertEqual(repo.daily_timings('one')[0]['attempts'][0]['result'], 'stopped')
            timer = DailyTiming(task_named(), repo)
            timer.begin_account('two', 'A2')
            now.return_value = stamp(70)
            timer.finish(ValueError('登录失败'))
            attempt = repo.daily_timings('two')[0]['attempts'][0]
            self.assertEqual(attempt['stage'], '切入账号')
            self.assertEqual(attempt['result'], 'failed')
            self.assertEqual(attempt['elapsed_seconds'], 10)

    def test_timing_observation_keeps_existing_scheduling_call_order(self):
        for success in (True, False):
            task = task_named()
            trace = []
            task.ensure_main = lambda **kw: trace.append('ensure_main')
            task._next_target_account = lambda: trace.append('next_target') or 'A2'
            task._switch_to_login = lambda: trace.append('logout')
            task._finish_sequence = Mock()
            timer = task._daily_timer = Mock()
            task._profile_id_for = lambda account: 'two'
            with patch('src.task.MultiAccountDailyTask.profile_status_label', return_value='A2'), \
                 patch.object(MultiAccountDailyTask, '_prepare_login_after_account_failure',
                              side_effect=lambda *args: trace.append('failure_recovery')):
                self.assertFalse(MultiAccountDailyTask._advance_after_account(task, 'A1', success, ValueError()))
            self.assertEqual(trace, ['ensure_main', 'next_target', 'logout'] if success
                             else ['next_target', 'failure_recovery'])
            timer.queue_handoff.assert_called_once_with('two', 'A2', '首次')
            task._finish_sequence.assert_not_called()

    def test_failed_account_recovery_time_ends_at_actual_logout(self):
        with tempfile.TemporaryDirectory() as root, patch('src.daily_timing.clock', return_value=stamp(0)) as now:
            repo = EvidenceRepository(root)
            timer = DailyTiming(task_named(), repo)
            timer.begin_account('one', 'A1')
            timer.result(False, ValueError('挑战失败'))
            now.return_value = stamp(60)
            timer.queue_handoff('two', 'A2', '首次')
            self.assertIsNone(timer.active['finished_at'])
            now.return_value = stamp(100)
            timer.begin_handoff()
            timer.begin_account('two', 'A2')
            timer.begin_handoff()
            self.assertEqual(len(timer.record['attempts']), 2)
            timer.result(True)
            now.return_value = stamp(200)
            timer.finish()
            attempts = repo.daily_timings('one')[0]['attempts']
            self.assertEqual([a['elapsed_seconds'] for a in attempts], [100, 100])
            self.assertEqual(attempts[0]['finished_at'], stamp(100)[0])

    def test_interrupted_record_has_unknown_end_and_ui_is_read_only(self):
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root, patch('src.daily_timing.clock', return_value=stamp(0)):
            repo = EvidenceRepository(root)
            timer = DailyTiming(task_named(), repo)
            timer.begin_account('one', 'A1')
            timer.record['session'] = 'previous-process'
            timer.save()
            rows = history_rows(repo.daily_timings('one'), 'one')['2026-10-09']
            self.assertEqual(rows['rows'][0][4], '中断（结束时间未知）')
            self.assertEqual(rows['rows'][0][3], '未知')
            before = repo.daily_timings('one')
            dialog = DailyTimingDialog(repo, 'one')
            dialog.refresh()
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
            self.assertEqual(repo.daily_timings('one'), before)
            dialog.close()


if __name__ == '__main__':
    unittest.main()
