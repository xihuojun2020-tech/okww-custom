"""Real fixture processes contend for package code; no game or network access."""

from pathlib import Path
import subprocess
import sys
import unittest

from gameframe.package_updates import apply_update, recover_updates
from gameframe.packages import PackageManifest
from gameframe.process_locks import LeaseUnavailable
from tests import TestGamePackUpdates as fixtures


ROOT = Path(__file__).resolve().parents[1]


class TestGameFramePackageLeases(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.TestGamePackUpdates()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def child(self, source, *arguments):
        code = f'import sys; sys.path.insert(0, {str(ROOT)!r})\n' + source
        process = subprocess.Popen([sys.executable, '-I', '-X', 'utf8', '-u', '-c', code,
                                    *map(str, arguments)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   encoding='utf-8')
        self.addCleanup(self.stop_child, process)
        return process

    @staticmethod
    def stop_child(process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)

    def ready(self, process):
        self.assertEqual(process.stdout.readline().strip(), 'ready')

    def release(self, process):
        process.stdin.write('\n')
        process.stdin.flush()

    def finish(self, process):
        output, error = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 0, error)
        return output.strip()

    def shared_owner(self):
        process = self.child('''
from gameframe.process_locks import package_lease
with package_lease(sys.argv[1]):
    print('ready', flush=True)
    sys.stdin.readline()
''', self.fixture.packages / 'probe')
        self.ready(process)
        return process

    def test_two_shared_owners_block_apply_and_allow_prepared_read(self):
        f = self.fixture
        owners = [self.shared_owner(), self.shared_owner()]
        plan = f.prepare()
        self.assertEqual([outcome.status for outcome in recover_updates(
            f.packages, ensure_idle=lambda: self.fail('prepared recovery must be read-only'))],
            ['prepared'])
        for owner in owners:
            with self.assertRaises(LeaseUnavailable):
                apply_update(plan, ensure_idle=lambda: self.fail('must lock before owner check'))
            f.assert_old_and_private()
            self.release(owner)
            self.finish(owner)
        self.assertEqual(apply_update(plan, ensure_idle=lambda: None).version, '2')
        self.assertEqual(f.snapshot(f.data), f.data_snapshot)

    def test_exclusive_owner_blocks_prepare_before_staging(self):
        f = self.fixture
        owner = self.child('''
from gameframe.process_locks import package_lease
with package_lease(sys.argv[1], exclusive=True):
    print('ready', flush=True)
    sys.stdin.readline()
''', f.packages / 'probe')
        self.ready(owner)
        with self.assertRaises(LeaseUnavailable):
            f.prepare()
        f.assert_old_and_private()
        self.assertFalse((f.packages / '.gameframe-transactions').exists())
        self.release(owner)
        self.finish(owner)

    def test_interrupted_recovery_requires_exclusive_lease(self):
        f = self.fixture
        plan = f.prepare()
        def interrupt(stage):
            if stage == 'after_new_rename':
                raise fixtures.Interrupted()
        with self.assertRaises(fixtures.Interrupted):
            apply_update(plan, ensure_idle=lambda: None, fault_hook=interrupt)
        before = f.snapshot(f.packages)
        owner = self.shared_owner()
        with self.assertRaises(LeaseUnavailable):
            recover_updates(f.packages, ensure_idle=lambda: self.fail('must lock first'))
        self.assertEqual(f.snapshot(f.packages), before)
        self.release(owner)
        self.finish(owner)
        self.assertEqual([item.status for item in recover_updates(
            f.packages, ensure_idle=lambda: None)], ['rolled_back'])
        f.assert_old_and_private()

    def test_two_updater_processes_only_one_can_replace_current_version(self):
        f = self.fixture
        plans = [f.prepare(), f.prepare()]
        source = '''
from pathlib import Path
from gameframe.package_updates import PreparedUpdate, apply_update
plan = PreparedUpdate(Path(sys.argv[1]), 'probe', '1', '2')
print('ready', flush=True)
sys.stdin.readline()
def overlap(stage):
    if stage == 'after_old_rename':
        print('switching', flush=True)
        sys.stdin.readline()
def attempt():
    try:
        result = apply_update(plan, ensure_idle=lambda: None,
                              fault_hook=overlap if sys.argv[2] == 'first' else None)
        print('success:' + result.version, flush=True)
    except Exception as error:
        print(type(error).__name__ + ':' + str(error), flush=True)
attempt()
if sys.argv[2] == 'second':
    sys.stdin.readline()
    attempt()
'''
        children = [self.child(source, plan.transaction, role)
                    for plan, role in zip(plans, ('first', 'second'))]
        for child in children:
            self.ready(child)
        self.release(children[0])
        self.assertEqual(children[0].stdout.readline().strip(), 'switching')
        self.release(children[1])
        self.assertTrue(children[1].stdout.readline().startswith('LeaseUnavailable:'))
        self.assertEqual(f.snapshot(f.data), f.data_snapshot)
        self.release(children[0])
        self.assertEqual(self.finish(children[0]), 'success:2')
        # Retrying the second old-version plan after release must not overwrite the winner.
        self.release(children[1])
        self.assertIn('ValueError:Gamepack ID/version', self.finish(children[1]))
        self.assertEqual(PackageManifest.read(f.packages / 'probe').version, '2')
        self.assertEqual(f.snapshot(f.data), f.data_snapshot)

    def test_concurrent_install_processes_only_one_publishes(self):
        f = self.fixture
        archive = f.archive(package_id='fresh')
        source = '''
from pathlib import Path
from unittest.mock import patch
from gameframe import packages
extract = packages.extract_archive
def barrier(*args, **kwargs):
    manifest = extract(*args, **kwargs)
    print('ready', flush=True)
    sys.stdin.readline()
    return manifest
try:
    with patch.object(packages, 'extract_archive', barrier):
        manifest = packages.install_archive(sys.argv[1], sys.argv[2])
    print('success:' + manifest.id)
except Exception as error:
    print(type(error).__name__ + ':' + str(error))
'''
        children = [self.child(source, archive, f.packages) for _ in range(2)]
        for child in children:
            self.ready(child)
        for child in children:
            self.release(child)
        outputs = [self.finish(child) for child in children]
        self.assertEqual(outputs.count('success:fresh'), 1, outputs)
        self.assertTrue(any(output.startswith(('LeaseUnavailable:', 'FileExistsError:'))
                            for output in outputs), outputs)
        self.assertEqual(PackageManifest.read(f.packages / 'fresh').version, '2')
        f.assert_old_and_private()


if __name__ == '__main__':
    unittest.main()
