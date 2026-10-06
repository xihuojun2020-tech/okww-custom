import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import copy
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.game_period import (GAME_ZONE, game_day_key, game_week_key, next_daily_reset,
                             next_weekly_reset, completed_in_period, nightmare_checkpoint)
from src.account_reminders import mark_manual_reminder, manual_reminder_done
from src.account_task_state import build_account_task_cards, record_task_event
from src.task.abyss_cycle_progress import AbyssCycleProgress, countdown_interval, abyss_overview, team_key
from tests.fixture_support import make_account_environment, synthetic_identity


class TestGamePeriod(unittest.TestCase):
    def test_midnight_does_not_reset_but_four_does(self):
        self.assertEqual(game_day_key('2026-10-06T03:59:59+08:00'), '2026-10-05')
        self.assertEqual(game_day_key('2026-10-06T04:00:00+08:00'), '2026-10-06')
        self.assertEqual(game_day_key('2026-10-05T20:00:00Z'), '2026-10-06')
        self.assertTrue(completed_in_period('2026-10-05 23:30:00', now='2026-10-06T03:59:00+08:00'))
        self.assertFalse(completed_in_period('2026-10-05 23:30:00', now='2026-10-06T04:00:00+08:00'))

    def test_monday_week_boundary_and_future_stamp(self):
        self.assertEqual(game_week_key('2026-10-05T03:59:59+08:00'), '2026-09-28')
        self.assertEqual(game_week_key('2026-10-05T04:00:00+08:00'), '2026-10-05')
        self.assertEqual(next_weekly_reset('2026-10-05T03:59:59+08:00').isoformat(), '2026-10-05T04:00:00+08:00')
        self.assertFalse(completed_in_period('2026-10-05T05:00:00+08:00', now='2026-10-05T04:00:00+08:00'))
        self.assertEqual(next_daily_reset('2026-10-05T04:00:00+08:00').day, 6)


class TestAccountTaskState(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = make_account_environment(self.temp.name)
        self.identity = synthetic_identity('A1')['profile_id']
        self.profile = self.env.repository.load_profile(self.identity)
        self.now = datetime(2026, 10, 5, 21, 0, tzinfo=GAME_ZONE)

    def cards(self, **kwargs):
        return {c.task_id: c for c in build_account_task_cards(self.profile, self.env.integrity, now=self.now, **kwargs)}

    def test_supplemental_state_reader_failure_does_not_hide_task_result(self):
        task = SimpleNamespace(integrity_service=self.env.integrity,
                               _verified_profile_id=self.identity,
                               _readonly_profile_config=Mock(side_effect=RuntimeError('read failed')),
                               log_warning=Mock())
        record_task_event(task, 'daily_run', 'failed', reason='original task failure')
        task.log_warning.assert_called_once()
        self.assertEqual(self.env.integrity.get_progress('task_state_v1:' + self.identity, {}), {})

    def test_nest_scope_changes_and_activity_is_actual_observation(self):
        self.profile.tasks.update({'Tacet Discord Nests to Farm': ['test-location'], 'Which to Farm': '无', 'Weekly Boss Target': '无'})
        stamp = self.now.isoformat()
        self.env.integrity.record_completion(self.identity, nightmare_checkpoint(self.profile.tasks), stamp)
        self.assertEqual(self.cards()['nightmare_nest'].state, 'completed')
        self.profile.tasks['Tacet Discord Nests to Farm'] = ['other-location']
        self.assertEqual(self.cards()['nightmare_nest'].state, 'pending')
        self.profile.tasks['Tacet Discord Nests to Farm'] = []
        self.env.integrity.set_progress('task_state_v1:' + self.identity, {'daily_activity': {
            'result': 'completed', 'period_id': game_day_key(self.now), 'actual_points': 100,
            'rewards_claimed': True, 'finished_at': stamp}})
        self.assertNotIn('nightmare_nest', self.cards())
        self.assertEqual(self.cards()['daily_activity'].state, 'completed')

    def test_all_manual_cycles_and_account_isolation(self):
        for rule in ('none', 'day', 'week', 'custom'):
            row = {'enabled': True, 'rule': rule}
            if rule == 'custom':
                row['reset_at'] = (self.now + timedelta(hours=2)).isoformat()
            mark_manual_reminder(self.env.integrity, self.identity, 'sea_ruins', row, now=self.now)
            record = self.env.integrity.get_progress('manual_task_marks:' + self.identity)['sea_ruins']
            self.assertTrue(manual_reminder_done(row, record, self.now))
            future = self.now + timedelta(days=8)
            self.assertEqual(manual_reminder_done(row, record, future), rule == 'none')
            self.assertEqual(self.env.integrity.get_profile_completions(self.identity), {})
            self.assertEqual(self.env.integrity.get_progress('manual_task_marks:' + synthetic_identity('A3')['profile_id'], {}), {})
            mark_manual_reminder(self.env.integrity, self.identity, 'sea_ruins', row, done=False, now=self.now)
            record = self.env.integrity.get_progress('manual_task_marks:' + self.identity)['sea_ruins']
            self.assertFalse(manual_reminder_done(row, record, self.now))
            self.assertEqual(record['completed_at'], self.now.isoformat())

    def test_pending_forgery_blocks_completion_and_other_account_live_does_not_leak(self):
        from src.task.forgery_quota_plan import FORGERY_GOALS
        from src.task.forgery_quota_progress import ForgeryQuotaProgress
        from uuid import uuid4
        goal = {'goal_id': str(uuid4()), 'domain': 1, 'need': {'gold': 1, 'purple': 0, 'blue': 0, 'green': 0}}
        self.profile.tasks.update({FORGERY_GOALS: [goal], 'Which to Farm': 'Forgery Challenge'})
        progress = ForgeryQuotaProgress(self.env.integrity, self.identity)
        event = progress.begin(goal['goal_id'], 1, 80, 'r1')
        self.assertEqual(self.cards()['forgery'].state, 'attention')
        progress.resolve(event, 80)
        self.assertEqual(self.cards()['forgery'].state, 'completed')
        self.assertIn('tacet', self.cards())
        live = {'profile_id': synthetic_identity('A3')['profile_id'], 'task_id': 'daily_activity'}
        self.assertNotEqual(self.cards(live=live)['daily_activity'].state, 'running')

    def test_weekly_monday_success_requires_sunday_recheck(self):
        from src.task.weekly_boss import WEEKLY_MONDAY
        self.env.integrity.record_completion(self.identity, WEEKLY_MONDAY, self.now.isoformat())
        self.assertEqual(self.cards()['weekly_boss'].state, 'completed')
        self.now += timedelta(days=6)
        self.assertEqual(self.cards()['weekly_boss'].state, 'pending')

    def test_abyss_failed_team_and_new_cycle_are_isolated(self):
        journal = AbyssCycleProgress(self.env.integrity, self.identity)
        self.assertIsNone(countdown_interval('奖励 6 天 11 小时', self.now))
        self.assertTrue(journal.observe_cycle('剩余 6天11小时', self.now))
        cycle = journal.cycle_id
        plan = SimpleNamespace(members=('a', 'b', 'c'))
        journal.write_floor('残响之塔', 3, 'failed', plan=plan)
        journal.write_floor('回音之塔', 0, 'completed')
        journal.verify_run(True)
        restarted = AbyssCycleProgress(self.env.integrity, self.identity)
        restarted.observe_cycle('剩余 6天10小时', self.now + timedelta(hours=1))
        self.assertEqual(restarted.cycle_id, cycle)
        self.assertIn(team_key(plan), restarted.failed_teams('残响之塔', 3))
        restarted.write_floor('残响之塔', 3, 'blocked', reason='候选队伍均失败')
        restarted.verify_run(True)
        self.assertEqual(abyss_overview(self.env.integrity, self.identity, self.now)[0], 'attention')
        other = AbyssCycleProgress(self.env.integrity, synthetic_identity('A3')['profile_id'])
        other.observe_cycle('剩余 6天11小时', self.now)
        self.assertFalse(other.failed_teams('残响之塔', 3))
        restarted.observe_cycle('剩余 20天11小时', self.now + timedelta(days=7))
        self.assertNotEqual(restarted.cycle_id, cycle)
        self.assertFalse(restarted.failed_teams('残响之塔', 3))

    def test_unverified_failure_not_inherited_on_rescan(self):
        first = AbyssCycleProgress(self.env.integrity, self.identity)
        first.observe_cycle('剩余 6天11小时', self.now)
        first.write_floor('残响之塔', 3, 'failed', plan=SimpleNamespace(members=('a', 'b', 'c')))
        second = AbyssCycleProgress(self.env.integrity, self.identity)
        second.observe_cycle('剩余 6天11小时', self.now)
        second.write_floor('残响之塔', 3, 'available')
        self.assertFalse(second.failed_teams('残响之塔', 3))

    def test_failed_left_four_changes_team_then_continues_right(self):
        from src.task.AutoAbyssTask import AutoAbyssTask, COMPLETED, AVAILABLE, TOWER_NAMES, AbyssTeamUnavailable
        for exhaust in (False, True):
            journal = AbyssCycleProgress(self.env.integrity, self.identity)
            journal.observe_cycle('剩余 20天11小时' if exhaust else '剩余 6天11小时', self.now)
            task = AutoAbyssTask.__new__(AutoAbyssTask)
            task.config = {'Tower Priority': '两侧塔优先'}
            task._abyss_journal = journal
            task._set_status = lambda *_: None
            task._enter_and_scan_characters = lambda *_: []
            task._return_from_team_to_towers = lambda: None
            task._planned_team_energy = lambda *_: 10
            first, second = SimpleNamespace(members=('a', 'b', 'c')), SimpleNamespace(members=('d', 'e', 'f'))
            def plan(*_, **__):
                tower, index, _, _ = task._allocation_context
                if tower == '残响之塔' and journal.failed_teams(tower, index):
                    if exhaust:
                        task._abyss_candidate_pool = {(tower, index): set()}
                        raise AbyssTeamUnavailable('所有符合条件的队伍都已失败')
                    return second
                return first
            task._plan_and_form_team = plan
            fights = []
            def fight(tower, index, _):
                fights.append((tower, index, task._current_abyss_plan.members))
                return ('失败', 0) if tower == '残响之塔' and task._current_abyss_plan == first else ('完成', 1)
            task._fight_selected_tower = fight
            scans = {TOWER_NAMES[0]: (COMPLETED, COMPLETED, COMPLETED, AVAILABLE),
                     TOWER_NAMES[1]: (COMPLETED,), TOWER_NAMES[2]: (AVAILABLE,)}
            task._run_towers(scans)
            self.assertEqual(fights[-1][0], '回音之塔')
            left = [r for r in fights if r[0] == '残响之塔']
            self.assertEqual(len(left), 1 if exhaust else 2)
            if exhaust:
                self.assertEqual(journal.floor('残响之塔', 3)['status'], 'blocked')
            else:
                self.assertNotEqual(left[0][2], left[1][2])

    def test_re_evaluation_preserves_clears_and_failure_history(self):
        from src.task.abyss_cycle_progress import reset_abyss_failures
        journal = AbyssCycleProgress(self.env.integrity, self.identity)
        journal.observe_cycle('剩余 6天11小时', self.now)
        journal.write_floor('残响之塔', 3, 'failed', plan=SimpleNamespace(members=('a', 'b', 'c')))
        journal.write_floor('回音之塔', 0, 'completed')
        journal.verify_run(True)
        reset_abyss_failures(self.env.integrity, self.identity)
        self.assertFalse(journal.failed_teams('残响之塔', 3))
        self.assertTrue(journal.floor('残响之塔', 3)['failure_history'])
        self.assertEqual(journal.floor('回音之塔', 0)['status'], 'completed')

    def test_failed_tail_does_not_erase_activity_success(self):
        self.env.integrity.set_progress('task_state_v1:' + self.identity, {
            'daily_activity': {'period_id': game_day_key(self.now), 'result': 'completed',
                               'actual_points': 100, 'rewards_claimed': True},
            'daily_run': {'period_id': game_day_key(self.now), 'result': 'failed', 'reason': '战令收尾失败'}})
        cards = self.cards()
        self.assertEqual(cards['daily_activity'].state, 'completed')
        self.assertEqual(cards['daily_run'].state, 'attention')

    def test_failed_attempt_time_is_not_reported_as_completion(self):
        previous = (self.now - timedelta(days=1)).isoformat()
        attempt = self.now.isoformat()
        self.env.integrity.record_completion(self.identity, 'Daily Task', previous)
        self.env.integrity.set_progress('task_state_v1:' + self.identity, {'daily_activity': {
            'period_id': game_day_key(self.now), 'result': 'failed', 'actual_points': 80,
            'rewards_claimed': False, 'finished_at': attempt}})
        card = self.cards()['daily_activity']
        self.assertEqual(card.state, 'attention')
        self.assertEqual(card.completed_at, previous)
        self.assertEqual(card.last_attempt_at, attempt)


class TestAccountNavigationUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFontDatabase
        cls.app = QApplication.instance() or QApplication([])
        font = Path('C:/Windows/Fonts/msyh.ttc')
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))

    def test_real_account_hub_does_not_squeeze_overview_with_sequence_panel(self):
        from PySide6.QtCore import QThreadPool
        from src.gui.AccountConfigTab import AccountConfigTab
        from src.gui.AccountSettingsTab import AccountSettingsTab
        from src.gui.SequenceManagementTab import SequenceManagementTab
        from src.account_config_editor import AccountConfigEditor
        from src.sequence_repository import SequenceRepository
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            with patch('src.gui.AccountSettingsTab.AccountConfigTab',
                       side_effect=lambda: AccountConfigTab(AccountConfigEditor(env.repository))), \
                 patch('src.gui.AccountSettingsTab.SequenceManagementTab',
                       side_effect=lambda *args, **kwargs: SequenceManagementTab(SequenceRepository(env.repository), **kwargs)):
                page = AccountSettingsTab()
            page.resize(1150, 800)
            page.show()
            self.app.processEvents()
            self.assertGreater(page.account_tab.overview.height(), 500)
            self.assertFalse(page.account_tab._sequence_panel.isVisible())
            page.account_tab._select_route('sequences')
            self.app.processEvents()
            self.assertTrue(page.account_tab._sequence_panel.isVisible())
            self.assertFalse(page.account_tab.overview.isVisible())
            page.account_tab._select_route('overview')
            self.app.processEvents()
            self.assertGreater(page.account_tab.overview.height(), 500)
            page.close()
            page.account_tab.overview.timer.stop()
            QThreadPool.globalInstance().waitForDone(3000)
            page.deleteLater()
            self.app.processEvents()

    def test_routes_preserve_draft_and_refresh_does_not_rebuild_form(self):
        from PySide6.QtCore import QThreadPool
        from src.gui.AccountConfigTab import AccountConfigTab
        from src.account_config_editor import AccountConfigEditor
        from src.gui.CodexTheme import apply_codex_light_theme
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            apply_codex_light_theme(self.app)
            page = AccountConfigTab(AccountConfigEditor(env.repository))
            page.resize(1150, 800)
            page.show()
            for _ in range(20):
                self.app.processEvents()
                if not page.overview.loading.busy:
                    break
                time.sleep(.02)
            widget = page.form_widgets['Which to Farm']
            original = widget.currentData()
            page._select_route('tacet')
            self.assertEqual(page.content_stack.currentWidget(), page.settings_scroll)
            widget.setCurrentIndex((widget.currentIndex() + 1) % widget.count())
            edited = widget.currentData()
            self.assertNotEqual(edited, original)
            page._select_route('weekly')
            page._select_route('tacet')
            self.assertIs(page.form_widgets['Which to Farm'], widget)
            self.assertEqual(widget.currentData(), edited)
            self.assertTrue(page.dirty)
            page._select_route('overview')
            page.overview.refresh(force=True)
            for _ in range(60):
                self.app.processEvents()
                if not page.overview.loading.busy:
                    break
                time.sleep(.02)
            self.assertTrue(page.overview._cards, page.overview.notice.text())
            self.assertFalse(page.overview.notice.text())
            self.assertIs(page.form_widgets['Which to Farm'], widget)
            self.assertEqual(widget.currentData(), edited)
            self.assertEqual(env.repository.load_profile(page.selected_profile_id).tasks['Which to Farm'], original)
            Path('test_out').mkdir(exist_ok=True)
            page.grab().save('test_out/account-overview-1.97.12.png')
            page.close()
            page.overview.timer.stop()
            QThreadPool.globalInstance().waitForDone(3000)
            page.deleteLater()
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
