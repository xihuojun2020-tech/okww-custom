import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from src.gui.DiagnosticStatusCard import DiagnosticStatusCard


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
                card.enabled.setChecked(True)
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
            finally:
                card.deleteLater()
                self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
