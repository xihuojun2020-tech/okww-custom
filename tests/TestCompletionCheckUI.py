import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox, QDialog, QLabel
from PySide6.QtCore import QThreadPool
from src.evidence.repository import EvidenceRepository
from src.evidence.model import now_iso
from src.gui.CompletionCheckTab import CompletionCheckTab, EvidenceCaptureDialog

ACCOUNT = '00000000-0000-4000-8000-000000000001'


class TestCompletionCheckUI(unittest.TestCase):
    def test_manual_account_mismatch_requires_confirmation(self):
        other = '00000000-0000-4000-8000-000000000002'
        capture = dict(frame=np.zeros((50, 80, 3), np.uint8), profile_id=ACCOUNT, captured_at=now_iso())
        dialog = EvidenceCaptureDialog(capture, {ACCOUNT: 'A1', other: 'A2'}, ACCOUNT)
        dialog.account.setCurrentIndex(dialog.account.findData(other))
        dialog.confirm.setChecked(True)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.No):
            dialog.confirm_accept()
            self.assertNotEqual(dialog.result(), QDialog.Accepted)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            dialog.confirm_accept()
            self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(dialog.metadata()['profile_id'], other)
        self.assertEqual(dialog.metadata()['runtime_profile_id'], ACCOUNT)
        dialog.close()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_manual_confirmation_defaults_unknown_and_freezes_binding(self):
        capture = dict(frame=np.zeros((50, 80, 3), np.uint8), profile_id=ACCOUNT,
                       captured_at=now_iso(), identity_source='runtime_bound')
        dialog = EvidenceCaptureDialog(capture, {ACCOUNT: 'A1-测试-19910000001'}, ACCOUNT)
        self.assertTrue(dialog.account.isEnabled())
        self.assertIsNone(dialog.account.currentData())
        self.assertFalse(dialog.buttons.button(QDialogButtonBox.Save).isEnabled())
        dialog.confirm.setChecked(True)
        self.assertFalse(dialog.buttons.button(QDialogButtonBox.Save).isEnabled())
        dialog.account.setCurrentIndex(dialog.account.findData(ACCOUNT))
        self.assertEqual(dialog.metadata()['identity_source'], 'user_confirmed')
        self.assertEqual(dialog.metadata()['source'], 'manual_capture')
        self.assertEqual(dialog.metadata()['completion_status'], 'unknown')
        dialog.status.setCurrentIndex(dialog.status.findData('completed'))
        self.assertEqual(dialog.metadata()['source'], 'manual_confirmation')
        dialog.close()

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
                page._reminders[ACCOUNT] = ['weekly_boss']
                page.reminders_only.setChecked(True)
                self.assertEqual(len(page._cards), 1)
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

    def test_reminder_legacy_preservation_and_compact_header_scope(self):
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
        self.assertEqual(set(panel.apply_account(account)['extensions']['completion_reminders']),
                         set(account['extensions']['completion_reminders']))
        self.assertFalse(panel.choices['activity_1'].isHidden())
        self.assertTrue(panel.choices['activity_2'].isHidden())
        panel.load_account({})
        self.assertTrue(panel.choices['activity_1'].isHidden())
        compact_settings(root, account=True)
        self.assertEqual(panel.header.minimumHeight(), 40)
        other = SectionPanel('other', collapsible=True)
        self.assertEqual(other.header.minimumHeight(), 56)
        root.close()
        other.close()


if __name__ == '__main__':
    unittest.main()
