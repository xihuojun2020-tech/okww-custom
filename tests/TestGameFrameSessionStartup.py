"""Session-only lifecycle over local worker fixtures and offscreen Qt."""

import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class TestGameFrameSessionStartup(unittest.TestCase):
    def test_worker_session_only_has_no_task_or_enable_action(self):
        from gameframe.controller import Controller
        from gameframe.packages import PackageManifest
        from gameframe.state import RunStore
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'entry.py').write_text('''
class Package:
    def prepare(self, task, data):
        assert task is None
    def run(self, task, context):
        raise AssertionError('one-shot ran')
    def run_session(self, task, context):
        assert task is None and context.task_definition is None and context.config == {}
        context.emit('fixture-restored', disabled_preserved=True)
        return {'restored': True}
''', encoding='utf-8')
            (root / 'manifest.json').write_text(json.dumps(dict(api_version=1, id='fixture', title='fixture',
                version='1.00.00', entrypoint='entry.py:Package', license='test', platforms=['windows'],
                supports_session=True, session_required_capabilities=['frames'],
                tasks=[dict(id='service', title='service', kind='service', default_config={'_enabled': False})])),
                encoding='utf-8')
            frame = Path(__file__).resolve().parent / 'images/in_combat.png'
            controller = Controller()
            try:
                process = controller.start(PackageManifest.read(root), None, data_dir=root / 'data',
                    device={'type': 'replay', 'frames': [str(frame)]}, session=True)
                output, _ = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, output)
                self.assertIn('fixture-restored', output)
                store = RunStore(root / 'data/runs.sqlite')
                try:
                    self.assertEqual(store.history()[0]['task_id'], '__session__')
                    self.assertEqual(store.history()[0]['status'], 'success')
                    self.assertFalse(store.enabled('fixture', 'service'))
                finally:
                    store.close()
                self.assertEqual(json.loads((root / 'data/actions.json').read_text()), [])
            finally:
                controller.close()

    def test_gui_restore_only_session_and_selected_local_user_root(self):
        from tests.TestGameFrameDesktopControls import TestGameFrameDesktopControls
        fixture = TestGameFrameDesktopControls()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        window = fixture.window
        window.packages = tuple(replace(item, supports_session=True) if item.id == 'native' else item
                                for item in window.packages)
        window._select_package(window.package_select.currentIndex())
        window.config_edit.setPlainText('invalid task override is irrelevant to session')
        window.device_edit.setPlainText(json.dumps({'type': 'replay', 'frames': [str(
            Path(__file__).resolve().parent / 'images/in_combat.png')]}))
        self.assertIn(str(window.data_dir), window.user_context_label.text())
        self.assertIn('Windows', window.user_context_label.text())
        window._restore_saved_session()
        self.assertEqual(fixture.fixture.controller.starts, [])  # No explicitly saved device yet.
        window.start_session()
        fixture.fixture._until(lambda: window.process is not None)
        self.assertEqual(fixture.fixture.controller.starts[0][1:3], (None, {}))
        self.assertEqual(len(fixture.fixture.controller.starts), 1)
        window._restore_saved_session()
        self.assertEqual(len(fixture.fixture.controller.starts), 1)
        window.restore_services.setChecked(False)
        saved = json.loads(window._context_path.read_text(encoding='utf-8'))
        self.assertFalse(saved['restore_services'])
        self.assertEqual(saved['selected_package'], 'native')
        self.assertEqual(saved['data_root'], str(window.data_dir))
        with patch('gameframe.gui.QFileDialog.getExistingDirectory', side_effect=AssertionError('owner active')):
            window.choose_data_root()
        self.assertIn('running', window.status_label.text())

    def test_gui_saved_startup_disabled_and_local_root_rejection(self):
        from gameframe.launcher_context import local_root, load_context, save_context
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'launcher-context.json'
            save_context(path, {'restore_services': False, 'selected_package': 'fixture', 'data_root': str(root)})
            self.assertFalse(load_context(path)['restore_services'])
            with self.assertRaises(ValueError):
                local_root('\\\\fixture-host\\share')
            with self.assertRaises(ValueError):
                local_root('relative-root')
