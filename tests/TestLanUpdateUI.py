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
        self.assertIn("self.preferences, self.lan_update_card", source)
        self.assertIn('版本与更新', GeneralSettingsTab.section_titles)

    @patch("custom_ok.ok.gui.MainWindow.subprocess.Popen")
    def test_schedule_starts_helper_before_quitting(self, popen):
        popen.return_value.poll.return_value = None
        window = SimpleNamespace(app=Mock(), executor=Mock())
        with tempfile.TemporaryDirectory() as temp:
            request = Path(temp) / "apply-request.json"
            request.write_text("{}", encoding="utf-8")
            popen.side_effect = lambda *args, **kwargs: (request.with_suffix('.ready.json').write_text('{}'), popen.return_value)[1]
            with patch('custom_ok.ok.gui.MainWindow.__file__', str(Path(temp) / '.venv/Lib/site-packages/ok/gui/MainWindow.py')):
                MainWindow.schedule_lan_update(window, request)
        command = popen.call_args.args[0]
        self.assertEqual('src.update.lan_apply', command[-2])
        self.assertTrue(os.path.isabs(command[-1]))
        from src.update import lan_service
        self.assertEqual(str(Path(lan_service.__file__).resolve().parents[2]), popen.call_args.kwargs['cwd'])
        window.app.quit.assert_called_once_with()
        window.executor.pause.assert_called_once_with()

    @patch('custom_ok.ok.gui.MainWindow.InfoBar.error')
    @patch('custom_ok.ok.gui.MainWindow.subprocess.Popen')
    def test_helper_import_failure_keeps_app_running(self, popen, info):
        popen.return_value.poll.return_value = 1
        window = SimpleNamespace(app=Mock(), tr=lambda text: text)
        with tempfile.TemporaryDirectory() as temp:
            request = Path(temp) / 'apply-request.json'
            request.write_text('{}')
            MainWindow.schedule_lan_update(window, request)
        window.app.quit.assert_not_called()
        info.assert_called_once()

    def test_card_shows_previous_installation_result(self):
        import json
        from src.gui.LanUpdateCard import LanUpdateCard
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'update-result.json').write_text(json.dumps(dict(from_version='1.92.01', to_version='1.92.02', message='校验失败')))
            card = LanUpdateCard(root / 'lan_update.json', '1.92.01', SimpleNamespace(current_task=None))
            self.assertIn('校验失败', card.status.text())
            card.deleteLater()

    def test_running_trigger_does_not_block_requested_install(self):
        from src.gui.LanUpdateCard import LanUpdateCard
        with tempfile.TemporaryDirectory() as temp:
            card = LanUpdateCard(Path(temp) / 'lan_update.json', '1.96.00',
                                 SimpleNamespace(current_task=object()))
            card.release = SimpleNamespace(version='1.97.00')
            card.service = Mock()
            card.service.create_apply_request.return_value = Path(temp) / 'apply-request.json'
            requested = []
            card.apply_requested.connect(requested.append)
            def finish(work, complete, *_args, **_kwargs):
                complete(work())
            card.operation.start = Mock(side_effect=finish)
            card._download()
            self.assertEqual(requested, [Path(temp) / 'apply-request.json'])
            card.deleteLater()

    @patch("custom_ok.ok.gui.MainWindow.subprocess.Popen", side_effect=OSError("blocked"))
    @patch("custom_ok.ok.gui.MainWindow.InfoBar.error")
    def test_failed_helper_launch_does_not_quit(self, info, popen):
        window = SimpleNamespace(app=Mock(), tr=lambda text: text)
        with tempfile.TemporaryDirectory() as temp:
            MainWindow.schedule_lan_update(window, Path(temp) / "request.json")
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
