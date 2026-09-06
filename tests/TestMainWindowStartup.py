import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from custom_ok.ok.gui.MainWindow import MainWindow


class TestMainWindowStartup(unittest.TestCase):
    """Regression tests for the post-show integrity gate."""

    def test_launcher_cleanup_preserves_other_same_named_installation(self):
        compiler = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        if not compiler.is_file():
            self.skipTest('controlled Windows launcher probe requires the .NET Framework C# compiler')
        with tempfile.TemporaryDirectory(prefix='okww-owned-launcher-') as temp:
            root = Path(temp)
            source = root / 'Launcher.cs'
            source.write_text('''using System.Diagnostics; using System.Threading;
class Launcher { static void Main(string[] args) {
  if (args.Length == 0) { Thread.Sleep(30000); return; }
  var info = new ProcessStartInfo(args[0], args[1]);
  info.UseShellExecute = false; info.CreateNoWindow = true;
  Process.Start(info).WaitForExit();
} }''', encoding='utf-8')
            a, b = root / 'a' / 'fake-launcher.exe', root / 'b' / 'fake-launcher.exe'
            a.parent.mkdir(); b.parent.mkdir()
            subprocess.run([str(compiler), '/nologo', '/target:exe', '/out:' + str(a), str(source)],
                           check=True, capture_output=True, timeout=30)
            shutil.copy2(a, b)
            marker = root / 'cleaned.txt'
            probe = root / 'probe.py'
            probe.write_text(
                'import sys\nfrom pathlib import Path\n'
                f'sys.path.insert(0, {str(Path.cwd())!r})\n'
                'from main import _find_owned_launcher, _exit_cleanup\n'
                'owned = _find_owned_launcher()\nassert owned is not None\n'
                '_exit_cleanup(owned)\n'
                f'Path({str(marker)!r}).write_text("done")\n', encoding='utf-8')
            other = subprocess.Popen([str(b)], creationflags=0x08000000)
            owned = None
            try:
                owned = subprocess.Popen(
                    [str(a), sys.executable, subprocess.list2cmdline([str(probe)])],
                    env=dict(os.environ, PYAPPIFY_EXECUTABLE=str(a)), creationflags=0x08000000)
                deadline = time.monotonic() + 10
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue(marker.is_file(), 'owned child did not complete cleanup')
                owned.wait(timeout=5)
                self.assertIsNone(other.poll(), 'the other installation must remain running')
            finally:
                for process in (owned, other):
                    if process is not None and process.poll() is None:
                        import psutil
                        for child in psutil.Process(process.pid).children(recursive=True):
                            try:
                                child.terminate()
                            except psutil.Error:
                                pass
                        process.terminate()
                        process.wait(timeout=5)

    def test_cleanup_without_verified_ownership_does_nothing(self):
        from main import _exit_cleanup, _find_owned_launcher
        with patch.dict(os.environ, {'PYAPPIFY_EXECUTABLE': 'relative.exe'}), patch('psutil.Process') as process:
            self.assertIsNone(_find_owned_launcher())
            _exit_cleanup()
            process.assert_not_called()

    def _window(self, **attrs):
        window = MainWindow.__new__(MainWindow)
        window._startup_post_show_scheduled = False
        window._startup_post_show_complete = False
        window._startup_args = {}
        window._integrity_review_blocked = False
        window.bring_to_front = Mock()
        window._review_account_integrity_before_start = Mock(return_value=True)
        window._check_okscript_args = Mock()
        window.main_window_config = {"last_version": "1.08.00"}
        window.version = "1.08.00"
        window.config = {}
        window.basic_global_config = {}
        window.app = Mock()
        window.app.start_controller.start = Mock()
        window.app.start = Mock()
        window.handler = Mock()
        window.show_startup_version_change_notice = Mock()
        window.__dict__.update(attrs)
        return window

    @patch("custom_ok.ok.gui.MainWindow.QTimer.singleShot")
    def test_post_show_review_is_scheduled_once(self, single_shot):
        window = self._window()

        self.assertTrue(window._schedule_post_show_startup())
        self.assertFalse(window._schedule_post_show_startup())

        single_shot.assert_called_once_with(150, window._run_post_show_startup)

    def test_failed_review_blocks_all_automatic_start_actions(self):
        window = self._window(
            _startup_args={"task": 3, "exit": True},
            _review_account_integrity_before_start=Mock(return_value=False),
        )

        window._run_post_show_startup()

        self.assertTrue(window._integrity_review_blocked)
        window.app.start_controller.start.assert_not_called()
        window._check_okscript_args.assert_not_called()
        window.bring_to_front.assert_called_once_with()

    @patch("custom_ok.ok.gui.MainWindow.QTimer.singleShot")
    def test_first_show_completes_readiness_before_deferring_review(self, single_shot):
        events = []
        window = self._window()
        window._complete_window_readiness = Mock(side_effect=lambda: events.append("ready"))
        window.bring_to_front = Mock(side_effect=lambda: events.append("front"))
        window._schedule_post_show_startup = Mock(side_effect=lambda: events.append("deferred"))

        window._handle_first_show()

        self.assertEqual(["ready", "deferred"], events)
        single_shot.assert_called_once_with(0, window.bring_to_front)

    def test_duplicate_post_show_callback_cannot_start_twice(self):
        window = self._window(_startup_args={"task": 0, "exit": False})

        window._run_post_show_startup()
        window._run_post_show_startup()

        self.assertTrue(window._startup_post_show_complete)
        window._review_account_integrity_before_start.assert_called_once_with()
        window._check_okscript_args.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
