"""Offscreen launcher checks; worker fixture only, no game or device."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gameframe.gui import GameFrameWindow


class FixtureController:
    def __init__(self):
        self.process = None
        self.starts = []
        self.closed = False
        self.controls = []

    def start(self, manifest, task_id, *, data_dir, config=None, device=None, session=False):
        self.starts.append((manifest.id, task_id, config, device))
        code = ("import sys; print('fixture ready', flush=True); "
                "line=sys.stdin.readline(); "
                "print('fixture stopped', flush=True) if line.strip() == 'stop' else None")
        self.process = subprocess.Popen([sys.executable, "-u", "-c", code],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True)
        return self.process

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.stdin.write("stop\n")
            self.process.stdin.flush()
            self.process.wait(timeout=3)

    def close(self):
        self.closed = True
        self.stop()
        if self.process is not None:
            self.process.stdin.close()
            self.process.stdout.close()

    def pause(self):
        self.controls.append('pause')

    def resume(self):
        self.controls.append('resume')

    def request_task(self, task_id, config):
        self.controls.append(('run-task', task_id, config))

    def set_service(self, task_id, enabled, config=None):
        self.controls.append(('set-service', task_id, enabled, config))


class TestGameFrameLauncher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for folder, mode in (("native", "native"), ("legacy", "legacy-application")):
            package = root / folder
            package.mkdir()
            (package / "entry.py").write_text("raise RuntimeError('game code imported by launcher')\n",
                                               encoding="utf-8")
            (package / "manifest.json").write_text(json.dumps({
                "api_version": 1, "id": folder, "title": folder, "version": "1.00.00",
                "entrypoint": "entry.py:Package", "license": "test", "platforms": ["windows"],
                "execution": mode, "tasks": [{"id": "task", "title": "Fixture task", "kind": "one-shot",
                                               "default_config": {"threshold": 0.5},
                                               "required_capabilities": ["frames"]}],
            }), encoding="utf-8")
        self.controller = FixtureController()
        self.window = GameFrameWindow(root, root / "data", controller=self.controller)
        self.addCleanup(self._close_window)

    def _until(self, predicate, seconds=3):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            self.window._drain_events()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("Launcher fixture timed out")

    def _close_window(self):
        if not self.window._cleanup_done:
            self.window.close()
            self._until(lambda: self.window._cleanup_done)

    def test_manifest_selection_stays_metadata_only_and_legacy_fields_do_not_apply(self):
        self.assertEqual(self.window.package_select.count(), 2)
        self.assertIn("Compatibility", self.window.mode_label.text())
        self.assertFalse(self.window.config_edit.isEnabled())
        self.assertFalse(self.window.device_edit.isEnabled())
        self.window.start_selected()
        self._until(lambda: self.window.process is not None)
        self.assertFalse(self.window.install_button.isEnabled())
        self.assertEqual(self.controller.starts[0], ("legacy", "task", None, None))
        self.window.stop_selected()
        self._until(lambda: self.window.process is None)
        self.assertTrue(self.window.install_button.isEnabled())

    def test_native_json_and_output_are_handled_without_blocking_ui(self):
        self.window.package_select.setCurrentIndex(1)
        self.assertIn("Native", self.window.mode_label.text())
        self.assertEqual(json.loads(self.window.config_edit.toPlainText()), {"threshold": 0.5})
        self.window.device_edit.setPlainText('{"type":"replay","frames":[]}')
        self.window.start_selected()
        self._until(lambda: self.window.process is not None)
        self.assertEqual(self.controller.starts[0],
                         ("native", "task", {"threshold": 0.5}, {"type": "replay", "frames": []}))
        self._until(lambda: "fixture ready" in self.window.output.toPlainText())
        self.window.stop_selected()
        self._until(lambda: self.window.process is None)
        self.assertIn("fixture stopped", self.window.output.toPlainText())
        self.assertIn("code 0", self.window.status_label.text())

    def test_pause_button_changes_only_after_worker_confirmation(self):
        self.window.package_select.setCurrentIndex(1)
        self.window.start_selected()
        self._until(lambda: self.window.process is not None)
        self.window.pause_button.click()
        self.assertEqual(self.controller.controls, ['pause'])
        self.assertFalse(self.window.pause_button.isEnabled())
        self.assertEqual(self.window.status_label.text(), 'Pause requested')
        self.window._events.put(('line', '{"event":"task-paused","paused":true}'))
        self.window._drain_events()
        self.assertEqual(self.window.pause_button.text(), 'Resume')
        self.assertTrue(self.window.pause_button.isEnabled())
        self.window.pause_button.click()
        self.assertEqual(self.controller.controls, ['pause', 'resume'])
        self.window._events.put(('line', '{"event":"task-paused","paused":false}'))
        self.window._drain_events()
        self.assertEqual(self.window.pause_button.text(), 'Pause')

    def test_install_zip_reloads_manifest_without_importing_game_code(self):
        archive = Path(self.temp.name) / "new-gamepack.zip"
        manifest = {
            "api_version": 1, "id": "fresh", "title": "Fresh package", "version": "1.00.00",
            "entrypoint": "entry.py:Package", "license": "test", "platforms": ["windows"],
            "execution": "native", "tasks": [{"id": "task", "title": "New task",
                                              "kind": "one-shot", "default_config": {},
                                              "required_capabilities": ["frames"]}],
        }
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("fresh/manifest.json", json.dumps(manifest))
            bundle.writestr("fresh/entry.py", "raise RuntimeError('installed code imported')\n")
        with patch("gameframe.gui.QFileDialog.getOpenFileName", return_value=(str(archive), "ZIP")):
            self.window.install_button.click()
        self.assertFalse(self.window.install_button.isEnabled())
        self._until(lambda: self.window.package_select.count() == 3)
        self.assertEqual(self.window._manifest().id, "fresh")
        self.assertEqual(self.window.task_list.count(), 1)
        self.assertTrue(self.window.install_button.isEnabled())
        self.assertEqual(self.controller.starts, [])

    def test_session_task_requests_reuse_worker_and_restore_launcher_choices(self):
        path = Path(self.temp.name) / 'native/manifest.json'
        metadata = json.loads(path.read_text())
        metadata['supports_session'] = True
        metadata['tasks'].append({'id': 'service', 'title': 'Service', 'kind': 'service'})
        path.write_text(json.dumps(metadata))
        self.window._reload_packages('native')
        self.window.config_edit.setPlainText('{"threshold":0.8}')
        self.window.start_selected()
        self.assertFalse(self.window.package_select.isEnabled())
        self._until(lambda: self.window.process is not None)
        self.assertTrue(self.window.start_button.isEnabled())
        self.window.task_list.setCurrentRow(1)
        self.window.start_selected()
        self.window.disable_selected()
        self.assertEqual(self.controller.controls,
                         [('set-service', 'service', True, {}), ('set-service', 'service', False, None)])
        self.window.task_list.setCurrentRow(0)
        self.assertEqual(json.loads(self.window.config_edit.toPlainText()), {'threshold': 0.8})
        self.window.start_selected()
        self.assertEqual(self.controller.controls[-1], ('run-task', 'task', {'threshold': 0.8}))
        self.assertEqual(len(self.controller.starts), 1)
        self.window.stop_selected()
        self._until(lambda: self.window.process is None)

    def test_management_is_a_separate_owned_process_without_device_construction(self):
        pack = Path(self.temp.name) / 'native'
        metadata = json.loads((pack / 'manifest.json').read_text())
        metadata['management'] = True
        (pack / 'manifest.json').write_text(json.dumps(metadata))
        (pack / 'entry.py').write_text(
            'import os, sys\nclass Package:\n'
            '    def management_command(self, data_dir):\n'
            '        return {"command":[sys.executable,"-u","-c",'
            '"import sys; print(\\\"management ready\\\",flush=True); sys.stdin.readline()"],'
            '"cwd":os.getcwd(),"env":os.environ.copy()}\n')
        self.window._reload_packages('native')
        self.window.manage_selected()
        self._until(lambda: 'management ready' in self.window.output.toPlainText())
        self.assertEqual(self.controller.starts, [])
        self.assertFalse(self.window.start_button.isEnabled())
        self.window.close()
        self._until(lambda: self.window._cleanup_done)
        self.assertEqual(self.window.management_controller.process.returncode, 0)


if __name__ == "__main__":
    unittest.main()
