import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import copy
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QMessageBox, QLabel
from src.gui.WorldBossMaterialPlanWidget import WorldBossMaterialPlanWidget
from src.gui.AccountConfigTab import AccountConfigTab, AccountTemplateDialog
from src.account_config_editor import AccountConfigEditor
from src.account_config_bundle import AccountConfigBundleService
from src.task.world_boss_material_plan import MATERIAL_TARGETS, material_plan
from src.task.world_boss_material_progress import WorldBossMaterialProgress
from src.task.world_boss_materials import WORLD_BOSS_TARGETS
from tests.fixture_support import make_account_environment

BOSSES = ['world_crownless', 'world_tempest', 'world_thundering']
ROWS = [{'boss': b, 'limit': n} for b, n in zip(BOSSES, (2, 3, 4))]


class TestWorldBossMaterialUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = make_account_environment(Path(self.temp.name))
        self.identity = self.env.repository.list_profiles()[0].profile_id
        self.progress = WorldBossMaterialProgress(self.env.integrity, self.identity)

    def dispose(self, widget):
        self.addCleanup(widget.deleteLater)
        return widget

    def test_screenshot_catalog_order_preserves_saved_targets_and_cumulative_progress(self):
        expected = ['天傀劫煞', '万囮牢·朽躯', '梦魔亚当·重锤', '无铭探索者', '海维夏',
                    '炉芯机骸', '海之女', '伪作的神王', '芬莱克', '荣耀狮像', '叹息古龙',
                    '罗蕾莱', '异构武装', '无归的谬误', '无冠者', '朔雷之鳞', '云闪之鳞',
                    '燎照之骑', '飞廉之猩', '哀声鸷', '无常凶鹭', '辉萤军势', '聚械机偶']
        self.progress.correct(BOSSES[0], 1)
        pending = self.progress.begin(BOSSES[1], 60, 'previous-version')
        widget = self.dispose(WorldBossMaterialPlanWidget({MATERIAL_TARGETS: ROWS}, self.env.integrity, self.identity))
        for row, (target, limit, _) in zip(ROWS, widget.rows):
            self.assertEqual(['无', *expected], [target.itemText(i) for i in range(target.count())])
            self.assertEqual(row['boss'], target.currentData())
        self.assertEqual(ROWS, widget.values())
        self.assertEqual({BOSSES[0]: 1}, self.progress.counts())
        self.assertIn(pending, self.progress.pending())
        self.assertEqual(expected, [target.name for target in WORLD_BOSS_TARGETS])

    def test_finite_values_invalid_duplicates_and_template_has_no_progress(self):
        widget = self.dispose(WorldBossMaterialPlanWidget({MATERIAL_TARGETS: ROWS}))
        self.assertEqual(ROWS, widget.values())
        self.assertIsNone(widget.progress)
        widget.rows[0][1].setText('不限')
        with self.assertRaises(ValueError):
            widget.values()
        widget.rows[0][1].setText('2')
        widget.rows[1][0].setCurrentIndex(widget.rows[1][0].findData(BOSSES[0]))
        with self.assertRaises(ValueError):
            widget.values()
        dialog = self.dispose(AccountTemplateDialog({MATERIAL_TARGETS: ROWS, 'Weekly Boss Target': '无'}))
        self.assertEqual(ROWS, dialog.tasks()[MATERIAL_TARGETS])
        self.assertEqual('无', dialog.tasks()['Weekly Boss Target'])
        self.assertIsNone(dialog._widgets[MATERIAL_TARGETS].progress)
        old = self.dispose(AccountTemplateDialog({}))
        self.assertEqual([], old.tasks()[MATERIAL_TARGETS])

    def test_progress_complete_fallback_and_pending_visible_when_plan_disabled(self):
        widget = self.dispose(WorldBossMaterialPlanWidget({MATERIAL_TARGETS: ROWS}, self.env.integrity, self.identity))
        for row in ROWS:
            self.progress.correct(row['boss'], row['limit'])
        widget.set_fallback('Forgery Challenge')
        self.assertIn('全部启用目标已达标', widget.summary.text())
        self.assertIn('凝素领域', widget.summary.text())
        self.assertIn('2/2', widget.rows[0][2].text())
        self.progress.begin(BOSSES[0], 60, 'test')
        for target, limit, _ in widget.rows:
            target.setCurrentIndex(0)
            limit.setText('0')
        widget.refresh()
        self.assertFalse(widget.resolve_button.isHidden())
        self.assertIn('待核验', widget.summary.text())
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes), \
                patch.object(widget, '_editable_progress', return_value=True):
            widget._resolve()
        self.assertEqual(3, self.progress.counts()[BOSSES[0]])
        self.assertTrue(widget.resolve_button.isHidden())
        self.assertEqual({}, WorldBossMaterialProgress(self.env.integrity, 'other-account').counts())

    def test_account_save_reload_preserves_weekly_and_links_stamina_choice(self):
        tab = self.dispose(AccountConfigTab(AccountConfigEditor(self.env.repository)))
        original_weekly = tab.draft.tasks['Weekly Boss Target']
        widget = tab.form_widgets[MATERIAL_TARGETS]
        for row, (target, limit, _) in zip(ROWS, widget.rows):
            target.setCurrentIndex(target.findData(row['boss']))
            limit.setText(str(row['limit']))
        self.assertTrue(tab.dirty)
        fallback = tab.form_widgets['Which to Farm']
        fallback.setCurrentIndex(fallback.findData('Forgery Challenge'))
        self.assertIn('凝素领域', widget.summary.text())
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            tab.save()
            deadline = time.monotonic() + 5
            while tab.operation.busy and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.005)
        self.assertFalse(tab.operation.busy)
        self.assertFalse(tab.dirty)
        saved = self.env.repository.load_profile(tab.selected_profile_id)
        self.assertEqual(ROWS, saved.tasks[MATERIAL_TARGETS])
        self.assertEqual(original_weekly, saved.tasks['Weekly Boss Target'])
        self.assertEqual('Forgery Challenge', saved.tasks['Which to Farm'])

    def test_production_bundle_restore_keeps_higher_count_and_pending(self):
        self.progress.correct(BOSSES[0], 2)
        bundle_service = AccountConfigBundleService(self.env.root, integrity_service=self.env.integrity)
        backup = bundle_service.export_bundle()
        self.assertEqual(2, backup['runtime_data']['progress'][self.progress.key]['counts'][BOSSES[0]])
        self.progress.correct(BOSSES[0], 5)
        event = self.progress.begin(BOSSES[1], 60, 'test')
        bundle_service.import_bundle(copy.deepcopy(backup), confirm=True)
        self.assertEqual(5, self.progress.counts()[BOSSES[0]])
        self.assertIn(event, self.progress.pending())

    def test_completion_panel_displays_cumulative_without_daily_completion(self):
        from types import SimpleNamespace
        from src.evidence.repository import EvidenceRepository
        from src.gui.CompletionCheckTab import CompletionCheckTab
        page = CompletionCheckTab(SimpleNamespace(), repository=EvidenceRepository(Path(self.temp.name) / 'evidence'),
                                  account_provider=lambda: self.env.repository)
        try:
            page._selected = self.identity
            page._profiles = {self.identity: 'A1'}
            page._material_summary = ['无冠者：已领 2/2 次 · 已达标', '有材料领奖待核验，请停止任务后到账号设置核对。']
            page._display_records()
            labels = '\n'.join(label.text() for label in page._run_panel.findChildren(QLabel))
            self.assertIn('首领材料累计目标（跨日跨周保留）', labels)
            self.assertIn('已领 2/2 次', labels)
            self.assertIn('待核验', labels)
            self.assertEqual({}, page._completions)
        finally:
            QThreadPool.globalInstance().waitForDone(5000)
            page.timer.stop()
            page.service.close()
            page.deleteLater()

    def test_completion_background_loader_reads_account_plan_and_same_ledger(self):
        from types import SimpleNamespace
        from src.evidence.repository import EvidenceRepository
        from src.gui.CompletionCheckTab import CompletionCheckTab
        editor = AccountConfigEditor(self.env.repository)
        draft = editor.load_draft(self.identity)
        draft.tasks[MATERIAL_TARGETS] = ROWS
        editor.save_draft(draft.scope, draft, confirmed_account_label=draft.account['display_name'])
        self.progress.correct(BOSSES[0], 2)
        self.progress.begin(BOSSES[1], 60, 'test')
        page = CompletionCheckTab(SimpleNamespace(), repository=EvidenceRepository(Path(self.temp.name) / 'evidence'),
                                  account_provider=lambda: self.env.repository)
        try:
            page._selected = self.identity
            page._profiles = {self.identity: 'A1'}
            page._load_records()
            deadline = time.monotonic() + 5
            while page.load_operation.busy and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.005)
            self.app.processEvents()
            self.assertFalse(page.load_operation.busy)
            self.assertIn('无冠者：已领 2/2 次 · 已达标', page._material_summary)
            self.assertTrue(any('待核验' in text for text in page._material_summary))
        finally:
            QThreadPool.globalInstance().waitForDone(5000)
            page.timer.stop()
            page.service.close()
            page.deleteLater()
