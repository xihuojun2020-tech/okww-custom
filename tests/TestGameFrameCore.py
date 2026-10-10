import json
import hashlib
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

import cv2
import numpy as np

from gameframe.api import Cancelled
from gameframe.devices.replay import ReplayDevice
from gameframe.packages import PackageManifest, discover, install_archive, verify_index
from gameframe.runtime import Runtime
from gameframe.state import RunStore

ROOT = Path(__file__).resolve().parents[1]


class CountingReplay(ReplayDevice):
    def __init__(self, paths):
        super().__init__(paths)
        self.releases = 0

    def release_all(self):
        self.releases += 1
        super().release_all()


class TestGameFrameCore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = RunStore(self.root / 'runs.sqlite')
        self.events = []
        self.runtime = Runtime(self.store, self.events.append)
        self.manifest = PackageManifest.read(ROOT / 'examples/vision_probe')
        self.template = np.random.default_rng(123).integers(20, 230, (8, 9, 3), dtype=np.uint8)
        frame = np.zeros((30, 40, 3), dtype=np.uint8)
        frame[13:21, 17:26] = self.template
        cv2.imwrite(str(self.root / 'template.png'), self.template)
        cv2.imwrite(str(self.root / 'frame.png'), frame)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def run_package(self, package=None, device=None, **options):
        self.device = device or CountingReplay([self.root / 'frame.png'])
        return self.runtime.run(self.manifest, package or self.manifest.load(),
                                'find-template', self.device, self.root,
                                {'template': str(self.root / 'template.png')}, **options)

    def test_real_image_to_rule_to_action_and_ledger(self):
        result = self.run_package()
        self.assertEqual(result['position'], [17, 13])
        self.assertEqual(self.device.actions[0].kind, 'click')
        self.assertEqual(self.device.actions[0].values, {'x': 21, 'y': 17})
        self.assertEqual(self.device.releases, 1)
        self.assertEqual(self.store.history()[0]['status'], 'success')
        self.assertEqual([e['event'] for e in self.events], ['started', 'finished'])

    def test_no_match_is_blocked_and_sends_no_input(self):
        cv2.imwrite(str(self.root / 'frame.png'), np.zeros((30, 40, 3), dtype=np.uint8))
        self.run_package()
        self.assertEqual(self.store.history()[0]['status'], 'blocked')
        self.assertEqual(self.device.actions, [])

    def test_capture_failure_does_not_become_success(self):
        with self.assertRaises(TimeoutError):
            self.run_package(device=CountingReplay([]))
        self.assertEqual(self.device.releases, 1)
        self.assertEqual(self.store.history()[0]['status'], 'failed')

    def test_explicit_stop_is_cancelled(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaises(Cancelled):
            self.run_package(stop=stop)
        self.assertEqual(self.device.releases, 1)
        self.assertEqual(self.store.history()[0]['status'], 'cancelled')

    def test_failure_releases_held_input_and_owner(self):
        class Fails:
            def run(self, task_id, context):
                context.act('key_down', key='W')
                raise RuntimeError('synthetic decision failure')
        with self.assertRaisesRegex(RuntimeError, 'decision failure'):
            self.run_package(Fails())
        self.assertFalse(self.device.held)
        self.assertEqual(self.device.releases, 1)
        self.run_package()
        self.assertEqual(len(self.store.history()), 2)

    def test_returned_success_cannot_override_explicit_stop(self):
        class CatchesStop:
            def run(self, task_id, context):
                context.act('key_down', key='W')
                context.stop.set()
                return {'status': 'success'}
        with self.assertRaises(Cancelled):
            self.run_package(CatchesStop())
        self.assertEqual(self.store.history()[0]['status'], 'cancelled')
        self.assertFalse(self.device.held)

    def test_cleanup_failure_is_failed_and_does_not_lock_next_run(self):
        class BadCleanup(CountingReplay):
            def release_all(self):
                super().release_all()
                raise OSError('synthetic release failure')
        with self.assertRaisesRegex(OSError, 'release failure'):
            self.run_package(device=BadCleanup([self.root / 'frame.png']))
        self.assertEqual(self.store.history()[0]['status'], 'failed')
        self.run_package()

    def test_config_merge_failure_does_not_acquire_input_owner(self):
        with self.assertRaises(TypeError):
            self.runtime.run(self.manifest, self.manifest.load(), 'find-template',
                             CountingReplay([]), self.root, config=1)
        self.run_package()
        self.assertEqual(len(self.store.history()), 1)

    def test_diagnostic_failure_does_not_fail_task_or_stop_service(self):
        def failed_observer(value):
            raise OSError('synthetic closed observer')
        self.runtime.events = failed_observer
        stop = threading.Event()
        class Service:
            attempts = 0
            def run(self, task_id, context):
                self.attempts += 1
                if self.attempts == 1:
                    raise TimeoutError('synthetic capture outage')
                stop.set()
                return {'recovered': True}
        service = Service()
        self.store.set_enabled(self.manifest.id, 'find-template', True)
        with self.assertLogs('gameframe.runtime', level='ERROR'):
            self.runtime.run_service(self.manifest, service, 'find-template', CountingReplay([]),
                                     self.root, stop=stop)
        self.assertEqual(service.attempts, 2)
        self.assertTrue(self.store.enabled(self.manifest.id, 'find-template'))
        self.assertEqual([r['status'] for r in self.store.history()], ['cancelled', 'failed'])

    def test_nested_task_cannot_take_input_owner(self):
        outer = self
        class Nested:
            def run(self, task_id, context):
                with outer.assertRaisesRegex(RuntimeError, 'owns device input'):
                    outer.runtime.run(outer.manifest, outer.manifest.load(), task_id,
                                      context.device, outer.root)
                return {'nested_rejected': True}
        self.assertTrue(self.run_package(Nested())['nested_rejected'])

    def test_unknown_task_does_not_start_a_run(self):
        with self.assertRaises(KeyError):
            self.runtime.run(self.manifest, self.manifest.load(), 'missing',
                             CountingReplay([]), self.root)
        self.assertEqual(self.store.history(), [])

    def test_missing_device_capability_is_reported(self):
        device = CountingReplay([])
        device.capabilities = frozenset({'frames'})
        with self.assertRaisesRegex(ValueError, 'mouse'):
            self.run_package(device=device)
        self.assertEqual(self.store.history(), [])

    def test_service_errors_retain_intent_and_continue(self):
        stop = threading.Event()
        class Service:
            attempts = 0
            def run(self, task_id, context):
                self.attempts += 1
                if self.attempts < 3:
                    raise TimeoutError('synthetic lost capture')
                stop.set()
                return {'recovered': True}
        service = Service()
        self.store.set_enabled(self.manifest.id, 'find-template', True)
        self.runtime.run_service(self.manifest, service, 'find-template', CountingReplay([]),
                                 self.root, stop=stop)
        self.assertEqual(service.attempts, 3)
        self.assertTrue(self.store.enabled(self.manifest.id, 'find-template'))
        self.assertEqual([r['status'] for r in self.store.history()], ['cancelled', 'failed', 'failed'])

    def test_disabled_service_is_not_forcibly_enabled(self):
        class MustNotRun:
            def run(self, *args):
                raise AssertionError('disabled service ran')
        self.runtime.run_service(self.manifest, MustNotRun(), 'find-template', CountingReplay([]),
                                 self.root, stop=threading.Event())
        self.assertFalse(self.store.enabled(self.manifest.id, 'find-template'))
        self.assertEqual(self.store.history(), [])

    def test_preferences_survive_store_reopen(self):
        self.store.set_enabled('ww', 'combat', True)
        second = RunStore(self.root / 'runs.sqlite')
        try:
            self.assertTrue(second.enabled('ww', 'combat'))
        finally:
            second.close()

    def test_external_manifest_duplicate_and_escaping_entry_rejected(self):
        value = json.loads((self.manifest.root / 'manifest.json').read_text())
        package = self.root / 'pack'
        package.mkdir()
        (package / 'plugin.py').write_text('def create_package(): return None')
        value['tasks'] *= 2
        (package / 'manifest.json').write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            PackageManifest.read(package)
        value['tasks'] = value['tasks'][:1]
        (self.root / 'outside.py').write_text('pass')
        value['entrypoint'] = '../outside.py:create_package'
        (package / 'manifest.json').write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'inside'):
            PackageManifest.read(package)

    def test_empty_package_directory_has_no_side_effect(self):
        self.assertEqual(discover(self.root / 'not-installed'), ())

    def test_install_package_and_relative_import_without_overwriting_data(self):
        value = json.loads((self.manifest.root / 'manifest.json').read_text())
        files = {'manifest.json': json.dumps(value).encode(),
                 'plugin.py': b'from .rules import Package\ndef create_package(): return Package()\n',
                 'rules.py': b'class Package:\n    name = "installed-relative-module"\n'}
        archive = self.root / 'pack.zip'
        with zipfile.ZipFile(archive, 'w') as output:
            for name, data in files.items():
                output.writestr('pack/' + name, data)
            output.writestr('pack/files.json', json.dumps(
                {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}))
        installed = install_archive(archive, self.root / 'packages')
        self.assertEqual(installed.load().name, 'installed-relative-module')
        verify_index(installed.root, required=True)
        self.assertEqual(list(installed.root.rglob('*.pyc')), [])
        private = installed.root / 'configs' / 'local.json'
        private.parent.mkdir()
        private.write_text('private data')
        with self.assertRaises(FileExistsError):
            install_archive(archive, self.root / 'packages')
        self.assertEqual(private.read_text(), 'private data')

    def test_install_rejects_path_escape_and_corrupt_content_without_partial_package(self):
        for reason in ('path', 'hash'):
            with self.subTest(reason=reason):
                archive = self.root / (reason + '.zip')
                with zipfile.ZipFile(archive, 'w') as output:
                    output.writestr('pack/manifest.json', (self.manifest.root / 'manifest.json').read_bytes())
                    output.writestr('pack/plugin.py', b'def create_package(): return None')
                    if reason == 'path':
                        output.writestr('../outside.py', b'pass')
                    else:
                        output.writestr('pack/files.json', '{}')
                with self.assertRaisesRegex(ValueError, 'Unsafe|SHA256'):
                    install_archive(archive, self.root / 'packages')
                self.assertFalse((self.root / 'outside.py').exists())
                self.assertEqual(list((self.root / 'packages').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
