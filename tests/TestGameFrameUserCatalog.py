"""Pure JSON discovery and real offline dynamic execution contracts."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gameframe.controller import Controller
from gameframe.packages import PackageManifest, discover

ROOT = Path(__file__).resolve().parents[1]


class TestGameFrameUserCatalog(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pack = self.root / 'pack'
        self.pack.mkdir()
        self.data = self.root / 'data'
        self.data.mkdir()
        (self.pack / 'plugin.py').write_text('class Package:\n    def run(self, task_id, context):\n        return {"task":task_id,"value":context.config["value"]}\n')
        self.metadata = dict(id='pack', version='1', api_version=1, entrypoint='plugin.py:Package',
            license='test', platforms=['offline'], task_catalog='user_tasks/catalog.json', tasks=[
                dict(id='builtin', title='Builtin', kind='one-shot')])
        self.write_manifest()
        self.catalog = dict(api_version=1, revision='abc', tasks=[dict(id='user:stable', title='User',
            kind='one-shot', default_config={'value': 7}, required_capabilities=[], source_id='ignored')])
        self.write_catalog()

    def write_manifest(self):
        (self.pack / 'manifest.json').write_text(json.dumps(self.metadata))

    def write_catalog(self):
        path = self.data / 'user_tasks/catalog.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(self.catalog))

    def test_metadata_only_and_catalog_boundaries(self):
        with patch.object(PackageManifest, 'load', side_effect=AssertionError('must not import')):
            manifest = discover(self.root)[0]
            self.assertEqual([task.id for task in manifest.available_tasks()], ['builtin'])
            self.assertEqual(manifest.task('user:stable', self.data).default_config, {'value': 7})
        for tasks in ([self.catalog['tasks'][0]] * 2, [dict(id='builtin', title='Shadow', kind='one-shot')],
                      [dict(id='bad', title='Bad', kind=[], required_capabilities=[])]):
            with self.subTest(tasks=tasks):
                self.catalog['tasks'] = tasks
                self.write_catalog()
                with self.assertRaises(ValueError):
                    manifest.available_tasks(self.data)
        self.metadata['task_catalog'] = '../outside.json'
        self.write_manifest()
        with self.assertRaises(ValueError):
            PackageManifest.read(self.pack)
        (self.data / 'user_tasks/catalog.json').unlink()
        self.assertEqual(manifest.available_tasks(self.data), manifest.tasks)

    def test_actual_cli_dynamic_id_and_capability_check(self):
        command = [sys.executable, '-m', 'gameframe', 'run', str(self.pack), '--task', 'user:stable',
                   '--data-dir', str(self.data), '--device', '{"type":"replay","frames":[]}']
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"task": "user:stable"', result.stdout)
        self.catalog['tasks'][0]['required_capabilities'] = ['unsupported-device-capability']
        self.write_catalog()
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('Device missing capabilities', result.stdout)

    def test_worker_rechecks_after_prepare_data_and_session_only_reload(self):
        (self.pack / 'plugin.py').write_text('import json\nclass Package:\n    def prepare_data(self, data_dir):\n'
            '        path=data_dir/"user_tasks/catalog.json"\n        value=json.loads(path.read_text())\n'
            '        value["tasks"]=[]\n        path.write_text(json.dumps(value))\n'
            '    def run(self, task_id, context):\n        raise AssertionError("deleted task ran")\n')
        controller = Controller()
        self.addCleanup(controller.close)
        with self.assertRaisesRegex(RuntimeError, 'shared task session'):
            controller.request_user_task_reload()
        process = controller.start(PackageManifest.read(self.pack), 'user:stable', data_dir=self.data,
                                   device={'type': 'replay', 'frames': []})
        output, _ = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 1, output)
        self.assertIn('Unknown task', output)
        self.assertFalse((self.data / 'runs.sqlite').exists())

    def test_execution_definition_revision_reaches_actual_runtime_context(self):
        self.catalog['tasks'][0]['revision'] = 'opaque-execution-definition'
        self.write_catalog()
        manifest = PackageManifest.read(self.pack)
        self.assertIsNone(manifest.task('builtin').revision)
        (self.pack / 'plugin.py').write_text('class Package:\n    def run(self, task_id, context):\n'
            '        return {"definition_revision":context.task_definition.revision}\n')
        result = subprocess.run([sys.executable, '-m', 'gameframe', 'run', str(self.pack),
            '--task', 'user:stable', '--data-dir', str(self.data), '--device', '{"type":"replay","frames":[]}'],
            cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"definition_revision": "opaque-execution-definition"', result.stdout)
        for invalid in (None, '', 1, []):
            with self.subTest(revision=invalid):
                self.catalog['tasks'][0]['revision'] = invalid
                self.write_catalog()
                with self.assertRaises(ValueError):
                    manifest.available_tasks(self.data)
