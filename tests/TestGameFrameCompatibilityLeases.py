"""Compatibility bootstrap with genuine local services and temporary main.py only."""

import json
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / 'gamepacks/wuthering_waves/bootstrap.py'
APPLICATION = '''
import json, time
from pathlib import Path
root = Path(__file__).parent
def event(kind):
    print(json.dumps({'event': kind}), flush=True)
def wait_gate(name):
    while not (root / name).exists():
        time.sleep(.01)
def run_application(task=None, stop_event=None):
    import cv2
    from src.evidence.service import get_evidence_service
    from src.runtime import diagnostic_lifecycle
    session = diagnostic_lifecycle.start_diagnostics('fixture', root / 'diagnostics',
                                                     source_root=root, local_only=True)
    evidence = get_evidence_service(root=root / 'evidence')
    def pending_save():
        wait_gate('evidence-gate')
        (root / 'evidence-drained').write_text('saved')
    evidence._pool.submit(pending_save)
    original_close = evidence.close
    def close():
        event('evidence-drain-started')
        original_close()
        event('evidence-drained')
    evidence.close = close
    original_finish = session.finish
    def finish(*args, **kwargs):
        assert kwargs['timeout'] is None
        event('diagnostic-drain-started')
        wait_gate('diagnostic-gate')
        original_finish(*args, **kwargs)
        event('diagnostic-drained')
    session.finish = finish
    event('task-ready')
    stop_event.wait()
    if task == 'FailFixture':
        raise RuntimeError('fixture execution failed')
    return 0
'''
RUNNER = '''
import importlib.util, sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
from src.runtime import diagnostic_lifecycle
spec = importlib.util.spec_from_file_location('fixture_bootstrap', sys.argv[2])
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
sys.argv = [sys.argv[2], *sys.argv[3:]]
with ExitStack() as external:
    spies = [external.enter_context(patch(name, side_effect=AssertionError('external: '+name)))
             for name in ('src.runtime.diagnostic_lifecycle.wake_uploader',
                          'src.runtime.diagnostic_lifecycle.start_automatic_archive_upload',
                          'src.runtime.diagnostic_policy.ensure_task',
                          'src.runtime.diagnostic_policy.connect')]
    try:
        bootstrap.main()
    finally:
        assert diagnostic_lifecycle._session is None
        for spy in spies:
            spy.assert_not_called()
'''
PROBE = '''
import json, sys
sys.path.insert(0, sys.argv[1])
from gameframe.process_locks import package_lease, data_lease, device_input_lease, LeaseUnavailable
kind, value = sys.argv[2], json.loads(sys.argv[3])
lease = (package_lease(value, exclusive=True) if kind == 'package' else
         data_lease(value, exclusive=True) if kind == 'data' else device_input_lease(value))
try:
    with lease: print('acquired')
except LeaseUnavailable:
    print('blocked')
    raise SystemExit(23)
'''


@unittest.skipUnless(os.name == 'nt', 'Compatibility input lease uses the actual Windows desktop')
class TestGameFrameCompatibilityLeases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / 'package'
        self.package.mkdir()
        self.source = self.package / 'payload'
        self.source.mkdir()
        self.bootstrap = self.package / 'bootstrap.py'
        self.bootstrap.write_bytes(BOOTSTRAP.read_bytes())
        (self.package / 'plugin.py').write_text('class Package: pass\n')
        (self.package / 'manifest.json').write_text(json.dumps({
            'api_version': 1, 'id': 'compat-fixture', 'version': '1.00.00',
            'entrypoint': 'plugin.py:Package', 'license': 'test', 'platforms': ['windows'],
            'execution': 'legacy-application', 'tasks': [],
        }))
        (self.source / 'main.py').write_text(textwrap.dedent(APPLICATION), encoding='utf-8')

    def probe(self, kind, value, blocked):
        result = subprocess.run([sys.executable, '-c', textwrap.dedent(PROBE), str(ROOT), kind,
                                 json.dumps(value)], text=True, encoding='utf-8',
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 23 if blocked else 0, result.stdout + result.stderr)

    def verify_drain(self, failed):
        command = [sys.executable, '-u', '-c', textwrap.dedent(RUNNER), str(ROOT), str(self.bootstrap),
                   '--source-root', str(self.source), '--expected-version', '1.00.00']
        if failed:
            command += ['--task-class', 'FailFixture']
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding='utf-8')
        lines, output = Queue(), []
        def read():
            for line in process.stdout:
                lines.put(line)
                output.append(line)
            lines.put(None)
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        def cleanup():
            (self.source / 'evidence-gate').touch()
            (self.source / 'diagnostic-gate').touch()
            if process.poll() is None:
                process.stdin.write('{"command":"stop"}\n')
                process.stdin.flush()
                process.wait(timeout=10)
            reader.join(timeout=2)
            process.stdin.close()
            process.stdout.close()
        self.addCleanup(cleanup)
        def event(expected):
            while True:
                try:
                    line = lines.get(timeout=20)
                except Empty:
                    self.fail('Compatibility fixture timed out: '+''.join(output))
                self.assertIsNotNone(line, ''.join(output))
                if line.startswith('{') and json.loads(line).get('event') == expected:
                    return
        def all_leases(blocked):
            self.probe('package', str(self.package), blocked)
            self.probe('data', str(self.source), blocked)
            self.probe('device', {'type': 'windows'}, blocked)
        event('task-ready')
        self.probe('data', str(self.source), True)
        process.stdin.write('{"command":"stop"}\n')
        process.stdin.flush()
        event('evidence-drain-started')
        all_leases(True)
        (self.source / 'evidence-gate').touch()
        event('evidence-drained')
        event('diagnostic-drain-started')
        all_leases(True)
        (self.source / 'diagnostic-gate').touch()
        event('diagnostic-drained')
        self.assertEqual(process.wait(timeout=10), 1 if failed else 0, ''.join(output))
        reader.join(timeout=2)
        self.assertTrue((self.source / 'evidence-drained').exists())
        if failed:
            self.assertIn('RuntimeError: fixture execution failed', ''.join(output))
        all_leases(False)

    def test_normal_return_drains_real_services_before_releasing_all_leases(self):
        self.verify_drain(False)

    def test_execution_exception_drains_real_services_and_retains_original_failure(self):
        self.verify_drain(True)

    def test_early_import_failure_does_not_import_cleanup_services(self):
        (self.source / 'main.py').write_text("raise RuntimeError('fixture early import failed')\n")
        code = '''
import importlib.abc, runpy, sys
sys.path.insert(0, sys.argv[1])
class BlockCleanup(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ('src.evidence.service', 'src.runtime.diagnostic_lifecycle', 'src.runtime.native_diagnostics'):
            raise AssertionError('cleanup service imported after early failure')
sys.meta_path.insert(0, BlockCleanup())
sys.argv = sys.argv[2:]
runpy.run_path(sys.argv[0], run_name='__main__')
'''
        result = subprocess.run([sys.executable, '-u', '-c', textwrap.dedent(code), str(ROOT),
                                 str(self.bootstrap), '--source-root', str(self.source)],
                                input='', text=True, encoding='utf-8', capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn('RuntimeError: fixture early import failed', result.stderr)
        self.assertNotIn('cleanup service imported', result.stderr)
        self.probe('package', str(self.package), False)
        self.probe('data', str(self.source), False)
        self.probe('device', {'type': 'windows'}, False)

    def test_cold_cli_imports_science_before_blocking_stdin_listener(self):
        (self.source / 'main.py').write_text('''
def run_application(task=None, stop_event=None):
    import numpy
    import cv2
    print('cold-ready', flush=True)
    stop_event.wait()
''', encoding='utf-8')
        code = ('import runpy,sys; sys.path.insert(0,sys.argv[1]); '
                'sys.argv=sys.argv[2:]; runpy.run_path(sys.argv[0],run_name="__main__")')
        process = subprocess.Popen([sys.executable, '-u', '-c', code, str(ROOT), str(self.bootstrap),
                                    '--source-root', str(self.source)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8')
        ready = Queue()
        reader = threading.Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True)
        reader.start()
        def cleanup():
            if process.poll() is None:
                process.communicate(input='{"command":"stop"}\n', timeout=5)
            reader.join(timeout=2)
        self.addCleanup(cleanup)
        self.assertEqual(ready.get(timeout=10), 'cold-ready\n')
        reader.join(timeout=2)
        output, _ = process.communicate(input='{"command":"stop"}\n', timeout=5)
        self.assertEqual(process.returncode, 0, output)


if __name__ == '__main__':
    unittest.main()
