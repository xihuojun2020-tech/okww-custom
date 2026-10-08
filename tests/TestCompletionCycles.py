import json
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from src.activity_catalog import ACTIVITIES, LEGACY_ACTIVITIES
from src.evidence.cycles import ANCHOR, seed_cycles, cycle_for
from src.evidence.model import PROJECTS, current_projects, period_for, project_group
from src.evidence.repository import EvidenceRepository

ACCOUNT = '00000000-0000-4000-8000-000000000001'


class TestCompletionCycles(unittest.TestCase):
    def test_deadline_ocr_failure_keeps_captured_frame_and_reports_missing_deadline(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from src.evidence.service import request_capture, process_capture
        frame = np.ones((10, 12, 3), np.uint8)
        reader = SimpleNamespace(ocr=Mock(side_effect=RuntimeError('OCR unavailable')))
        executor = SimpleNamespace(current_task=None, method=SimpleNamespace(get_frame=lambda: frame),
            device_manager=SimpleNamespace(hwnd_window=SimpleNamespace(exists=True, hwnd=1)),
            get_task_by_class=lambda cls: reader)
        future = request_capture(executor, period_project='matrix')
        process_capture(executor)
        value = future.result()
        self.assertTrue(np.array_equal(value['frame'], frame))
        self.assertIn('OCR unavailable', value['period_error'])
        reader.ocr.assert_called_once()

    def test_user_deadlines_and_weekly_display_are_independent(self):
        cycles = seed_cycles()
        self.assertEqual(cycles['adversity_tower']['end_at'], '2026-10-12T03:22:11+08:00')
        self.assertEqual(cycles['sea_ruins']['end_at'], '2026-10-26T03:22:11+08:00')
        self.assertEqual(cycles['matrix']['end_at'], '2026-11-12T03:22:11+08:00')
        self.assertEqual(cycles['character_trial']['end_at'], '2026-10-22T09:22:11+08:00')
        for project in ('adversity_tower', 'sea_ruins', 'matrix'):
            self.assertEqual(project_group(project), 'week')
            self.assertEqual(period_for(project, ANCHOR), period_for(project, '2026-10-09T05:00:00+08:00'))
        self.assertIsNone(cycle_for('adversity_tower', cycles['adversity_tower']['end_at']))
        self.assertIsNotNone(cycle_for('sea_ruins', cycles['adversity_tower']['end_at']))

    def test_only_four_current_activities_and_old_titles_remain_readable(self):
        self.assertEqual(list(ACTIVITIES.values()), ['初露峥嵘', '天工寻物', '团团勇者大乱斗', '梦构匣中'])
        current = current_projects(ANCHOR)
        self.assertEqual(current.count('character_trial'), 1)
        self.assertTrue(all(key not in current and key in PROJECTS for key in LEGACY_ACTIVITIES))
        self.assertNotIn('character_trial', current_projects('2026-10-23T00:00:00+08:00'))
        self.assertIn('dream_box', current_projects('2026-10-23T00:00:00+08:00'))

    def test_unknown_old_screenshots_stay_in_history_without_rewriting_originals(self):
        with tempfile.TemporaryDirectory() as root:
            repo = EvidenceRepository(root)
            old = repo.save(dict(profile_id=ACCOUNT, project_id='sea_ruins',
                captured_at='2026-09-01T12:00:00+08:00'), np.zeros((5, 5, 3), np.uint8))
            original = repo.asset_path(old['image_path']).read_bytes()
            with patch('src.evidence.model.datetime') as dt:
                from datetime import datetime
                dt.now.return_value = datetime.fromisoformat(ANCHOR)
                self.assertEqual(repo.read_current(ACCOUNT, 'sea_ruins'), [])
            self.assertEqual(repo.list_records(ACCOUNT)[0]['evidence_id'], old['evidence_id'])
            self.assertEqual(repo.asset_path(old['image_path']).read_bytes(), original)

    def test_completed_image_expires_but_remains_in_history_and_reopen_keeps_deadline(self):
        with tempfile.TemporaryDirectory() as root:
            repo = EvidenceRepository(root)
            row = repo.save(dict(profile_id=ACCOUNT, project_id='adversity_tower', captured_at=ANCHOR,
                source='manual_confirmation', completion_status='completed'),
                np.ones((5, 5, 3), np.uint8))
            from datetime import datetime
            with patch('src.evidence.model.datetime') as dt:
                dt.now.return_value = datetime.fromisoformat('2026-10-10T03:00:00+08:00')
                self.assertEqual(repo.read_current(ACCOUNT)[0]['evidence_id'], row['evidence_id'])
                dt.now.return_value = datetime.fromisoformat('2026-10-12T03:22:11+08:00')
                self.assertEqual(repo.read_current(ACCOUNT), [])
            self.assertEqual(EvidenceRepository(root).cycles()['adversity_tower'], seed_cycles()['adversity_tower'])
            self.assertEqual(repo.list_records(ACCOUNT)[0]['completion_status'], 'completed')

    def test_screen_countdown_only_establishes_expired_project_with_matching_title(self):
        with tempfile.TemporaryDirectory() as root:
            repo = EvidenceRepository(root)
            self.assertFalse(repo.observe_cycle('matrix', '矩阵 剩余时间 40天7小时', ANCHOR))
            self.assertFalse(repo.observe_cycle('matrix', '海墟 剩余时间 40天7小时', '2026-11-13T12:00:00+08:00'))
            self.assertFalse(repo.observe_cycle('matrix', '矩阵 剩余时间 40天7小时 1天2小时', '2026-11-13T12:00:00+08:00'))
            self.assertTrue(repo.observe_cycle('matrix', '矩阵 剩余时间 40天7小时', '2026-11-13T12:00:00+08:00'))
            cycles = json.loads(repo.get_preference('project_cycles_v1'))
            self.assertEqual(cycles['matrix']['end_at'], '2026-12-23T19:00:00+08:00')
            self.assertEqual(EvidenceRepository(root).cycles(), cycles)


if __name__ == '__main__':
    unittest.main()
