import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np

from src.evidence.model import period_for, summarize
from src.evidence.repository import EvidenceRepository


ACCOUNT = '00000000-0000-4000-8000-000000000001'


class TestCompletionEvidence(unittest.TestCase):
    def test_daily_run_observer_preserves_return_stop_and_error(self):
        from contextlib import nullcontext
        from unittest.mock import Mock
        from src.task.DailyTask import DailyTask
        from ok import TaskDisabledException
        for error, expected in ((None, 'returned'), (RuntimeError('failed'), 'failed'),
                                (TaskDisabledException('stopped'), 'stopped')):
            task = SimpleNamespace(clear_profile_binding=Mock(), _guard_bound_profile_identity=Mock(),
                                   account_input_guard=lambda _: nullcontext(),
                                   _run_daily_inner=Mock(side_effect=error, return_value='original'))
            with patch('src.evidence.service.finish_daily_run') as finish:
                if error:
                    with self.assertRaises(type(error)) as raised:
                        DailyTask.run(task)
                    self.assertIs(raised.exception, error)
                else:
                    self.assertEqual(DailyTask.run(task), 'original')
                finish.assert_called_once_with(task, expected)
                self.assertFalse(task._profile_run_active)

    def test_recording_attempts_all_pages_even_with_legacy_partial_selection(self):
        from unittest.mock import Mock
        from src.task.DailyTask import DailyTask
        from src.recording_policy import RECORDING_PAGES
        with tempfile.TemporaryDirectory() as root:
            task = SimpleNamespace(_profile_get=lambda key, default: {'Record Pages': ['任务页']}.get(key, default),
                get_active_profile_name=lambda: 'synthetic', _open_record_page=Mock(return_value=False),
                ensure_main=Mock(), log_warning=Mock(), log_info=Mock(), log_error=Mock(), screenshot=Mock())
            with patch('src.storage.get_warehouse_sub', return_value=root):
                DailyTask.record_progress(task)
            self.assertEqual([call.args[0] for call in task._open_record_page.call_args_list], list(RECORDING_PAGES))
            self.assertEqual(task.log_warning.call_count, len(RECORDING_PAGES))

    def test_run_records_are_observations_not_completion_and_keep_account_binding(self):
        from src.evidence.service import EvidenceService, begin_daily_run, finish_daily_run
        with tempfile.TemporaryDirectory() as root:
            repo = EvidenceRepository(root)
            service = EvidenceService(repo)
            task = SimpleNamespace(executor=SimpleNamespace(completion_evidence_service=service),
                                   _verified_profile_id=ACCOUNT)
            task._completion_run_record = begin_daily_run(task)
            finish_daily_run(task, 'returned')
            service.close()
            record = repo.latest_run(ACCOUNT)
            self.assertEqual(record['result'], 'returned')
            self.assertIsNotNone(record['finished_at'])
            self.assertEqual(repo.list_records(ACCOUNT), [])
            self.assertIn(ACCOUNT, repo.profiles())
            record['profile_id'] = '00000000-0000-4000-8000-000000000002'
            with self.assertRaises(ValueError):
                repo.save_run(record)
            with patch.object(service, 'submit', side_effect=OSError('disk full')):
                self.assertIsNone(begin_daily_run(task))
                finish_daily_run(task, 'failed')

    def test_capture_expiration_switch_and_missing_window_are_rejected(self):
        from src.evidence.service import request_capture, process_capture
        from unittest.mock import Mock
        for failure in ('expired', 'switch', 'window'):
            executor = SimpleNamespace(paused=True, current_task=SimpleNamespace(_verified_profile_id=ACCOUNT),
                method=SimpleNamespace(get_frame=Mock()),
                device_manager=SimpleNamespace(hwnd_window=SimpleNamespace(exists=True, hwnd=1)))
            with patch('src.evidence.service.time.monotonic', return_value=10):
                future = request_capture(executor)
            if failure == 'switch':
                executor.current_task._active_account_switch_capture = object()
            elif failure == 'window':
                executor.device_manager.hwnd_window.exists = False
            with patch('src.evidence.service.time.monotonic', return_value=19 if failure == 'expired' else 11):
                process_capture(executor)
            with self.assertRaises((RuntimeError, TimeoutError)):
                future.result()
            executor.method.get_frame.assert_not_called()

    def test_daily_adapter_retains_the_frame_that_proved_the_highest_points(self):
        from src.task.DailyTask import DailyTask
        from src.evidence.service import EvidenceService
        from unittest.mock import Mock
        import cv2
        with tempfile.TemporaryDirectory() as root:
            service = EvidenceService(EvidenceRepository(root))
            task = SimpleNamespace(_verified_profile_id=ACCOUNT, start_time=1,
                ocr=Mock(side_effect=[[SimpleNamespace(name='100')], [], [SimpleNamespace(name='70')]]),
                next_frame=Mock(), log_info=Mock(), info_set=Mock())
            task.executor = SimpleNamespace(current_task=task, completion_evidence_service=service,
                nullable_frame=Mock(return_value=np.full((5, 5, 3), 100, np.uint8)))
            try:
                self.assertEqual(DailyTask.get_total_daily_points(task), 100)
            finally:
                service.close()
            record = service.repository.list_records(ACCOUNT)[0]
            self.assertEqual(record['progress']['points'], 100)
            task.executor.nullable_frame.assert_called_once()
            decoded = cv2.imdecode(np.frombuffer(service.repository.asset_path(record['image_path']).read_bytes(), np.uint8), 1)
            self.assertTrue(np.all(decoded == 100))

    def test_weekly_and_garden_adapters_observe_without_changing_results(self):
        from src.task.WeeklyBossTask import WeeklyBossTask
        from src.task.GardenTask import GardenTask
        from unittest.mock import Mock
        for remaining in (0, 2):
            task = SimpleNamespace(_stage=Mock(), _open_weekly_book=Mock(),
                _read_remaining=Mock(return_value=remaining), info_set=Mock(), ensure_main=Mock())
            with patch('src.evidence.service.record_task_evidence') as observe:
                if remaining:
                    with self.assertRaises(RuntimeError):
                        WeeklyBossTask._recheck(task, 3, 1)
                else:
                    self.assertTrue(WeeklyBossTask._recheck(task, 3, 3).complete)
                self.assertEqual(observe.call_args.args[2], 'partial' if remaining else 'completed')
        for matched in ([], [SimpleNamespace(name='10000')]):
            task = SimpleNamespace(ocr=Mock(return_value=matched), GARDEN_TARGET_POINTS='target', log_info=Mock())
            with patch('src.evidence.service.record_task_evidence') as observe:
                self.assertEqual(GardenTask.is_weekly_garden_completed(task), bool(matched))
                self.assertEqual(observe.call_count, int(bool(matched)))

    def test_backup_keeps_original_and_recycle_state(self):
        with tempfile.TemporaryDirectory() as root:
            repo = EvidenceRepository(root)
            record = repo.save(dict(profile_id=ACCOUNT, project_id='daily_activity'), np.zeros((5, 5, 3), np.uint8))
            repo.trash(record['evidence_id'])
            backup = EvidenceRepository(repo.backup())
            self.assertEqual(len(backup.list_records(ACCOUNT, trashed=True)), 1)
            self.assertEqual(repo.asset_path(record['image_path']).read_bytes(),
                             backup.asset_path(record['image_path']).read_bytes())

    def test_queue_full_and_missing_frame_do_not_change_production(self):
        from src.evidence.service import EvidenceService, record_task_evidence
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as root:
            service = EvidenceService(EvidenceRepository(root))
            executor = SimpleNamespace(completion_evidence_service=service, nullable_frame=Mock(return_value=None))
            task = SimpleNamespace(executor=executor, _verified_profile_id=ACCOUNT, start_time=1,
                                   record_last_completed=Mock())
            executor.current_task = task
            try:
                saved = record_task_evidence(task, 'daily_activity', 'completed', 'test').result(timeout=5)
                service._pool.submit(lambda: None).result(timeout=5)
                self.assertEqual(saved['asset_status'], 'capture_failed')
                self.assertEqual(saved['completion_status'], 'completed')
                for _ in range(4):
                    self.assertTrue(service._slots.acquire(blocking=False))
                self.assertIsNone(record_task_evidence(task, 'daily_activity', 'completed', 'test'))
                self.assertIn('队列已满', service.last_error)
                task.record_last_completed.assert_not_called()
                for _ in range(4):
                    service._slots.release()
            finally:
                service.close()

    def test_current_summary_is_not_truncated_by_other_projects_or_unknowns(self):
        with tempfile.TemporaryDirectory() as root:
            repo = EvidenceRepository(root)
            repo.save(dict(profile_id=ACCOUNT, project_id='daily_activity', source='automatic',
                           completion_status='completed'), None)
            for _ in range(65):
                repo.save(dict(profile_id=ACCOUNT, project_id='daily_activity'), None)
            self.assertEqual(summarize(repo.read_current(ACCOUNT))[0]['completion_status'], 'completed')

    def test_duplicate_event_does_not_duplicate_original(self):
        with tempfile.TemporaryDirectory() as root:
            repo = EvidenceRepository(root)
            metadata = dict(profile_id=ACCOUNT, project_id='weekly_boss', source='automatic', event_id='run-event')
            first = repo.save(metadata, np.zeros((5, 5, 3), np.uint8))
            second = repo.save(metadata, np.ones((5, 5, 3), np.uint8))
            self.assertEqual(first['evidence_id'], second['evidence_id'])
            self.assertEqual(len(repo.list_records(ACCOUNT)), 1)

    def test_index_failure_preserves_original_and_reports_orphan(self):
        with tempfile.TemporaryDirectory() as root:
            repo = EvidenceRepository(root)
            with patch.object(repo, '_connect', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    repo.save(dict(profile_id=ACCOUNT, project_id='daily_activity'), np.zeros((5, 5, 3), np.uint8))
            report = repo.inspect_storage()
            self.assertEqual(len(report['orphans']), 2)
            self.assertGreater(report['bytes'], 0)
            self.assertTrue(all(repo.asset_path(p).exists() for p in report['orphans']))

    def test_manual_status_requires_explicit_confirmation_source(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                EvidenceRepository(root).save(dict(profile_id=ACCOUNT, project_id='weekly_boss',
                                                   completion_status='completed'), None)

    def test_async_save_freezes_account_and_frame(self):
        from src.evidence.service import EvidenceService
        with tempfile.TemporaryDirectory() as root:
            service = EvidenceService(EvidenceRepository(root))
            metadata = dict(profile_id=ACCOUNT, project_id='daily_activity')
            frame = np.zeros((5, 5, 3), np.uint8)
            try:
                future = service.submit(metadata, frame)
                metadata['profile_id'] = 'changed'
                frame[:] = 255
                self.assertEqual(future.result(timeout=5)['profile_id'], ACCOUNT)
            finally:
                service.close()

    def test_executor_capture_binding_cancel_and_no_input(self):
        from src.evidence.service import request_capture, process_capture
        from unittest.mock import Mock
        executor = SimpleNamespace(current_task=SimpleNamespace(_verified_profile_id=ACCOUNT),
            method=SimpleNamespace(get_frame=Mock(return_value=np.zeros((5, 5, 3), np.uint8))),
            device_manager=SimpleNamespace(hwnd_window=SimpleNamespace(exists=True, hwnd=1)))
        future = request_capture(executor)
        process_capture(executor)
        self.assertEqual(future.result()['profile_id'], ACCOUNT)
        future = request_capture(executor)
        executor.current_task._verified_profile_id = None
        process_capture(executor)
        with self.assertRaises(RuntimeError):
            future.result()
        future = request_capture(executor)
        future.cancel()
        process_capture(executor)
        executor.method.get_frame.assert_called_once()

    def test_periods_use_game_reset_not_sunday_check_slot(self):
        before = datetime.fromisoformat('2026-09-14T03:59:00+08:00')
        after = datetime.fromisoformat('2026-09-14T04:00:00+08:00')
        self.assertEqual(period_for('daily_activity', before), 'day:2026-09-13')
        self.assertEqual(period_for('weekly_boss', before), 'week:2026-09-07')
        self.assertEqual(period_for('weekly_boss', after), 'week:2026-09-14')
        self.assertIsNone(period_for('piano_activity', after))

    def test_roundtrip_retention_and_explicit_recycle(self):
        with tempfile.TemporaryDirectory() as root:
            repo = EvidenceRepository(root)
            record = repo.save(dict(profile_id=ACCOUNT, project_id='daily_activity'),
                               np.zeros((100, 200, 3), dtype=np.uint8))
            image = repo.asset_path(record['image_path'])
            self.assertTrue(image.exists())
            self.assertEqual(record['source'], 'manual_capture')
            self.assertEqual(record['completion_status'], 'unknown')
            repo.trash(record['evidence_id'])
            self.assertEqual(repo.list_records(ACCOUNT), [])
            self.assertTrue(image.exists())
            self.assertEqual(len(repo.list_records(ACCOUNT, trashed=True)), 1)
            repo.restore(record['evidence_id'])
            self.assertEqual(len(repo.list_records(ACCOUNT)), 1)
            with self.assertRaises(ValueError):
                repo.permanently_delete(record['evidence_id'], confirmed=True)
            repo.trash(record['evidence_id'])
            with self.assertRaises(ValueError):
                repo.permanently_delete(record['evidence_id'])
            repo.permanently_delete(record['evidence_id'], confirmed=True)
            self.assertFalse(image.exists())

    def test_invalid_account_or_path_cannot_escape_repository(self):
        with tempfile.TemporaryDirectory() as root:
            repo = EvidenceRepository(root)
            with self.assertRaises(ValueError):
                repo.save(dict(profile_id='../outside', project_id='daily_activity'), None)
            with self.assertRaises(ValueError):
                repo.asset_path('../outside.png')

    def test_old_evidence_and_missing_files_remain_in_history(self):
        with tempfile.TemporaryDirectory() as root:
            repo = EvidenceRepository(root)
            record = repo.save(dict(profile_id=ACCOUNT, project_id='weekly_boss',
                                   captured_at='2000-01-01T12:00:00+08:00'),
                               np.zeros((10, 10, 3), dtype=np.uint8))
            self.assertEqual(len(repo.list_records(ACCOUNT)), 1)
            repo.asset_path(record['image_path']).unlink()  # Simulate external disk damage.
            loaded = repo.list_records(ACCOUNT)[0]
            self.assertEqual(loaded['asset_status'], 'missing')
            self.assertEqual(loaded['evidence_id'], record['evidence_id'])

    def test_unknown_screenshot_does_not_hide_completed_record(self):
        rows = [dict(completion_status='unknown', source='manual_capture'),
                dict(completion_status='completed', source='automatic')]
        chosen, conflict = summarize(rows)
        self.assertEqual(chosen['completion_status'], 'completed')
        self.assertFalse(conflict)
        rows.insert(0, dict(completion_status='incomplete', source='manual_confirmation'))
        self.assertTrue(summarize(rows)[1])


if __name__ == '__main__':
    unittest.main()
