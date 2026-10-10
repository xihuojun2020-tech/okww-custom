"""Offscreen overview selects identities and keeps account actions read-only."""

import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QSignalSpy, QTest

from src.account_task_state import AccountTaskCard
from src.game_period import beijing_now
from src.gui.DailyTimingDialog import DailyTimingDialog, history_rows
from src.gui.NativeExecutionOverviewDialog import NativeExecutionOverviewDialog
from src.runtime.native_live_status import NativeLiveReader
from tests import TestNativeLiveStatus as live_fixtures
from tests.fixture_support import make_account_environment, synthetic_identity


class TestNativeExecutionOverview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.fixture = live_fixtures.TestNativeLiveStatus()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.environment = make_account_environment(self.fixture.root, names=('A1', 'A3'))

    def test_multiple_workers_require_selection_and_overview_cannot_write(self):
        identity = synthetic_identity('A1')['profile_id']
        first, one = self.fixture.start(identity)
        second, two = self.fixture.start(synthetic_identity('A3')['profile_id'])
        self.fixture.command(first, 'stage')
        self.fixture.command(second, 'stage')
        reader = NativeLiveReader(self.fixture.root)
        dialog = NativeExecutionOverviewDialog(self.environment.repository, reader, profile_id=identity)
        self.addCleanup(dialog.close)
        self.assertIsNone(dialog.workers.currentData())
        self.assertEqual(dialog.live(), {})
        self.assertEqual(dialog.accounts.currentData(), identity)
        dialog.workers.setCurrentIndex(dialog.workers.findData(one))
        self.assertEqual(dialog.live()['profile_id'], identity)
        self.assertEqual(dialog.live()['run_id'], 'business-run')
        with patch.object(dialog.overview.marking, 'start') as start:
            dialog.overview._mark('manual:test', True)
            dialog.overview._reset_abyss()
            start.assert_not_called()
        dialog.workers.setCurrentIndex(dialog.workers.findData(two))
        self.assertNotEqual(dialog.live()['profile_id'], identity)
        dialog.set_profile(synthetic_identity('A3')['profile_id'])
        self.assertEqual(dialog.overview.profile_id, synthetic_identity('A3')['profile_id'])
        # A later running-card refresh must not expose its normally writable actions.
        while dialog.overview.loading.busy:
            QTest.qWait(10)
        cards = [AccountTaskCard('adversity_tower', '深塔', 'running', manual=True)]
        dialog.overview._cards = cards
        dialog.overview._render(cards, beijing_now(), dialog.live())
        dialog.overview.refresh(force=True)
        row = dialog.overview._rows['adversity_tower']
        self.assertTrue(row.primary.isHidden())
        self.assertTrue(row.settings.isHidden())
        self.assertTrue(row.launch.isHidden())
        self.assertTrue(row.retry.isHidden())

    def test_directory_watch_reloads_stage_without_schema_polling(self):
        child, session = self.fixture.start(synthetic_identity('A1')['profile_id'])
        reader = NativeLiveReader(self.fixture.root)
        dialog = NativeExecutionOverviewDialog(self.environment.repository, reader)
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.workers.currentData(), session)
        spy = QSignalSpy(dialog.changed)
        self.fixture.command(child, 'stage')
        self.assertTrue(spy.wait(3000))
        self.assertEqual(dialog.live()['task_id'], 'forgery')

    def test_foreign_process_timing_requires_session_batch_and_attempt_match(self):
        batch = {'batch_id': 'batch', 'session': 'worker-session', 'game_day': '2026-10-11',
                 'finished_at': None, 'elapsed_seconds': 0, 'attempts': [{
                     'profile_id': 'profile', 'attempt_number': 1, 'phase': '首次',
                     'started_at': '2026-10-11T09:00:00+08:00', 'finished_at': None,
                     'elapsed_seconds': 0, 'result': 'running', 'reason': ''}]}
        key = ('worker-session', 'batch', 'profile', 1)
        row = history_rows([batch], 'profile', live_timings={key: 12})['2026-10-11']['rows'][0]
        self.assertEqual((row[3], row[4]), ('00:00:12', '运行中'))
        for changed in (('other', 'batch', 'profile', 1), ('worker-session', 'old', 'profile', 1),
                        ('worker-session', 'batch', 'profile', 2)):
            row = history_rows([batch], 'profile', live_timings={changed: 12})['2026-10-11']['rows'][0]
            self.assertEqual((row[3], row[4]), ('未知', '中断（结束时间未知）'))

    def test_readonly_timing_queries_once_then_elapsed_uses_memory(self):
        repository = Mock()
        repository.daily_timings.return_value = []
        dialog = DailyTimingDialog(repository, 'profile', readonly=True, live_provider=lambda: {})
        self.addCleanup(dialog.close)
        repository.daily_timings.assert_called_once_with('profile', readonly=True)
        dialog._render()
        repository.daily_timings.assert_called_once_with('profile', readonly=True)


if __name__ == '__main__':
    unittest.main()
