"""Offline checks for the complete compatibility application, not gameplay."""

import hashlib
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import ModuleType
import unittest
from unittest.mock import Mock, patch
import zipfile

from gameframe.packages import PackageManifest
from scripts.build_gamepack import build_gamepack, payload_files, source_metadata


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'gamepacks/wuthering_waves'


def load_bootstrap():
    spec = importlib.util.spec_from_file_location('ww_pack_bootstrap', PACK / 'bootstrap.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestGameFrameMigration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temporary.name)
        cls.archive = build_gamepack(cls.directory / 'gamepack.zip')
        with zipfile.ZipFile(cls.archive) as archive:
            archive.extractall(cls.directory / 'installed')
        cls.installed = cls.directory / 'installed/wuthering_waves'

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_registry_covers_all_production_tasks_and_characters(self):
        manifest = json.loads((PACK / 'manifest.json').read_text(encoding='utf-8'))
        actual = source_metadata(ROOT)
        self.assertEqual(manifest['tasks'], actual['tasks'])
        self.assertEqual(manifest['characters'], actual['characters'])
        self.assertEqual(sum(t['kind'] == 'one-shot' for t in manifest['tasks']), 22)
        self.assertEqual(sum(t['kind'] == 'service' for t in manifest['tasks']), 7)
        self.assertEqual(len(manifest['characters']), 57)
        self.assertIn('src/char/TrialGenericChar.py', manifest['characters'])

    def test_import_is_metadata_only_and_commands_select_exact_tasks(self):
        with patch.dict(sys.modules, {'config': None, 'ok': None}):
            manifest = PackageManifest.read(PACK)
            package = manifest.load()
            for task in manifest.tasks:
                launch = package.legacy_command(task.id, self.directory / 'records')
                self.assertEqual(launch['cwd'], str(ROOT))
                self.assertEqual(launch['command'][0], sys.executable)
                if task.id == 'application':
                    self.assertNotIn('--task-class', launch['command'])
                else:
                    self.assertEqual(launch['command'][-2:], ['--task-class', task.id])
            with self.assertRaises(KeyError):
                package.legacy_command('not-registered', self.directory)

    def test_shared_bootstrap_calls_production_without_running_it(self):
        bootstrap = load_bootstrap()
        production = ModuleType('main')
        production.run_application = Mock(return_value='production-result')
        original_argv, original_path = sys.argv[:], sys.path[:]
        try:
            with patch.dict(sys.modules, {'main': production}):
                self.assertEqual(bootstrap.run(ROOT, 'AutoCombatTask'), 'production-result')
                production.run_application.assert_called_once_with(task='AutoCombatTask', stop_event=None)
                self.assertEqual(sys.argv, [str(ROOT / 'main.py'), '--headless'])
                production.run_application.reset_mock()
                bootstrap.run(ROOT)
                production.run_application.assert_called_once_with(task=None, stop_event=None)
                self.assertEqual(sys.argv, [str(ROOT / 'main.py')])
                production.run_application.reset_mock()
                stop = threading.Event()
                bootstrap.listen_stop(stop, io.StringIO('{"command":"stop"}\n'))
                self.assertTrue(stop.is_set())
                bootstrap.run(ROOT, 'DailyTask', stop)
                production.run_application.assert_called_once_with(task='DailyTask', stop_event=stop)
        finally:
            sys.argv[:] = original_argv
            sys.path[:] = original_path

    def test_malformed_control_reports_failure_and_requests_production_stop(self):
        bootstrap = load_bootstrap()
        for message in ('invalid\n', '{}\n', 'null\n', '[]\n', '{"command":"pause"}\n'):
            with self.subTest(message=message):
                stop, output = threading.Event(), io.StringIO()
                with redirect_stdout(output):
                    bootstrap.listen_stop(stop, io.StringIO(message))
                self.assertTrue(stop.is_set())
                event = json.loads(output.getvalue())
                self.assertEqual(event['event'], 'control-failed')
                self.assertTrue(event['error'])

    def test_built_package_uses_its_own_payload_and_all_files_verify(self):
        manifest = PackageManifest.read(self.installed)
        package = manifest.load()
        launch = package.legacy_command('application', self.directory / 'records')
        payload = self.installed / 'payload'
        self.assertTrue((payload / 'src/runtime/framework_overlay.py').is_file())
        self.assertTrue((payload / 'src/vision/color.py').is_file())
        self.assertEqual(launch['cwd'], str(payload))
        self.assertIn(str(payload), launch['command'])
        self.assertNotIn(str(ROOT), launch['command'])
        contents = json.loads((self.installed / 'files.json').read_text(encoding='utf-8'))
        for name, digest in contents.items():
            self.assertEqual(hashlib.sha256((self.installed / name).read_bytes()).hexdigest(), digest, name)
        expected = {'payload/' + p.relative_to(ROOT).as_posix() for p in payload_files(ROOT)}
        self.assertTrue(expected.issubset(contents))
        source = source_metadata(payload)
        self.assertEqual(source['tasks'], package.manifest['tasks'])
        self.assertEqual(len(source['characters']), 57)
        for private in ('configs', 'logs', '.venv', '.git', '__pycache__'):
            self.assertFalse(any(private in Path(name).parts for name in contents), private)

    def test_untracked_runtime_data_cannot_enter_the_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for folder, name in (('configs', 'private-account.json'), ('logs', 'private.log'),
                                 ('.venv', 'private.py'), ('src/__pycache__', 'cached.pyc'),
                                 ('assets', 'vendor.dll')):
                path = root / folder / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('private sentinel', encoding='utf-8')
            names = {p.relative_to(root).as_posix() for p in payload_files(root)}
            self.assertFalse(any('private' in name or name.endswith(('.pyc', '.dll')) for name in names))


if __name__ == '__main__':
    unittest.main()
