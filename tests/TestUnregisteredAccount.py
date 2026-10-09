import tempfile
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.config_integrity import ConfigIntegrityBlocked
from src.task.account_feature_verification import begin_task_run, current_feature_run, IDENTITY_REQUIRED
from src.task.MultiAccountDailyTask import CURRENT_ACCOUNT, UNREGISTERED_ACCOUNT
from src.task.tiangong_treasure import Progress
from src.task.world_boss_material_progress import SessionMaterialProgress
from src.task.world_boss_materials import WORLD_BOSS_TARGETS
from src.evidence.service import bound_profile, record_task_evidence


class TestUnregisteredAccount(unittest.TestCase):
    def test_account_panel_shows_mode_and_retains_it_across_sequence_change(self):
        from PySide6.QtWidgets import QApplication
        from ok import og
        from src.gui.ChoiceControls import QtComboBox
        from src.gui.TaskHubTab import TaskHubTab
        from src.task.MultiAccountDailyTask import CURRENT_SEQUENCE
        app = QApplication.instance() or QApplication([])
        owner = SimpleNamespace(enabled=False, config={CURRENT_SEQUENCE: 'S1', CURRENT_ACCOUNT: UNREGISTERED_ACCOUNT})
        owner.get_sequence_names = lambda: ['S1', 'S2']
        owner.get_current_sequence = lambda: owner.config[CURRENT_SEQUENCE]
        owner.get_sequence_accounts = lambda sequence=None: ['A1'] if (sequence or owner.get_current_sequence()) == 'S1' else ['B2']
        hub = SimpleNamespace(_account_owner=lambda: owner, account_panel=Mock(),
                              sequence_combo=QtComboBox(), account_combo=QtComboBox())
        hub.refresh_account_choices = lambda: TaskHubTab.refresh_account_choices(hub)
        with patch.object(og, 'executor', SimpleNamespace(onetime_tasks=[owner], _account_feature_run=None)), \
                patch('src.account_repository.get_default_repository', return_value=None):
            hub.refresh_account_choices()
            self.assertEqual(hub.account_combo.currentData(), UNREGISTERED_ACCOUNT)
            TaskHubTab._select_sequence(hub, 1)
            self.assertEqual(owner.config[CURRENT_SEQUENCE], 'S2')
            self.assertEqual(hub.account_combo.currentData(), UNREGISTERED_ACCOUNT)
            self.assertEqual([hub.account_combo.itemData(i) for i in range(hub.account_combo.count())],
                             ['', UNREGISTERED_ACCOUNT, 'B2'])
        hub.sequence_combo.deleteLater()
        hub.account_combo.deleteLater()
        app.processEvents()

    def task(self, name):
        owner = SimpleNamespace(config={CURRENT_ACCOUNT: UNREGISTERED_ACCOUNT})
        daily = SimpleNamespace(clear_profile_binding=Mock())
        task = type(name, (SimpleNamespace,), {})(info_set=Mock(), _verified_profile_id='stale')
        task.executor = SimpleNamespace(current_task=task, _account_feature_run=object(),
                                        _daily_reserve_policy=object())
        def get(cls):
            return owner if cls.__name__ == 'MultiAccountDailyTask' else daily
        task.get_task_by_class = get
        return task, daily

    def test_five_required_tasks_block_before_any_input_or_bypass(self):
        for name in IDENTITY_REQUIRED:
            task, _ = self.task(name)
            with patch('src.gui.navigation_sections.classify_task', return_value='tasks'), \
                    patch('src.task.WWOneTimeTask.WWOneTimeTask.run') as prepare, \
                    patch('src.task.account_feature_verification.begin_account_visit') as verify:
                with self.assertRaisesRegex(ConfigIntegrityBlocked, '必须验证身份'):
                    begin_task_run(task)
            prepare.assert_not_called()
            verify.assert_not_called()
            self.assertIsNone(task.executor._unregistered_task)

    def test_optional_task_skips_ocr_clears_old_binding_and_never_writes_evidence(self):
        task, daily = self.task('TiangongTreasureTask')
        with patch('src.gui.navigation_sections.classify_task', return_value='tasks'), \
                patch('src.task.WWOneTimeTask.WWOneTimeTask.run'), \
                patch('src.task.account_feature_verification.begin_account_visit') as verify:
            begin_task_run(task)
            self.assertIsNone(current_feature_run(task))
        verify.assert_not_called()
        daily.clear_profile_binding.assert_called_once()
        self.assertIsNone(task._verified_profile_id)
        self.assertIsNone(task.executor._daily_reserve_policy)
        self.assertIsNone(bound_profile(task.executor))
        child = SimpleNamespace(executor=task.executor, _verified_profile_id='stale-child')
        self.assertIsNone(record_task_evidence(child, 'weekly_boss', 'completed', 'test'))

    def test_anonymous_flag_cannot_leak_into_next_task(self):
        task, _ = self.task('WeeklyBossTask')
        task.executor._unregistered_task = task
        other = SimpleNamespace(executor=task.executor)
        task.executor.current_task = other
        from src.task.account_feature_verification import unregistered_run
        self.assertFalse(unregistered_run(other))

    def test_anonymous_stage_progress_is_only_in_memory(self):
        with tempfile.TemporaryDirectory() as root:
            progress = Progress(None, 'period', root)
            progress.update(0, dict(score=90000, status='completed'))
            self.assertEqual(progress.stages['1']['score'], 90000)
            self.assertEqual(list(Path(root).iterdir()), [])
            self.assertEqual(Progress(None, 'period', root).stages, {})

    def test_session_material_counter_reuses_confirmed_claims_and_does_not_cross_runs(self):
        boss = WORLD_BOSS_TARGETS[0].key
        progress = SessionMaterialProgress()
        for _ in range(2):
            event = progress.begin(boss, 60, 'plan')
            self.assertEqual(len(progress.pending()), 1)
            progress.resolve(event, True)
            progress.resolve(event, True)
        self.assertEqual(progress.counts(), {boss: 2})
        self.assertEqual(SessionMaterialProgress().counts(), {})

    def test_weekly_entry_uses_explicit_target_without_daily_profile(self):
        from src.task.WeeklyBossTask import WeeklyBossTask
        from src.task.weekly_boss import WEEKLY_BOSSES
        task = object.__new__(WeeklyBossTask)
        task.config = {'目标周本': WEEKLY_BOSSES[0].name}
        task.run_for_target = Mock()
        task.get_task_by_class = Mock()
        with patch('src.task.account_feature_verification.unregistered_run', return_value=True):
            task.run()
        task.run_for_target.assert_called_once_with(WEEKLY_BOSSES[0].key)
        task.get_task_by_class.assert_not_called()

    def test_material_entry_passes_session_counter_and_selected_claims_without_daily(self):
        from src.task.WorldBossMaterialTask import WorldBossMaterialTask
        task = object.__new__(WorldBossMaterialTask)
        target = WORLD_BOSS_TARGETS[0]
        task.config = {'首领关卡': target.name, '领取次数': 2}
        task.reset_to_false = Mock()
        task.run_for_profile = Mock()
        task.get_task_by_class = Mock()
        executor = SimpleNamespace(check_enabled=Mock())
        with patch.object(WorldBossMaterialTask, 'executor', new=property(lambda _: executor)), \
                patch('src.task.account_feature_verification.unregistered_run', return_value=True):
            task.run()
        args, kwargs = task.run_for_profile.call_args
        self.assertIsNone(args[0])
        self.assertEqual(kwargs['request'], (target.key, 2))
        self.assertIsInstance(kwargs['progress'], SessionMaterialProgress)
        task.get_task_by_class.assert_not_called()
