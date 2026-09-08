import os
import inspect
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QPushButton, QWidget
from custom_ok.ok.gui.MainWindow import MainWindow
from src.gui.GeneralSettingsTab import GeneralSettingsTab
from src.gui.BackgroundOperation import BackgroundOperation


class TestLanUpdateUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_general_settings_mounts_lan_update_card(self):
        source = inspect.getsource(GeneralSettingsTab.__init__)
        self.assertIn("self.lan_update_card = LanUpdateCard", source)
        self.assertIn("behavior_layout.addWidget(self.lan_update_card)", source)

    @patch("custom_ok.ok.gui.MainWindow.subprocess.Popen")
    def test_schedule_starts_helper_before_quitting(self, popen):
        window = SimpleNamespace(app=Mock())
        with tempfile.TemporaryDirectory() as temp:
            request = Path(temp) / "apply-request.json"
            request.write_text("{}", encoding="utf-8")
            MainWindow.schedule_lan_update(window, request)
        command = popen.call_args.args[0]
        self.assertEqual(["-m", "src.update.lan_apply"], command[1:3])
        self.assertTrue(os.path.isabs(command[3]))
        window.app.quit.assert_called_once_with()

    @patch("custom_ok.ok.gui.MainWindow.subprocess.Popen", side_effect=OSError("blocked"))
    @patch("custom_ok.ok.gui.MainWindow.InfoBar.error")
    def test_failed_helper_launch_does_not_quit(self, info, popen):
        window = SimpleNamespace(app=Mock(), tr=lambda text: text)
        MainWindow.schedule_lan_update(window, Path("request.json"))
        window.app.quit.assert_not_called()
        info.assert_called_once()

    def test_timed_out_background_operation_restores_button(self):
        owner, button = QWidget(), QPushButton('check')
        operation = BackgroundOperation(owner, (button,))
        release, failures = threading.Event(), []
        request_id = operation.start(lambda: release.wait(1), self.fail, failures.append)
        operation._timeout(request_id)
        self.assertFalse(operation.busy)
        self.assertTrue(button.isEnabled())
        self.assertIsInstance(failures[0], TimeoutError)
        release.set()
        owner.deleteLater()


if __name__ == "__main__":
    unittest.main()
