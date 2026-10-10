"""A real, device-free management module proves the process lease boundary."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from gameframe.process_locks import LeaseUnavailable, package_lease


ROOT = Path(__file__).resolve().parents[1]


class TestGameFramePackageProcess(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root / 'packages' / 'fixture'
        self.package.mkdir(parents=True)
        (self.package / 'manifest.json').write_text(json.dumps({
            'api_version': 1, 'id': 'fixture', 'version': '1.97.68',
            'entrypoint': 'plugin.py:Package', 'license': 'MIT',
            'platforms': ['offline'], 'tasks': [], 'management': True}), encoding='utf-8')
        (self.package / 'plugin.py').write_text('class Package: pass\n', encoding='utf-8')
        self.sentinel = self.root / 'imported'
        (self.root / 'fixture_manager.py').write_text('''
import json
from pathlib import Path
import sys
sentinel = Path(sys.argv[2])
sentinel.write_text('imported', encoding='utf-8')
print('importing', flush=True)
sys.stdin.readline()
sentinel.with_suffix('.running').write_text('running', encoding='utf-8')
print('running', flush=True)
if sys.argv[1] == 'exit':
    raise SystemExit(7)
for line in sys.stdin:
    if json.loads(line)['command'] == 'stop':
        break
''', encoding='utf-8')

    def start(self, *, version='1.97.68', mode='stop'):
        code = (f'import sys, runpy; sys.path[:0] = [{str(ROOT)!r}, {str(self.root)!r}]; '
                'runpy.run_module("gameframe.package_process", run_name="__main__")')
        process = subprocess.Popen([
            sys.executable, '-I', '-X', 'utf8', '-u', '-c', code,
            '--package', str(self.package), '--expected-version', version,
            '--module', 'fixture_manager', '--', mode, str(self.sentinel)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8')
        self.addCleanup(self.cleanup_process, process)
        return process

    @staticmethod
    def cleanup_process(process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)

    def send(self, process, message):
        process.stdin.write(message + '\n')
        process.stdin.flush()

    def importing(self, process):
        self.assertEqual(process.stdout.readline().strip(), 'importing')
        self.assertEqual(self.sentinel.read_text(encoding='utf-8'), 'imported')
        with self.assertRaises(LeaseUnavailable):
            with package_lease(self.package, exclusive=True):
                self.fail('module import must hold the shared package lease')

    def assert_released(self):
        with package_lease(self.package, exclusive=True):
            pass

    def test_import_and_runtime_are_leased_until_stdin_stop(self):
        process = self.start()
        self.importing(process)
        self.send(process, 'continue')
        self.assertEqual(process.stdout.readline().strip(), 'running')
        self.assertTrue(self.sentinel.with_suffix('.running').is_file())
        with self.assertRaises(LeaseUnavailable):
            with package_lease(self.package, exclusive=True):
                self.fail('running management module must retain its lease')
        self.send(process, json.dumps({'command': 'stop'}))
        output, error = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 0, output + error)
        self.assert_released()

    def test_module_system_exit_retains_nonzero_code_and_releases(self):
        process = self.start(mode='exit')
        self.importing(process)
        self.send(process, 'continue')
        output, error = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 7, output + error)
        self.assertIn('running', output)
        self.assert_released()

    def test_stale_version_rejects_before_module_import(self):
        process = self.start(version='1.97.67')
        output, error = process.communicate(timeout=15)
        self.assertNotEqual(process.returncode, 0, output + error)
        self.assertIn('version changed before the process started', error)
        self.assertFalse(self.sentinel.exists())
        self.assert_released()

    def test_exclusive_owner_rejects_before_module_import(self):
        with package_lease(self.package, exclusive=True):
            process = self.start()
            output, error = process.communicate(timeout=15)
            self.assertNotEqual(process.returncode, 0, output + error)
            self.assertIn('LeaseUnavailable', error)
            self.assertFalse(self.sentinel.exists())
        self.assert_released()


if __name__ == '__main__':
    unittest.main()
