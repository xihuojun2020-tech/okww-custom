"""Production worker lifecycle with real leases and a device that sends no input."""

import json
import io
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
WORKER_FIXTURE = '''
import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from gameframe import worker
marker, close_gate = Path(sys.argv[2]), Path(sys.argv[3])
class FakeDevice:
    capabilities = frozenset()
    def release_all(self):
        worker.emit({'event': 'fixture-input-released'})
    def close(self):
        worker.emit({'event': 'fixture-close-started'})
        while not close_gate.exists():
            time.sleep(.01)
        worker.emit({'event': 'fixture-close-finished'})
def create_device(options):
    marker.write_text(json.dumps(options))
    return FakeDevice()
worker.create_device = create_device
raise SystemExit(worker.main(sys.argv[4:]))
'''
PLUGIN = '''
import time
from pathlib import Path
Path(__file__).with_name('imported.marker').write_text('imported')
class Package:
    def __init__(self):
        self.context = None
    def run(self, task_id, context):
        self.context = context
        context.emit('fixture-task-ready')
        context.stop.wait()
        context.check_stop()
        return {}
    def run_session(self, task_id, context):
        return self.run(task_id, context)
    def close(self):
        if self.context is None:
            return
        gate = self.context.config.get('package_close_gate')
        if gate:
            self.context.emit('fixture-package-close-started')
            while not Path(gate).exists():
                time.sleep(.01)
            self.context.emit('fixture-package-close-finished')
'''
PROBE = '''
import json,sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from gameframe.process_locks import package_lease,data_lease,device_input_lease,LeaseUnavailable
kind = sys.argv[2]
value = json.loads(sys.argv[3])
lease = (device_input_lease(value) if kind == 'device' else
         package_lease(value, exclusive=True) if kind == 'package' else data_lease(value, exclusive=True))
try:
    with lease:
        print('acquired', flush=True)
except LeaseUnavailable:
    print('blocked', flush=True)
    raise SystemExit(23)
'''


@unittest.skipUnless(os.name == 'nt', 'Worker fixture checks the actual Windows station/desktop mutex')
class TestGameFrameWorkerLeases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.script = self.root / 'worker-fixture.py'
        self.script.write_text(textwrap.dedent(WORKER_FIXTURE), encoding='utf-8')

    def package(self, name):
        package = self.root / name
        package.mkdir()
        (package / 'plugin.py').write_text(textwrap.dedent(PLUGIN), encoding='utf-8')
        (package / 'manifest.json').write_text(json.dumps({
            'api_version': 1, 'id': name, 'title': name, 'version': '1.00.00',
            'entrypoint': 'plugin.py:Package', 'license': 'test', 'platforms': ['windows'],
            'execution': 'native', 'supports_session': True,
            'tasks': [{'id': 'fixture', 'title': 'Fixture', 'kind': 'one-shot'}],
        }), encoding='utf-8')
        return package

    def launch(self, package, name, hwnd, expected_version='1.00.00', config=None, session=False):
        data = self.root / (name + '-data')
        data.mkdir()
        marker = self.root / (name + '-factory.json')
        gate = self.root / (name + '-close-gate')
        options = {'type': 'windows', 'hwnd': hwnd}
        command = [sys.executable, '-u', str(self.script), str(ROOT), str(marker), str(gate),
                   '--package', str(package), '--expected-version', expected_version,
                   '--task', 'fixture', '--data-dir', str(data), '--device', json.dumps(options)]
        if config is not None:
            command += ['--config', json.dumps(config)]
        if session:
            command.append('--session')
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding='utf-8')
        events = Queue()
        output = []
        def read():
            for line in process.stdout:
                output.append(line)
                events.put(line)
            events.put(None)
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        def close():
            gate.touch()
            if config and config.get('package_close_gate'):
                Path(config['package_close_gate']).touch()
            if process.poll() is None:
                process.stdin.write('{"command":"stop"}\n')
                process.stdin.flush()
                process.wait(timeout=5)
            reader.join(timeout=2)
            process.stdin.close()
            process.stdout.close()
        self.addCleanup(close)
        def wait_event(kind):
            while True:
                try:
                    line = events.get(timeout=5)
                except Empty:
                    self.fail('Worker fixture timed out: ' + ''.join(output))
                self.assertIsNotNone(line, ''.join(output))
                value = json.loads(line)
                if value['event'] == kind:
                    return value
        return process, wait_event, marker, gate, data, options

    def probe(self, kind, value, blocked):
        result = subprocess.run([sys.executable, '-c', textwrap.dedent(PROBE), str(ROOT), kind,
                                 json.dumps(value)], text=True, encoding='utf-8',
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 23 if blocked else 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), 'blocked' if blocked else 'acquired')

    def test_workers_share_one_desktop_and_hold_all_leases_through_device_close(self):
        first_pack = self.package('first-package')
        first, event, factory, gate, data, device = self.launch(first_pack, 'first', 101, session=True)
        event('fixture-task-ready')
        self.assertEqual(json.loads(factory.read_text()), device)
        second_pack = self.package('second-package')
        second, second_event, second_factory, _, _, _ = self.launch(second_pack, 'second', 303, session=True)
        failure = second_event('worker-failed')
        self.assertEqual(failure['type'], 'LeaseUnavailable')
        self.assertEqual(second.wait(timeout=5), 1)
        self.assertFalse(second_factory.exists(), 'Contending worker constructed a device before refusing input')
        first.stdin.write('{"command":"stop"}\n')
        first.stdin.flush()
        event('fixture-close-started')
        self.assertIsNone(first.poll())
        self.probe('package', str(first_pack), blocked=True)
        self.probe('data', str(data), blocked=True)
        self.probe('device', {'type': 'windows', 'hwnd': 505}, blocked=True)
        gate.touch()
        event('fixture-close-finished')
        self.assertEqual(first.wait(timeout=5), 130)
        self.probe('package', str(first_pack), blocked=False)
        self.probe('data', str(data), blocked=False)
        self.probe('device', {'type': 'windows', 'hwnd': 505}, blocked=False)

    def test_stale_expected_version_fails_before_package_import_or_device_factory(self):
        package = self.package('stale-package')
        process, event, marker, _, data, _ = self.launch(package, 'stale', 707, expected_version='1.00.01')
        failure = event('worker-failed')
        self.assertEqual(failure['type'], 'ValueError')
        self.assertEqual(failure['error'], 'Gamepack version changed before the worker started')
        self.assertEqual(process.wait(timeout=5), 1)
        self.assertFalse(marker.exists())
        self.assertFalse((package / 'imported.marker').exists())
        self.assertFalse((data / 'runs.sqlite').exists())

    def test_package_drain_holds_all_leases_after_device_cleanup(self):
        package = self.package('drain-package')
        drain_gate = self.root / 'package-drain-gate'
        process, event, _, device_gate, data, _ = self.launch(
            package, 'drain', 808, config={'package_close_gate': str(drain_gate)})
        event('fixture-task-ready')
        device_gate.touch()
        process.stdin.write('{"command":"stop"}\n')
        process.stdin.flush()
        event('fixture-close-finished')
        event('fixture-package-close-started')
        self.assertIsNone(process.poll())
        self.probe('package', str(package), blocked=True)
        self.probe('data', str(data), blocked=True)
        self.probe('device', {'type': 'windows'}, blocked=True)
        drain_gate.touch()
        event('fixture-package-close-finished')
        self.assertEqual(process.wait(timeout=5), 130)
        self.probe('package', str(package), blocked=False)
        self.probe('data', str(data), blocked=False)
        self.probe('device', {'type': 'windows'}, blocked=False)

    def test_device_cleanup_error_preserves_exception_and_still_drains_package_store_and_leases(self):
        from gameframe import worker
        package_root = self.package('cleanup-error-package')
        data = self.root / 'cleanup-error-data'
        data.mkdir()
        failure = RuntimeError('fixture device close failed')
        device = Mock()
        device.close.side_effect = failure
        package = SimpleNamespace(close=Mock())
        manifest = SimpleNamespace(version='1.00.00', execution='native',
                                   task=lambda identifier: SimpleNamespace(id=identifier, kind='one-shot'),
                                   load=lambda: package)
        store = Mock()
        with patch.object(worker.PackageManifest, 'read', return_value=manifest), \
             patch.object(worker, 'create_device', return_value=device), \
             patch.object(worker, 'RunStore', return_value=store), \
             patch.object(worker, 'Runtime') as runtime, patch.object(worker, 'emit') as emit, \
             patch.object(sys, 'stdin', io.StringIO('')):
            with self.assertRaises(RuntimeError) as raised:
                worker.main(['--package', str(package_root), '--task', 'fixture',
                             '--data-dir', str(data), '--device', '{"type":"windows"}'])
        runtime.return_value.run.assert_called_once()
        emit.assert_not_called()
        self.assertIs(raised.exception, failure)
        device.close.assert_called_once_with()
        package.close.assert_called_once_with()
        store.close.assert_called_once_with()
        self.probe('package', str(package_root), blocked=False)
        self.probe('data', str(data), blocked=False)
        self.probe('device', {'type': 'windows'}, blocked=False)


if __name__ == '__main__':
    unittest.main()
