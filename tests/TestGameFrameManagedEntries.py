# SPDX-License-Identifier: MIT
"""Actual CLI/child entry ownership and core-version boundaries, device-free."""
from contextlib import contextmanager, nullcontext
import importlib.metadata
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gameframe import __main__ as cli, managed_install, package_process, worker
from gameframe.controller import Controller
from gameframe.core_release_version import release_key
from gameframe.packages import PackageManifest


class TestGameFrameManagedEntries(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.managed = self.root / 'managed'
        self.package = self.root / 'package'
        self.package.mkdir()
        self.data = self.root / 'users'
        self.trace = []
        self.owner_active = False
        self.value = dict(api_version=1, id='entry-fixture', version='1.97.76',
                          channel='beta', revision=2, supports_managed_updates=True,
                          entrypoint='plugin.py:create_package', license='MIT', platforms=['windows'],
                          management=True, overview=True, configuration=True,
                          tasks=[dict(id='fixture', title='fixture', kind='one-shot')])
        (self.package / 'plugin.py').write_text('def create_package(): pass', encoding='utf-8')
        self.write_manifest()
        self.manifest = PackageManifest.read(self.package)
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop('GAMEFRAME_MANAGED_ROOT', None)

    def write_manifest(self):
        (self.package / 'manifest.json').write_text(json.dumps(self.value), encoding='utf-8')

    @contextmanager
    def owner(self, root, *, environment):
        self.assertEqual(root, self.managed)
        self.assertEqual(environment, sys.prefix)
        self.owner_active = True
        self.trace.append('owner-enter')
        try:
            yield
        finally:
            self.trace.append('owner-exit')
            self.owner_active = False

    def inside(self, operation):
        self.assertTrue(self.owner_active)
        self.assertEqual(os.environ['GAMEFRAME_MANAGED_ROOT'], str(self.managed))
        self.trace.append(operation)

    def test_cli_gui_run_manage_overview_hold_owner_through_cleanup_and_restore_env(self):
        parent = self
        process = SimpleNamespace(stdout=(), stdin=io.StringIO(),
                                  wait=lambda: (parent.inside('wait') or 0))
        class FakeController:
            def start(self, *args, **kwargs): parent.inside('run'); return process
            def start_management(self, *args, **kwargs): parent.inside('manage'); return process
            def start_overview(self, *args, **kwargs): parent.inside('overview'); return process
            def close(self): parent.inside('close')
        from gameframe import gui
        def run_gui(packages, data, **options):
            self.inside('gui')
            self.assertEqual(options['managed_root'], self.managed)
            return 0
        for command in ('run', 'manage', 'overview', 'gui'):
            self.trace.clear()
            arguments = ([command, '--packages', str(self.package), '--data-dir', str(self.data)]
                         if command == 'gui' else [command, str(self.package), '--data-dir', str(self.data)])
            if command == 'run': arguments.extend(['--task', 'fixture', '--device', '{"type":"replay","frames":[]}'])
            arguments.extend(['--managed-root', str(self.managed)])
            os.environ['GAMEFRAME_MANAGED_ROOT'] = str(self.root / 'previous-root')
            with self.subTest(command=command), patch.object(managed_install, 'managed_owner', self.owner), \
                 patch.object(cli, 'Controller', FakeController), patch.object(gui, 'run_gui', run_gui), \
                 patch.object(cli.threading, 'Thread', return_value=SimpleNamespace(start=lambda: None)):
                self.assertEqual(cli.main(arguments), 0)
            self.assertEqual(os.environ['GAMEFRAME_MANAGED_ROOT'], str(self.root / 'previous-root'))
            self.assertEqual((self.trace[0], self.trace[-1]), ('owner-enter', 'owner-exit'))
            if command != 'gui': self.assertLess(self.trace.index('close'), self.trace.index('owner-exit'))

    def test_worker_explicit_and_inherited_root_hold_through_device_package_store_cleanup(self):
        device = SimpleNamespace(close=lambda: self.inside('device-close'))
        package = SimpleNamespace(close=lambda: self.inside('package-close'))
        store = SimpleNamespace(close=lambda: self.inside('store-close'))
        runtime = SimpleNamespace(run=lambda *args, **kwargs: self.inside('runtime'))
        args = ['--package', str(self.package), '--task', 'fixture', '--data-dir', str(self.data),
                '--device', '{"type":"replay","frames":[]}']
        for explicit in (True, False):
            self.trace.clear()
            os.environ['GAMEFRAME_MANAGED_ROOT'] = str(self.managed)
            entry = args + (['--managed-root', str(self.managed)] if explicit else [])
            with self.subTest(explicit=explicit), patch.object(managed_install, 'managed_owner', self.owner), \
                 patch.object(worker, 'package_lease', return_value=nullcontext()), \
                 patch.object(worker, 'data_lease', return_value=nullcontext()), \
                 patch.object(worker, 'device_input_lease', return_value=nullcontext()), \
                 patch.object(PackageManifest, 'load', return_value=package), \
                 patch.object(worker, 'create_device', side_effect=lambda options: (self.inside('device') or device)), \
                 patch.object(worker, 'RunStore', return_value=store), patch.object(worker, 'Runtime', return_value=runtime), \
                 patch.object(worker.threading, 'Thread', return_value=SimpleNamespace(start=lambda: None)):
                self.assertEqual(worker.main(entry), 0)
            self.assertEqual(self.trace[-4:], ['device-close', 'package-close', 'store-close', 'owner-exit'])

    def test_worker_same_base_different_prerelease_refused_before_device(self):
        expected = {**self.manifest.release_identity, 'revision': 1}
        with patch.object(worker, 'package_lease', return_value=nullcontext()), \
             patch.object(worker, 'create_device') as device, patch.object(worker, 'RunStore') as store, \
             patch.object(worker, 'emit') as emit, \
             patch.object(worker.threading, 'Thread', return_value=SimpleNamespace(start=lambda: None)):
            result = worker.main(['--package', str(self.package), '--expected-identity', json.dumps(expected),
                '--task', 'fixture', '--data-dir', str(self.data), '--device', '{"type":"replay","frames":[]}'])
        self.assertEqual(result, 1)
        self.assertIn('release identity changed', emit.call_args[0][0]['error'])
        device.assert_not_called()
        store.assert_not_called()

    def test_package_process_management_config_overview_owner_and_complete_identity(self):
        args = ['--package', str(self.package), '--expected-version', self.manifest.version,
                '--expected-identity', json.dumps(self.manifest.release_identity),
                '--managed-root', str(self.managed), '--module', 'fixture_module', '--', '--fixture-option']
        with patch.object(managed_install, 'managed_owner', self.owner), \
             patch.object(package_process, 'package_lease', return_value=nullcontext()), \
             patch.object(sys, 'argv', list(sys.argv)), \
             patch.object(package_process.runpy, 'run_module', side_effect=lambda *a, **kw: self.inside('package-module')) as execute:
            self.assertEqual(package_process.main(args), 0)
            execute.assert_called_once_with('fixture_module', run_name='__main__', alter_sys=True)
            self.assertEqual(sys.argv, ['fixture_module', '--fixture-option'])
        self.assertEqual(self.trace, ['owner-enter', 'package-module', 'owner-exit'])
        args[args.index('--expected-identity') + 1] = json.dumps({**self.manifest.release_identity, 'revision': 1})
        with patch.object(managed_install, 'managed_owner', self.owner), \
             patch.object(package_process, 'package_lease', return_value=nullcontext()), \
             patch.object(package_process.runpy, 'run_module') as execute:
            with self.assertRaisesRegex(ValueError, 'release identity changed'): package_process.main(args)
            execute.assert_not_called()

    def test_controller_all_native_launches_carry_identity_before_module_arguments(self):
        def launch(data):
            return {'command': [sys.executable, '-m', 'gameframe.package_process', '--package', str(self.package),
                               '--expected-version', self.manifest.version, '--module', 'fixture', '--', '--data', str(data)],
                    'cwd': str(self.root), 'env': {}}
        package = SimpleNamespace(management_command=launch, overview_command=launch, configuration_command=launch)
        for method in ('start', 'start_management', 'start_overview', 'start_configuration'):
            controller = Controller()
            with self.subTest(method=method), patch('gameframe.controller.package_lease', return_value=nullcontext()), \
                 patch.object(PackageManifest, 'load', return_value=package), patch.object(controller, '_launch') as child:
                if method == 'start': controller.start(self.manifest, 'fixture', data_dir=self.data, device={'type':'replay','frames':[]})
                else: getattr(controller, method)(self.manifest, data_dir=self.data)
                command = child.call_args[0][0]
                self.assertEqual(json.loads(command[command.index('--expected-identity') + 1]), self.manifest.release_identity)
                if '--' in command: self.assertLess(command.index('--expected-identity'), command.index('--'))

    def test_controller_child_environment_receives_explicit_managed_root(self):
        from gameframe import controller as module
        controller = Controller()
        process = SimpleNamespace(pid=987654, poll=lambda: 0, wait=lambda **kwargs: 0,
                                  stdin=io.StringIO(), stdout=io.StringIO())
        def create_process(command, **options):
            self.inside('spawn')
            self.assertEqual(options['env']['GAMEFRAME_MANAGED_ROOT'], str(self.managed))
            return process
        with patch.object(managed_install, 'managed_owner', self.owner), \
             patch.object(module.subprocess, 'Popen', side_effect=create_process), \
             patch.object(module.psutil, 'Process', side_effect=module.psutil.NoSuchProcess(987654)):
            with managed_install.managed_entry(self.managed):
                controller._launch(['fixture-child'], str(self.root), {}, 'management', False)
                controller.close()
        self.assertNotIn('GAMEFRAME_MANAGED_ROOT', os.environ)

    def test_core_minimum_metadata_boundary_normalization_and_prerelease_order(self):
        self.value['required_core_version'] = '1.04.02'
        self.write_manifest()
        with patch('importlib.metadata.version', return_value='1.4.1'):
            with self.assertRaisesRegex(ValueError, 'requires gameframe-runtime'): PackageManifest.read(self.package)
        with patch('importlib.metadata.version', return_value='1.4.2'):
            self.assertEqual(PackageManifest.read(self.package).required_core_version, '1.04.02')
        self.value['required_core_version'] = '1.97.76b2'
        self.write_manifest()
        for installed, accepted in [('1.97.76a9', False), ('1.97.76b1', False), ('1.97.76b2', True),
                                    ('1.97.76', True), ('1.97.77a1', True)]:
            with self.subTest(installed=installed), patch('importlib.metadata.version', return_value=installed):
                if accepted: PackageManifest.read(self.package)
                else:
                    with self.assertRaises(ValueError): PackageManifest.read(self.package)
        with patch('importlib.metadata.version', side_effect=importlib.metadata.PackageNotFoundError('gameframe-runtime')):
            with self.assertRaisesRegex(ValueError, 'installed gameframe-runtime'): PackageManifest.read(self.package)
        for value in ('1.2', '1.2.3.dev1', '1.2.3+local', '1.2.3b0'):
            with self.subTest(value=value), self.assertRaises(ValueError): release_key(value)

    def test_managed_update_metadata_bool_and_legacy_defaults(self):
        self.assertTrue(self.manifest.supports_managed_updates)
        self.value['supports_managed_updates'] = 'true'
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'must be a boolean'): PackageManifest.read(self.package)
        for name in ('supports_managed_updates', 'channel', 'revision'): self.value.pop(name)
        self.write_manifest()
        legacy = PackageManifest.read(self.package)
        self.assertFalse(legacy.supports_managed_updates)
        self.assertEqual((legacy.channel, legacy.revision), ('stable', 0))


if __name__ == '__main__':
    unittest.main()
