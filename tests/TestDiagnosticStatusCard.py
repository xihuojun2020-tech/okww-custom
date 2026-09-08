import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from src.gui.DiagnosticStatusCard import DiagnosticStatusCard, diagnostic_error_message, diagnostic_status_text


class TestDiagnosticStatusCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait(self, widget):
        deadline = time.monotonic() + 5
        while widget.operation.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertFalse(widget.operation.busy)

    def test_settings_and_retry_only_touch_local_state(self):
        with tempfile.TemporaryDirectory() as temp, patch('src.gui.DiagnosticStatusCard.default_root', return_value=Path(temp)), patch('src.gui.DiagnosticStatusCard.wake_uploader') as wake:
            card = DiagnosticStatusCard()
            try:
                card.timer.stop()
                self.wait(card)
                self.assertFalse(hasattr(card, 'enabled'))
                card.target.setText(str(Path(temp) / 'remote'))
                card.save()
                self.wait(card)
                self.assertTrue(json.loads((Path(temp) / 'settings.json').read_text())['enabled'])
                states = Path(temp) / 'states'
                states.mkdir()
                for state in ('blocked', 'retrying'):
                    (states / (state + '.json')).write_text(json.dumps({'status': state, 'next_retry': 123}))
                card.retry()
                self.wait(card)
                self.assertEqual(json.loads((states / 'blocked.json').read_text())['next_retry'], 123)
                self.assertEqual(json.loads((states / 'retrying.json').read_text())['next_retry'], 0)
                self.assertTrue(wake.called)
                (states / 'retrying.json').write_text(json.dumps({'status': 'retrying', 'next_retry': 123}))
                card.password.setText('not-a-real-password')
                with patch('src.gui.DiagnosticStatusCard.save_credentials') as save_credentials:
                    card.save()
                    self.wait(card)
                self.assertTrue(save_credentials.called)
                self.assertEqual(json.loads((states / 'retrying.json').read_text())['next_retry'], 0)
            finally:
                card.deleteLater()
                self.app.processEvents()

    def test_upload_errors_have_actionable_messages(self):
        self.assertIn('重启程序', diagnostic_error_message("No module named 'win32timezone'"))
        self.assertIn('重新填写密码', diagnostic_error_message('NAS authentication failed, Windows code 86'))

    def test_collection_warning_does_not_replace_upload_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            batch = root / 'run' / 'batches' / 'batch'
            batch.mkdir(parents=True)
            (batch / '_READY').touch()
            states = root / 'states'
            states.mkdir()
            (states / 'run--batch.json').write_text(json.dumps({
                'status': 'retrying', 'last_error': 'SMB worker timed out'}), encoding='utf-8')
            (root / 'collector-error.json').write_text(json.dumps({
                'error': 'image file is truncated'}), encoding='utf-8')
            status = diagnostic_status_text(root)
            self.assertIn('最近上传错误：SMB worker timed out', status)
            self.assertIn('最近采集警告：image file is truncated', status)


if __name__ == '__main__':
    unittest.main()
