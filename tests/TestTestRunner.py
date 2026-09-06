import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import psutil

from scripts.run_test_file import run_isolated


class TestTestRunner(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_test_file(self, body):
        path = self.root / 'RunnerFixture.py'
        path.write_text('import unittest\n' + body, encoding='utf-8')
        return path

    def test_success_and_skip_counts(self):
        path = self.make_test_file(
            'class Checks(unittest.TestCase):\n'
            '    def test_pass(self): self.assertTrue(True)\n'
            '    @unittest.skip("synthetic missing fixture")\n'
            '    def test_skip(self): pass\n')
        result = run_isolated(path, timeout=15)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['tests_run'], 2)
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(result['exit_code'], 0)

    def test_assertion_failure_is_not_success(self):
        path = self.make_test_file('class Checks(unittest.TestCase):\n'
                              '    def test_fail(self): self.fail("synthetic failure")\n')
        result = run_isolated(path, timeout=15)
        self.assertEqual(result['status'], 'failed')
        self.assertNotEqual(result['exit_code'], 0)

    def test_exit_zero_without_test_result_is_not_success(self):
        path = self.make_test_file('import os\nos._exit(0)\n')
        result = run_isolated(path, timeout=15)
        self.assertEqual(result['status'], 'failed')

    def test_ok_output_followed_by_hanging_exit_times_out(self):
        path = self.make_test_file(
            'import atexit, time\n'
            'atexit.register(lambda: time.sleep(60))\n'
            'class Checks(unittest.TestCase):\n'
            '    def test_pass(self): pass\n')
        result = run_isolated(path, timeout=2)
        self.assertEqual(result['status'], 'timed_out')
        self.assertNotEqual(result['exit_code'], 0)
        self.assertLess(result['elapsed_seconds'], 12)

    def test_spawned_descendant_is_cleaned_without_killing_unrelated_process(self):
        pid_path = self.root / 'child.pid'
        path = self.make_test_file(
            'import subprocess, sys\n'
            'from pathlib import Path\n'
            'class Checks(unittest.TestCase):\n'
            '    def test_child(self):\n'
            '        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
            f'        Path({str(pid_path)!r}).write_text(str(child.pid))\n')
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        try:
            result = run_isolated(path, timeout=15)
            self.assertEqual(result['status'], 'passed')
            child_pid = int(pid_path.read_text())
            if psutil.pid_exists(child_pid):
                psutil.wait_procs([psutil.Process(child_pid)], timeout=5)
            self.assertFalse(psutil.pid_exists(child_pid))
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.kill()
            unrelated.wait(timeout=5)

    def test_cli_writes_machine_readable_result(self):
        path = self.make_test_file('class Checks(unittest.TestCase):\n'
                              '    def test_pass(self): pass\n')
        result_path = self.root / 'result.json'
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/run_test_file.py'),
                   str(path), '--timeout', '15', '--result-file', str(result_path)]
        completed = subprocess.run(command, timeout=20, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors='replace'))
        self.assertEqual(json.loads(result_path.read_text(encoding='utf-8'))['status'], 'passed')


if __name__ == '__main__':
    unittest.main()
