import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from custom_ok.ok.gui.MainWindow import MainWindow


class TestLanUpdateUI(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
