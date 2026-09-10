import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np
from PySide6.QtWidgets import QApplication, QDialogButtonBox
from PySide6.QtCore import QThreadPool
from src.evidence.repository import EvidenceRepository
from src.evidence.model import now_iso
from src.gui.CompletionCheckTab import CompletionCheckTab, EvidenceCaptureDialog

ACCOUNT = '00000000-0000-4000-8000-000000000001'


class TestCompletionCheckUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_manual_confirmation_defaults_unknown_and_freezes_binding(self):
        capture = dict(frame=np.zeros((50, 80, 3), np.uint8), profile_id=ACCOUNT,
                       captured_at=now_iso(), identity_source='runtime_bound')
        dialog = EvidenceCaptureDialog(capture, {ACCOUNT: 'A1-测试-19910000001'}, ACCOUNT)
        self.assertFalse(dialog.account.isEnabled())
        self.assertFalse(dialog.buttons.button(QDialogButtonBox.Save).isEnabled())
        dialog.confirm.setChecked(True)
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
                self.assertEqual(len(page._cards), 10)
                self.assertFalse(hasattr(executor, '_completion_capture_requests'))
                self.assertFalse(repo.database.exists())
                self.assertTrue(all(card.layout() is not None for card in page._cards))
            finally:
                QThreadPool.globalInstance().waitForDone(5000)
                page.timer.stop()
                page.service.close()
                page.close()


if __name__ == '__main__':
    unittest.main()
