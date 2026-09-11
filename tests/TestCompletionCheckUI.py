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
                from src.evidence.model import PROJECTS
                self.assertEqual(len(page._cards), len(PROJECTS))
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


if __name__ == '__main__':
    unittest.main()
