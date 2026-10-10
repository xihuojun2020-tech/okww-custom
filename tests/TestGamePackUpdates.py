"""Indexed temporary gamepacks exercise actual swaps without loading game code."""

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from gameframe.controller import Controller
from gameframe.package_updates import apply_update, prepare_update, recover_updates
from gameframe.packages import PackageManifest, discover, install_archive
from gameframe.state import RunStore


class Interrupted(BaseException):
    pass


class TestGamePackUpdates(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.packages = self.root / 'packages'
        self.data = self.root / 'data'
        self.data.mkdir()
        (self.data / 'accounts.json').write_text('{"private":"unchanged"}', encoding='utf-8')
        store = RunStore(self.data / 'runs.sqlite')
        store.set_enabled('probe', 'service', True)
        store.close()
        self.data_snapshot = self.snapshot(self.data)
        install_archive(self.archive('1'), self.packages)
        self.old_snapshot = self.snapshot(self.packages / 'probe')

    def tearDown(self):
        self.temporary.cleanup()

    def snapshot(self, root):
        return {path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob('*') if path.is_file()}

    def archive(self, version='2', *, package_id='probe', index=True, corrupt=False, extra=None,
                requirements=b'unchanged==1\n'):
        manifest = {'api_version': 1, 'id': package_id, 'version': version, 'title': 'Probe',
                    'entrypoint': 'plugin.py:create_package', 'license': 'MIT',
                    'platforms': ['offline'], 'tasks': []}
        files = {'manifest.json': json.dumps(manifest).encode(),
                 'plugin.py': b'raise AssertionError("update must never import game code")\n',
                 'version.txt': version.encode(), 'requirements.txt': requirements}
        archive = self.root / (package_id + '-' + version + '.zip')
        with zipfile.ZipFile(archive, 'w') as output:
            for name, contents in files.items():
                output.writestr('bundle/' + name, contents)
            if index:
                hashes = {name: hashlib.sha256(contents).hexdigest() for name, contents in files.items()}
                output.writestr('bundle/files.json', json.dumps({} if corrupt else hashes))
            if extra:
                output.writestr(extra, b'outside')
        return archive

    def prepare(self, **options):
        return prepare_update(self.archive(**options), self.packages,
                              package_id='probe', current_version='1', target_version='2')

    def assert_old_and_private(self):
        self.assertEqual(self.snapshot(self.packages / 'probe'), self.old_snapshot)
        self.assertEqual(self.snapshot(self.data), self.data_snapshot)

    def test_successful_update_is_metadata_only_and_preserves_private_data(self):
        plan = self.prepare()
        self.assert_old_and_private()
        self.assertEqual([(item.id, item.version) for item in discover(self.packages)], [('probe', '1')])
        manifest = apply_update(plan, ensure_idle=lambda: None)
        self.assertEqual((manifest.id, manifest.version), ('probe', '2'))
        self.assertEqual(self.snapshot(self.data), self.data_snapshot)
        self.assertFalse(plan.transaction.exists())
        self.assertEqual([item.version for item in discover(self.packages)], ['2'])

    def test_archive_contract_rejections_leave_old_package_intact(self):
        for options in ({'package_id': 'other'}, {'version': '3'}, {'index': False},
                        {'corrupt': True}, {'extra': '../escape.txt'}, {'requirements': b'changed==2\n'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.prepare(**options)
            self.assert_old_and_private()
            self.assertFalse((self.packages / 'escape.txt').exists())
            self.assertEqual(list((self.packages / '.gameframe-transactions').iterdir()), [])

    def test_unindexed_source_checkout_is_not_an_update_target(self):
        (self.packages / 'probe/files.json').unlink()
        with self.assertRaisesRegex(ValueError, 'source checkout'):
            self.prepare()
        self.assertEqual(PackageManifest.read(self.packages / 'probe').version, '1')

    def test_dependency_whitespace_and_comments_do_not_require_environment_upgrade(self):
        plan = self.prepare(requirements=b'\xef\xbb\xbf# new explanatory comment\n\n  unchanged==1  \r\n')
        self.assertEqual(apply_update(plan, ensure_idle=lambda: None).version, '2')

    def test_manifest_visibility_defaults_and_boolean_contract(self):
        path = self.packages / 'probe/manifest.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        value['tasks'] = [{'id': 'hidden', 'title': 'Helper', 'kind': 'one-shot', 'visible': False},
                          {'id': 'normal', 'title': 'Normal', 'kind': 'one-shot'}]
        path.write_text(json.dumps(value), encoding='utf-8')
        self.assertEqual([task.visible for task in PackageManifest.read(path.parent).tasks], [False, True])
        value['tasks'][0]['visible'] = 'false'
        path.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'visible must be a boolean'):
            PackageManifest.read(path.parent)

    def test_both_owned_processes_must_exit_and_final_gate_is_rechecked(self):
        worker, management = Controller(), Controller()
        worker.process = SimpleNamespace(poll=lambda: None)
        management.process = SimpleNamespace(poll=lambda: None)
        def ensure_idle():
            worker.assert_idle()
            management.assert_idle()
        plan = self.prepare()
        with self.assertRaisesRegex(RuntimeError, 'still running'):
            apply_update(plan, ensure_idle=ensure_idle)
        worker.process = None
        with self.assertRaisesRegex(RuntimeError, 'still running'):
            apply_update(plan, ensure_idle=ensure_idle)
        self.assert_old_and_private()
        management.process = None
        self.assertEqual(apply_update(plan, ensure_idle=ensure_idle).version, '2')

    def test_owner_becoming_active_at_final_gate_rolls_back_before_rename(self):
        plan = self.prepare()
        calls = []
        def ensure_idle():
            calls.append(True)
            if len(calls) == 2:
                raise RuntimeError('owner started')
        with self.assertRaisesRegex(RuntimeError, 'owner started'):
            apply_update(plan, ensure_idle=ensure_idle)
        self.assert_old_and_private()
        self.assertFalse(plan.transaction.exists())

    def test_ordinary_swap_failures_restore_old_tree(self):
        for stage in ('after_old_rename', 'after_new_rename', 'before_commit'):
            with self.subTest(stage=stage):
                plan = self.prepare()
                def fault(current):
                    if current == stage:
                        raise RuntimeError(stage)
                with self.assertRaisesRegex(RuntimeError, stage):
                    apply_update(plan, ensure_idle=lambda: None, fault_hook=fault)
                self.assert_old_and_private()
                self.assertFalse(plan.transaction.exists())

    def test_interrupted_swaps_recover_old_tree_and_recovery_requires_idle(self):
        for stage in ('after_old_rename', 'after_new_rename', 'before_commit'):
            with self.subTest(stage=stage):
                plan = self.prepare()
                def fault(current):
                    if current == stage:
                        raise Interrupted(stage)
                with self.assertRaises(Interrupted):
                    apply_update(plan, ensure_idle=lambda: None, fault_hook=fault)
                before = self.snapshot(self.packages)
                def active():
                    raise RuntimeError('management active')
                with self.assertRaisesRegex(RuntimeError, 'management active'):
                    recover_updates(self.packages, ensure_idle=active)
                self.assertEqual(self.snapshot(self.packages), before)
                outcomes = recover_updates(self.packages, ensure_idle=lambda: None)
                self.assertEqual([item.status for item in outcomes], ['rolled_back'])
                self.assert_old_and_private()
                self.assertEqual(recover_updates(self.packages, ensure_idle=lambda: None), ())

    def test_committed_interruption_retains_new_tree_and_prepared_is_not_auto_applied(self):
        plan = self.prepare()
        pending = recover_updates(self.packages, ensure_idle=lambda: None)
        self.assertEqual([(item.plan, item.status) for item in pending], [(plan, 'prepared')])
        self.assert_old_and_private()
        def fault(stage):
            if stage == 'after_commit':
                raise Interrupted()
        with self.assertRaises(Interrupted):
            apply_update(plan, ensure_idle=lambda: None, fault_hook=fault)
        self.assertEqual([item.status for item in recover_updates(self.packages, ensure_idle=lambda: None)],
                         ['committed'])
        self.assertEqual(PackageManifest.read(plan.installed).version, '2')
        self.assertEqual(self.snapshot(self.data), self.data_snapshot)
        self.assertFalse(plan.transaction.exists())

    def test_interrupted_rollback_is_itself_recoverable(self):
        plan = self.prepare()
        original = Path.rename
        def rename(path, target):
            if path == plan.transaction / 'previous':
                raise Interrupted('rollback interrupted')
            return original(path, target)
        def fault(stage):
            if stage == 'after_new_rename':
                raise RuntimeError('start rollback')
        with patch.object(Path, 'rename', rename), self.assertRaises(Interrupted):
            apply_update(plan, ensure_idle=lambda: None, fault_hook=fault)
        self.assertFalse(plan.installed.exists())
        recover_updates(self.packages, ensure_idle=lambda: None)
        self.assert_old_and_private()

    def test_staging_tamper_or_changed_current_version_is_rejected(self):
        plan = self.prepare()
        (plan.transaction / 'incoming/version.txt').write_text('tampered', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            apply_update(plan, ensure_idle=lambda: None)
        self.assert_old_and_private()
        with self.assertRaisesRegex(ValueError, 'ID/version'):
            prepare_update(self.archive(), self.packages, package_id='probe',
                           current_version='0', target_version='2')


if __name__ == '__main__':
    unittest.main()
