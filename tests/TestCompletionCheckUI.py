import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton
from PySide6.QtCore import QThreadPool
from src.evidence.repository import EvidenceRepository
from src.evidence.model import now_iso
from src.gui.CompletionCheckTab import CompletionCheckTab

ACCOUNT = '00000000-0000-4000-8000-000000000001'


class TestCompletionCheckUI(unittest.TestCase):
    def test_task_card_evidence_button_is_accessible_and_uses_shared_capture(self):
        from custom_ok.ok.gui.tasks.TaskCard import TaskCard
        from tests.TestFlatUI import example_task
        from ok import og
        from unittest.mock import Mock
        task = type('AutoSeaRuinsTask', (), {})()
        task.__dict__.update(vars(example_task()))
        page = SimpleNamespace(capture_evidence=Mock())
        window = SimpleNamespace(completion_check_tab=page, switchTo=Mock())
        with patch.object(og, 'app', SimpleNamespace(tr=str)), \
             patch.object(og, 'executor', SimpleNamespace(waiting_for_task=lambda _: '')), \
             patch.object(og, 'main_window', window):
            card = TaskCard(task, True, fluent_sample=True)
            try:
                self.assertTrue(card._expand_enabled)
                card.setExpand(True)
                card.evidence_button.click()
                page.capture_evidence.assert_called_once_with('sea_ruins')
                window.switchTo.assert_called_once_with(page)
            finally:
                card.close()

    def test_one_click_capture_uses_selected_account_without_dialog_and_freezes_selection(self):
        from concurrent.futures import Future
        import time
        other = '00000000-0000-4000-8000-000000000002'
        with tempfile.TemporaryDirectory() as root:
            repo = EvidenceRepository(root)
            page = CompletionCheckTab(SimpleNamespace(), repository=repo, account_provider=lambda: None)
            page.timer.stop()
            page._profiles = {ACCOUNT: 'A1', other: 'A2'}
            page._selected = ACCOUNT
            page._display_records()
            future = Future()
            try:
                with patch('src.gui.CompletionCheckTab.request_capture', return_value=future) as capture, \
                     patch.object(page, 'reload_records'), patch.object(QDialog, 'exec', side_effect=AssertionError('unexpected confirmation')):
                    card = next(card for card in page._cards if card.property('project_id') == 'sea_ruins')
                    card.findChild(QPushButton, 'saveCurrentEvidence').click()
                    self.assertTrue(page.capture_operation.busy)
                    page._selected = other
                    future.set_result(dict(frame=np.ones((10, 12, 3), np.uint8), profile_id=other,
                                           captured_at='2026-10-08T20:27:00+08:00'))
                    deadline = time.monotonic() + 5
                    while page.capture_operation.busy and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(.005)
                    self.assertFalse(page.capture_operation.busy)
                    capture.assert_called_once_with(page.executor)
                row = repo.list_records(ACCOUNT)[0]
                self.assertEqual(row['project_id'], 'sea_ruins')
                self.assertEqual(row['completion_status'], 'completed')
                self.assertEqual(row['source'], 'manual_confirmation')
                self.assertEqual(row['runtime_profile_id'], other)
                self.assertEqual(repo.list_records(other), [])
                self.assertTrue(repo.asset_path(row['image_path']).exists())
            finally:
                page.service.close()
                page.close()

    def test_failed_capture_does_not_create_completed_record(self):
        from concurrent.futures import Future
        import time
        with tempfile.TemporaryDirectory() as root:
            repo = EvidenceRepository(root)
            page = CompletionCheckTab(SimpleNamespace(), repository=repo, account_provider=lambda: None)
            page.timer.stop()
            page._profiles = {ACCOUNT: 'A1'}
            page._selected = ACCOUNT
            future = Future()
            future.set_exception(RuntimeError('游戏窗口不可用'))
            try:
                with patch('src.gui.CompletionCheckTab.request_capture', return_value=future):
                    page.capture_evidence('matrix')
                    deadline = time.monotonic() + 5
                    while page.capture_operation.busy and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(.005)
                self.assertIn('游戏窗口不可用', page.notice.text())
                self.assertEqual(repo.list_records(ACCOUNT), [])
            finally:
                page.service.close()
                page.close()

    def test_accounts_follow_current_slots_in_all_and_filtered_views(self):
        from PySide6.QtCore import Qt
        from src.account_slots import SLOT_KEY
        def profile(identity, old_name, slot):
            return dict(profile_id=identity, display_name=old_name, nickname='测试',
                        extensions={SLOT_KEY: None if slot is None else
                                    {'sequence': '序列1' if slot[0] == 'A' else '序列2', 'slot': slot}})
        # Creation order and legacy names differ from current fixed positions.
        profiles = {'B18': profile('b1', 'B18', 'B1'),
                    'A10': profile('a10', 'A10', 'A10'),
                    'B10': profile('a2', 'B10', 'A2'),
                    'unused': profile('unused', 'A3', None),
                    'A1': profile('a1', 'A1', 'A1')}
        projection = {'profiles': profiles, 'sequences': {'序列1': ['A10', 'B10'], '序列2': ['B18']}}
        with tempfile.TemporaryDirectory() as root:
            page = CompletionCheckTab(SimpleNamespace(), repository=EvidenceRepository(root),
                                      account_provider=lambda: None)
            def identities():
                return [page.accounts.item(i).data(Qt.UserRole) for i in range(page.accounts.count())]
            try:
                page.timer.stop()
                with patch.object(page, 'reload_records'):
                    page._accounts_loaded((projection, ['retired'], 'a2'))
                    self.assertEqual(identities(), ['a1', 'a2', 'a10', 'b1', 'unused', 'retired'])
                    self.assertEqual(page._selected, 'a2')
                    self.assertTrue(page.accounts.item(1).text().startswith('A2-'))
                    page.sequence.setCurrentIndex(page.sequence.findData('序列1'))
                    self.assertEqual(identities(), ['a2', 'a10'])
                    self.assertEqual(page._selected, 'a2')
                    page.sequence.setCurrentIndex(0)
                    page.search.setText('A')
                    self.assertEqual(identities(), ['a1', 'a2', 'a10'])
                    page.search.clear()
                    page._accounts_loaded((projection, ['retired'], 'b1'))
                    self.assertEqual(identities(), ['a1', 'a2', 'a10', 'b1', 'unused', 'retired'])
                    self.assertEqual(page._selected, 'a2')
            finally:
                page.service.close()
                page.close()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_synthetic_dashboard_layout_and_selection_are_read_only(self):
        with tempfile.TemporaryDirectory() as root:
            repo = EvidenceRepository(root)
            executor = SimpleNamespace()
            page = CompletionCheckTab(executor, repository=repo, account_provider=lambda: None)
            try:
                page._profiles = {ACCOUNT: 'A1-测试-19910000001'}
                page._selected = ACCOUNT
                page._rows = []
                page.resize(800, 640)
                page._display_records()
                from src.evidence.model import CURRENT_PROJECTS
                self.assertEqual(len(page._cards), len(CURRENT_PROJECTS))
                self.assertEqual(set(page._group_headers), {'day', 'week', None})
                self.assertFalse(hasattr(executor, '_completion_capture_requests'))
                self.assertFalse(repo.database.exists())
                self.assertTrue(all(card.layout() is not None for card in page._cards))
                self.assertFalse(page._run_panel.toggle_button.isChecked())
                page._run_record = {'result': 'returned', 'video_paths': []}
                page._display_records()
                text = '\n'.join(label.text() for label in page._run_panel.findChildren(QLabel))
                self.assertIn('正常返回（不代表全部完成）', text)
                self.assertIn('最近开始时间：无记录', text)
                page._run_record['scope'] = 'world_boss_material'
                page._display_records()
                text = '\n'.join(label.text() for label in page._run_panel.findChildren(QLabel))
                self.assertIn('最近执行范围：首领材料单独执行', text)
                self.assertFalse(hasattr(page, 'reminders_only'))
                other = '00000000-0000-4000-8000-000000000002'
                page._profiles[other] = 'A2-测试-19910000002'
                page._rows = [{'profile_id': ACCOUNT}]
                with patch.object(page, 'reload_records'):
                    page._select_account(SimpleNamespace(data=lambda _: other))
                self.assertEqual(page._rows, [])
                self.assertIsNone(page._run_record)
            finally:
                QThreadPool.globalInstance().waitForDone(5000)
                page.timer.stop()
                page.service.close()
                page.close()

    def test_copy_original_pixels_and_failed_decode_preserves_clipboard(self):
        import cv2
        from src.gui.CompletionCheckTab import copy_image, EvidenceDetailDialog
        frame = np.zeros((720, 1280, 3), np.uint8)
        frame[:, :, 2] = 173
        data = cv2.imencode('.png', frame)[1].tobytes()
        copy_image(data)
        clipboard = QApplication.clipboard()
        self.assertEqual((clipboard.image().width(), clipboard.image().height()), (1280, 720))
        self.assertEqual(clipboard.image().pixelColor(600, 400).red(), 173)
        with self.assertRaises(ValueError):
            copy_image(b'invalid')
        self.assertEqual(clipboard.image().pixelColor(600, 400).red(), 173)
        with tempfile.TemporaryDirectory() as root:
            repo = EvidenceRepository(root)
            record = repo.save(dict(profile_id=ACCOUNT, project_id='sea_ruins'), frame)
            dialog = EvidenceDetailDialog(record, repo.asset_path(record['image_path']).read_bytes())
            dialog.fit()
            dialog.copy_original()
            self.assertEqual(clipboard.image().width(), 1280)
            self.assertIn('图片已复制', dialog.copy_notice.text())
            dialog.close()

    def test_card_copy_freezes_selected_record_and_missing_file_preserves_clipboard(self):
        import time
        with tempfile.TemporaryDirectory() as root:
            repo = EvidenceRepository(root)
            record = repo.save(dict(profile_id=ACCOUNT, project_id='sea_ruins'), np.full((48, 96, 3), 71, np.uint8))
            page = CompletionCheckTab(SimpleNamespace(), repository=repo, account_provider=lambda: None)
            try:
                def drain():
                    deadline = time.monotonic() + 5
                    while page.action_operation.busy and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(0.005)
                    self.assertFalse(page.action_operation.busy)
                page._selected = ACCOUNT
                page._rows = repo.read_current(ACCOUNT)
                page._display_records()
                from qfluentwidgets import PushButton
                button = next(button for button in page.findChildren(PushButton) if button.text() == '复制图片')
                button.click()
                page._selected = '00000000-0000-4000-8000-000000000002'
                drain()
                self.assertEqual(QApplication.clipboard().image().width(), 96)
                self.assertEqual(QApplication.clipboard().image().pixelColor(0, 0).red(), 71)
                repo.asset_path(record['image_path']).unlink()
                page.copy_record(record)
                drain()
                self.assertEqual(QApplication.clipboard().image().width(), 96)
                self.assertIn('证据操作失败', page.notice.text())
            finally:
                QThreadPool.globalInstance().waitForDone(5000)
                page.timer.stop()
                page.service.close()
                page.close()

    def test_snapshot_pending_filter_uses_latest_photo_status(self):
        with tempfile.TemporaryDirectory() as root:
            repo = EvidenceRepository(root)
            repo.save(dict(profile_id=ACCOUNT, project_id='sea_ruins', source='manual_confirmation',
                completion_status='completed'), np.zeros((5, 5, 3), np.uint8))
            page = CompletionCheckTab(SimpleNamespace(), repository=repo, account_provider=lambda: None)
            try:
                page._selected = ACCOUNT
                page._rows = repo.read_current(ACCOUNT)
                page.pending_only.setChecked(True)
                self.assertNotIn('sea_ruins', [c.property('project_id') for c in page._cards])
                repo.save(dict(profile_id=ACCOUNT, project_id='sea_ruins'), np.ones((5, 5, 3), np.uint8))
                page._rows = repo.read_current(ACCOUNT)
                page._display_records()
                self.assertIn('sea_ruins', [c.property('project_id') for c in page._cards])
            finally:
                page.timer.stop()
                page.service.close()
                page.close()

    def test_reminder_legacy_migration_note_and_compact_header_scope(self):
        from src.gui.AccountReminderPanel import AccountReminderPanel
        from src.gui.compact_settings import compact_settings
        from src.gui.SectionPanel import SectionPanel
        from PySide6.QtWidgets import QWidget, QVBoxLayout
        root = QWidget()
        layout = QVBoxLayout(root)
        panel = AccountReminderPanel(root)
        layout.addWidget(panel)
        account = {'extensions': {'completion_reminders': ['activity_1', 'piano_activity']}}
        panel.load_account(account)
        self.assertTrue(panel.choices['activities'].isChecked())
        panel.note.setPlainText('仅供人工查看')
        applied = panel.apply_account(account)
        self.assertEqual(applied['extensions']['completion_reminders'], ['activities'])
        self.assertEqual(applied['extensions']['account_reminder_note'], '仅供人工查看')
        panel.load_account({})
        self.assertFalse(any(control.isChecked() for control in panel.choices.values()))
        compact_settings(root, account=True)
        self.assertEqual(panel.header.minimumHeight(), 40)
        other = SectionPanel('other', collapsible=True)
        self.assertEqual(other.header.minimumHeight(), 40)
        root.close()
        other.close()

    def test_completion_check_has_no_reminder_filter_or_summary(self):
        with tempfile.TemporaryDirectory() as root:
            page = CompletionCheckTab(SimpleNamespace(), repository=EvidenceRepository(root),
                                      account_provider=lambda: None)
            try:
                self.assertFalse(hasattr(page, 'reminders_only'))
                self.assertFalse(hasattr(page, 'reminder_summary'))
            finally:
                page.timer.stop()
                page.service.close()
                page.close()


if __name__ == '__main__':
    unittest.main()
