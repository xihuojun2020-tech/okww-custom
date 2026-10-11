# SPDX-License-Identifier: MIT
"""Offline subprocess and shared-file-lease fixtures; no pip or OS process launch."""
from contextlib import contextmanager, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile


from gameframe import managed_bootstrap as bootstrap
from gameframe import managed_install as install


class LeaseFixture:
    def __init__(self):
        self.held = {}
        self.events = []

    @contextmanager
    def __call__(self, path, exclusive):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        readers, writer = self.held.get(path, (0, False))
        if writer or (exclusive and readers):
            raise bootstrap.LeaseBusy('fixture active owner')
        self.held[path] = (readers + (not exclusive), exclusive)
        self.events.append(('acquire', path.name, exclusive))
        try:
            yield
        finally:
            current_readers, _ = self.held[path]
            self.held[path] = (current_readers - (not exclusive), False)
            self.events.append(('release', path.name, exclusive))


def descriptor(root, path):
    return {'path': path.relative_to(root).as_posix(), 'size': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


class BuildRunner:
    def __init__(self, lease):
        self.calls = []
        self.fail = None
        self.lease = lease

    def __call__(self, command, **options):
        self.calls.append((command, options))
        stage = ('venv' if 'venv' in command else 'pip-check' if 'pip' in command and 'check' in command
                 else 'pip' if 'pip' in command else 'preflight')
        if stage == self.fail:
            raise subprocess.CalledProcessError(1, command, stderr='fixture ' + stage + ' failure')
        if stage == 'venv':
            environment = Path(command[-1])
            (environment / 'Scripts').mkdir(parents=True)
            (environment / 'Scripts/python.exe').touch()
            (environment / 'Scripts/pythonw.exe').touch()
            return SimpleNamespace(returncode=0)
        if stage == 'pip':
            assert '--no-index' in command and '--no-cache-dir' in command and '--only-binary=:all:' in command
            assert command[-1].startswith('gameframe-runtime[gui,windows]==')
            assert 'fixture_dependency==1.0' in command
            assert 'management-fixture==2.0; python_version >= "3.12"' in command
            assert options['env']['PIP_CONFIG_FILE'] == __import__('os').devnull
            return SimpleNamespace(returncode=0)
        if stage == 'pip-check':
            return SimpleNamespace(returncode=0)
        # Execute the actual no-device preflight script, using production package installer/index.
        import gameframe
        from gameframe import packages
        environment = Path(command[-2])
        core_version = json.loads(command[-3])['core']['version']
        stdout = io.StringIO()
        with patch.object(gameframe, '__file__', str(environment / 'Lib/site-packages/gameframe/__init__.py')), \
             patch('importlib.metadata.version', return_value=core_version), \
             patch.object(packages, 'package_lease', lambda *args, **kwargs: self.lease(environment / 'pack.lock', True)), \
             patch.object(sys, 'argv', ['-c', *command[-3:]]), redirect_stdout(stdout):
            exec(compile(command[4], '<managed-preflight>', 'exec'), {'__name__': '__main__'})
        return SimpleNamespace(returncode=0, stdout=stdout.getvalue())


class TestManagedInstallation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root, self.artifacts, self.data = (self.directory / name for name in ('managed', 'release', 'users'))
        self.artifacts.mkdir()
        self.data.mkdir()
        self.combat = self.data / 'combat.json'
        self.combat.write_bytes(b'{"_enabled":false,"account":"synthetic"}')
        self.original_data = self.combat.read_bytes()
        self.base = self.directory / 'stable/python.exe'
        self.base.parent.mkdir()
        self.base.touch()
        self.pythonw = self.base.with_name('pythonw.exe')
        self.pythonw.touch()
        self.entry = install.initialize(self.root, bootstrap_pythonw=self.pythonw,
                                        base_python=self.base, data_dir=self.data)
        self.lease = LeaseFixture()
        self.runner = BuildRunner(self.lease)
        core = self.artifacts / 'gameframe_runtime-1.97.76-py3-none-any.whl'
        with zipfile.ZipFile(core, 'w') as wheel:
            wheel.writestr('gameframe_runtime-1.97.76.dist-info/METADATA',
                           'Name: gameframe-runtime\nVersion: 1.97.76\n')
        dependency = self.artifacts / 'fixture_dependency-1.0-py3-none-any.whl'
        dependency.write_bytes(b'fake dependency wheel used only by fake pip')
        pack = self.artifacts / 'native.zip'
        manifest = {'api_version': 1, 'id': 'native-fixture', 'version': '1.97.76',
                    'channel': 'stable', 'revision': 0, 'required_core_version': '1.97.76',
                    'entrypoint': 'plugin.py:create_package', 'license': 'AGPL-3.0',
                    'platforms': ['windows'], 'tasks': []}
        files = {'manifest.json': json.dumps(manifest).encode(),
                 'requirements.txt': b'# runtime\nfixture_dependency==1.0\n',
                 'requirements-management.txt': b'management-fixture==2.0; python_version >= "3.12"\n',
                 'plugin.py': b'def create_package(): raise AssertionError("never import game code")\n'}
        index = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
        files['files.json'] = json.dumps(index).encode()
        with zipfile.ZipFile(pack, 'w') as archive:
            for name, content in files.items(): archive.writestr('native-fixture/' + name, content)
        self.bundle = {'schema_version': 2, 'package_id': 'native-fixture', 'version': '1.97.76',
                       'channel': 'stable', 'revision': 0, 'published_at': '2026-10-11T00:00:00Z',
                       'core': {**descriptor(self.artifacts, core), 'version': '1.97.76'},
                       'gamepack': {**descriptor(self.artifacts, pack), 'package_id': 'native-fixture',
                                    'version': '1.97.76', 'channel': 'stable', 'revision': 0,
                                    'required_core_version': '1.97.76'},
                       'wheels': [descriptor(self.artifacts, dependency)]}

    def prepare(self, *, automatic=False):
        return install.prepare_environment(self.root, self.artifacts, self.bundle,
                                          base_python=self.base, automatic=automatic,
                                          run=self.runner, lease=self.lease)

    def test_archive_requirements_reject_external_sources_before_ready(self):
        pack = self.artifacts / 'native.zip'
        with zipfile.ZipFile(pack) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        for requirement in ('fixture @ https://example.invalid/a.whl', '-r other.txt', './local.whl', '--find-links https://example.invalid'):
            files['native-fixture/requirements.txt'] = requirement.encode()
            with zipfile.ZipFile(pack, 'w') as archive:
                for name, content in files.items():
                    archive.writestr(name, content)
            self.bundle['gamepack'].update(descriptor(self.artifacts, pack))
            with self.assertRaisesRegex(ValueError, 'Unsupported offline requirement'):
                self.prepare()
            self.assertFalse((self.root / 'pending.json').exists())
            self.assertEqual(list((self.root / 'versions').iterdir()), [])

    def test_missing_gamepack_requirement_resolver_failure_never_ready(self):
        runner = self.runner
        def missing_wheel(command, **options):
            if 'install' in command:
                self.assertIn('management-fixture==2.0; python_version >= "3.12"', command)
                raise subprocess.CalledProcessError(1, command, stderr='No matching distribution found for management-fixture==2.0')
            return runner(command, **options)
        with self.assertRaises(subprocess.CalledProcessError):
            install.prepare_environment(self.root, self.artifacts, self.bundle, base_python=self.base,
                                        run=missing_wheel, lease=self.lease)
        self.assertFalse((self.root / 'pending.json').exists())
        self.assertEqual(list((self.root / 'versions').iterdir()), [])

    def test_late_candidate_cannot_overwrite_newer_pending_or_active(self):
        newer = json.loads(json.dumps(self.prepare()))
        newer['bundle']['core']['version'] = '1.97.77'
        for target in ('pending.json', 'active.json'):
            (self.root / 'pending.json').unlink(missing_ok=True)
            environments = set((self.root / 'versions').iterdir())
            def interleaved(command, **options):
                result = self.runner(command, **options)
                if '-c' in command:
                    # Another already verified preparation publishes while this one preflights.
                    bootstrap.atomic_json(self.root / target, newer)
                return result
            with self.assertRaisesRegex(ValueError, 'newer managed release'):
                install.prepare_environment(self.root, self.artifacts, self.bundle, base_python=self.base,
                                            run=interleaved, lease=self.lease)
            self.assertEqual(bootstrap.read_json(self.root / target), newer)
            self.assertEqual(set((self.root / 'versions').iterdir()), environments)
        (self.root / 'active.json').unlink()
        pointer = self.prepare()
        before = (self.root / 'pending.json').read_bytes()
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual((self.root / 'pending.json').read_bytes(), before)
        self.bundle['published_at'] = '2026-10-11T01:00:00Z'
        with self.assertRaisesRegex(ValueError, 'conflicting content'):
            self.prepare()
        self.assertEqual((self.root / 'pending.json').read_bytes(), before)
        self.assertEqual(set((self.root / 'versions').iterdir()), environments | {self.root / pointer['environment']})

    def launch_runner(self, command, **options):
        self.launched = (command, options)
        # The GUI and every descendant can share ownership while bootstrap stays alive.
        with self.lease(self.root / '.leases/environment.lock', False):
            with self.assertRaises(bootstrap.LeaseBusy):
                with self.lease(self.root / '.leases/environment.lock', True): pass
        return SimpleNamespace(returncode=0)

    def test_scheduled_dispatch_uses_active_release_and_current_data_root(self):
        old = self.prepare()
        bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease)
        incoming = self.prepare()
        relocated = self.directory / 'relocated'
        bootstrap.atomic_json(self.data / 'launcher-context.json', {'data_root': str(relocated)})
        options = dict(package_id='native-fixture', task='daily', device={'type': 'fixture'}, config={'account': 'A1'})
        with self.lease(self.root / '.leases/environment.lock', False):
            bootstrap.launch(self.root, **options, run=self.launch_runner, lease=self.lease)
            self.assertEqual(self.launched[0][0], str(self.root / old['environment'] / 'Scripts/pythonw.exe'))
            self.assertTrue((self.root / 'pending.json').exists())
        bootstrap.launch(self.root, **options, run=self.launch_runner, lease=self.lease)
        command = self.launched[0]
        self.assertEqual(command[:5], [str(self.root / incoming['environment'] / 'Scripts/pythonw.exe'),
                         '-m', 'gameframe', 'run', str(self.root / incoming['environment'] / 'gamepacks/native-fixture')])
        self.assertEqual(command[command.index('--data-dir') + 1], str(relocated / 'native-fixture'))
        self.assertEqual(json.loads(command[command.index('--config') + 1]), {'account': 'A1'})
        self.assertNotIn('--session', command)
        self.assertEqual(self.combat.read_bytes(), self.original_data)
        with self.assertRaisesRegex(ValueError, 'does not match'):
            bootstrap.launch(self.root, **dict(options, package_id='different'), run=self.launch_runner, lease=self.lease)
        bootstrap.atomic_json(self.data / 'launcher-context.json', {'data_root': 'relative'})
        with self.assertRaisesRegex(ValueError, 'absolute local'):
            bootstrap.launch(self.root, **options, run=self.launch_runner, lease=self.lease)

    def test_scheduled_cli_requires_explicit_objects_and_package(self):
        common = ['--managed-root', str(self.root)]
        for arguments in (['--task', 'daily'], ['--device', '{}'],
                          ['--task', 'daily', '--package-id', 'native-fixture', '--device', '[]']):
            with self.assertRaises(SystemExit), patch('sys.stderr', io.StringIO()):
                bootstrap.main(common + arguments)
        with patch.object(bootstrap, 'launch', return_value=7) as launch:
            self.assertEqual(bootstrap.main(common + ['--task', 'daily', '--package-id', 'native-fixture', '--device', '{}']), 7)
            self.assertEqual(launch.call_args.kwargs, dict(package_id='native-fixture', task='daily', device={}, config=None))

    def test_verified_offline_build_preflight_pending_and_normal_launch_commit(self):
        pointer = self.prepare()
        self.assertFalse((self.root / 'active.json').exists())
        self.assertEqual(bootstrap.read_json(self.root / 'pending.json'), pointer)
        self.assertEqual(len(self.runner.calls), 4)
        self.assertEqual(bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease), 0)
        self.assertEqual(bootstrap.read_json(self.root / 'active.json'), pointer)
        self.assertFalse((self.root / 'pending.json').exists())
        command, options = self.launched
        self.assertEqual(command[1:4], ['-m', 'gameframe', 'gui'])
        self.assertNotIn('--task', command)
        self.assertEqual(command[command.index('--data-dir') + 1], str(self.data))
        self.assertEqual(options['env']['GAMEFRAME_MANAGED_ROOT'], str(self.root))
        self.assertNotIn('PYTHONPATH', options['env'])
        self.assertEqual(self.combat.read_bytes(), self.original_data)
        self.assertEqual(self.entry[0], str(self.pythonw))
        self.assertEqual(self.entry[1], str(self.root / 'bootstrap.py'))
        self.assertNotIn('versions', str(self.entry))

    def test_active_gui_or_surviving_worker_keeps_pending_and_active(self):
        old = self.prepare()
        bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease)
        incoming = self.prepare()
        active_bytes = (self.root / 'active.json').read_bytes()
        old_environment = self.root / old['environment']
        # No GUI needs to exist; this independent owner's shared lease is sufficient.
        with install.managed_owner(self.root, environment=old_environment, lease=self.lease):
            bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease)
            self.assertEqual((self.root / 'active.json').read_bytes(), active_bytes)
            self.assertEqual(bootstrap.read_json(self.root / 'pending.json'), incoming)
            self.assertEqual(self.launched[0][0], str(old_environment / 'Scripts/pythonw.exe'))
        bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease)
        self.assertEqual(bootstrap.read_json(self.root / 'active.json'), incoming)
        with self.assertRaisesRegex(RuntimeError, 'no longer'):
            with install.managed_owner(self.root, environment=old_environment, lease=self.lease): pass
        self.assertEqual(self.combat.read_bytes(), self.original_data)

    def test_build_failures_leave_existing_active_and_pending_untouched(self):
        self.prepare()
        bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease)
        self.prepare()
        active, pending = ((self.root / name).read_bytes() for name in ('active.json', 'pending.json'))
        existing = set((self.root / 'versions').iterdir())
        for failure in ('venv', 'pip', 'pip-check', 'preflight'):
            self.runner.fail = failure
            with self.subTest(failure=failure), self.assertRaises(subprocess.CalledProcessError):
                self.prepare()
            self.assertEqual((self.root / 'active.json').read_bytes(), active)
            self.assertEqual((self.root / 'pending.json').read_bytes(), pending)
            self.assertEqual(set((self.root / 'versions').iterdir()), existing)
        self.assertEqual(self.combat.read_bytes(), self.original_data)

    def test_sha_size_and_relative_path_fail_before_subprocess(self):
        original = dict(self.bundle['core'])
        for updates in ({'sha256': '0' * 64}, {'size': original['size'] + 1}, {'path': '../core.whl'}):
            self.bundle['core'] = {**original, **updates}
            with self.subTest(updates=updates), self.assertRaises(ValueError): self.prepare()
        self.assertEqual(self.runner.calls, [])
        self.assertFalse((self.root / 'pending.json').exists())

    def test_core_and_bundle_identity_rejected_before_build(self):
        for target, key, value in [('core', 'version', '1.97.77'), ('gamepack', 'channel', 'beta')]:
            old = self.bundle[target][key]
            self.bundle[target][key] = value
            with self.subTest(target=target), self.assertRaises(ValueError): self.prepare()
            self.bundle[target][key] = old
        self.assertEqual(self.runner.calls, [])

    def test_atomic_active_write_failure_preserves_old_pointer_and_candidate(self):
        self.prepare()
        bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease)
        self.prepare()
        old_active, old_pending = ((self.root / name).read_bytes() for name in ('active.json', 'pending.json'))
        with patch.object(bootstrap.os, 'replace', side_effect=OSError('fixture replace syscall')):
            with self.assertRaises(OSError):
                bootstrap.atomic_json(self.root / 'active.json', {'invalid': 'not committed'})
        self.assertEqual((self.root / 'active.json').read_bytes(), old_active)
        def failed_write(path, value):
            raise OSError('fixture atomic replace failure')
        bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease, write=failed_write)
        self.assertEqual((self.root / 'active.json').read_bytes(), old_active)
        self.assertEqual((self.root / 'pending.json').read_bytes(), old_pending)
        self.assertFalse(list(self.root.glob('.active.json*')))
        error = bootstrap.read_json(self.root / 'last-update-error.json')
        self.assertEqual((error['status'], error['phase'], error['failure']), ('failed', 'precommit', 'OSError'))
        self.assertIn('fixture atomic replace failure', error['message'])
        # A later normal launch does not retry the same failed candidate implicitly.
        bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease)
        self.assertEqual((self.root / 'active.json').read_bytes(), old_active)
        install.request_pending_retry(self.root, lease=self.lease)
        bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease)
        self.assertNotEqual((self.root / 'active.json').read_bytes(), old_active)

    def test_receipt_tamper_and_pointer_escape_do_not_replace_active(self):
        self.prepare()
        bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease)
        pointer = self.prepare()
        old_active = (self.root / 'active.json').read_bytes()
        receipt = self.root / pointer['environment'] / 'ready.json'
        receipt.write_text('{}', encoding='utf-8')
        bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease)
        self.assertIn('receipt', bootstrap.read_json(self.root / 'last-update-error.json')['message'])
        self.assertEqual((self.root / 'active.json').read_bytes(), old_active)
        pointer['environment'] = '../outside'
        bootstrap.atomic_json(self.root / 'pending.json', pointer)
        bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease)
        self.assertIn('pointer', bootstrap.read_json(self.root / 'last-update-error.json')['message'])
        self.assertEqual((self.root / 'active.json').read_bytes(), old_active)

    def test_manual_policy_retains_auto_candidate_explicit_candidate_can_commit(self):
        self.prepare()
        bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease)
        incoming = self.prepare(automatic=True)
        old_active = (self.root / 'active.json').read_bytes()
        install.set_update_policy(self.root, 'MANUAL_UPDATE', lease=self.lease)
        bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease)
        self.assertEqual((self.root / 'active.json').read_bytes(), old_active)
        self.assertEqual(bootstrap.read_json(self.root / 'pending.json'), incoming)
        install.set_update_policy(self.root, 'AUTO_UPDATE', lease=self.lease)
        bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease)
        self.assertEqual(bootstrap.read_json(self.root / 'active.json'), incoming)
        install.set_update_policy(self.root, 'MANUAL_UPDATE', lease=self.lease)
        explicit = self.prepare(automatic=False)
        bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease)
        self.assertEqual(bootstrap.read_json(self.root / 'active.json'), explicit)

    def test_stable_policy_blocks_prerelease_and_initial_failure_is_real_error(self):
        incoming = self.prepare(automatic=True)
        incoming['bundle']['channel'] = 'beta'
        self.assertFalse(bootstrap.automatic_commit_allowed(self.root, incoming))
        install.set_update_policy(self.root, 'AUTO_UPDATE_PRE_RELEASE', lease=self.lease)
        self.assertTrue(bootstrap.automatic_commit_allowed(self.root, incoming))
        incoming['bundle']['channel'] = 'stable'
        pointer = incoming
        (self.root / pointer['environment'] / 'ready.json').write_bytes(b'broken')
        with self.assertRaisesRegex(ValueError, 'receipt'):
            bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease)
        self.assertFalse((self.root / 'active.json').exists())

    def test_commit_cleanup_interruption_is_idempotent_and_does_not_rollback(self):
        pointer = self.prepare()
        pending = self.root / 'pending.json'
        original_unlink = Path.unlink
        def interrupted_unlink(path, *args, **kwargs):
            if path == pending:
                raise OSError('fixture interrupted pending cleanup')
            return original_unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', interrupted_unlink):
            bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease)
        self.assertEqual(bootstrap.read_json(self.root / 'active.json'), pointer)
        self.assertTrue(pending.exists())
        self.assertEqual(bootstrap.read_json(self.root / 'last-update-error.json')['status'], 'committed')
        with patch.object(bootstrap, 'atomic_json', wraps=bootstrap.atomic_json) as writes:
            bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease,
                             write=lambda *args: self.fail('Already committed active was rewritten'))
            self.assertEqual(writes.call_count, 0)
        self.assertFalse(pending.exists())
        self.assertFalse((self.root / 'last-update-error.json').exists())

    def test_concurrent_bootstrap_gate_rejects_second_commit(self):
        pending = self.prepare()
        with self.lease(self.root / '.leases/switch.lock', True):
            with self.assertRaises(bootstrap.LeaseBusy):
                bootstrap.launch(self.root, run=self.launch_runner, lease=self.lease)
        self.assertEqual(bootstrap.read_json(self.root / 'pending.json'), pending)
        self.assertFalse((self.root / 'active.json').exists())


if __name__ == '__main__':
    unittest.main()
