"""CLI forwarding through actual owned children and temporary transport fixtures."""
import json
import os
from pathlib import Path
from queue import Queue, Empty
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]

MANAGEMENT = '''
import json, os, sys
print(json.dumps({'event': 'fixture-ready', 'pid': os.getpid()}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request['command'] == 'stop':
        print(json.dumps({'event': 'fixture-stopped'}), flush=True)
        break
    if request.get('action_id') == 'fail':
        print(json.dumps({'event': 'fixture-failed', 'error': 'management fixture failure'}), flush=True)
        raise SystemExit(7)
    print(json.dumps({'event': 'configuration-response', 'request_id': request['request_id'],
                      'command': request['command'], 'ok': True, 'received': request}), flush=True)
'''

PLUGIN = '''
import os, sys
from pathlib import Path
from queue import Empty

class Package:
    def management_command(self, data_dir):
        return {'command': [sys.executable, '-u', str(Path(__file__).with_name('management.py'))],
                'cwd': str(data_dir), 'env': os.environ.copy()}

    overview_command = management_command

    def run_session(self, task_id, context):
        context.emit('fixture-ready', pid=os.getpid())
        while True:
            try:
                request = context.requests.get(timeout=.05)
            except Empty:
                if context.stop.is_set():
                    context.emit('fixture-stopped')
                    return {}
                continue
            if request.get('action_id') == 'fail':
                raise RuntimeError('session fixture failure')
            context.emit('configuration-response', request_id=request['request_id'],
                         command=request['command'], ok=True, received=request)
'''


class TestGameFrameCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pack = self.root / 'fixture'
        self.pack.mkdir()
        self.data = self.root / 'data'
        self.data.mkdir()
        (self.pack / 'plugin.py').write_text(textwrap.dedent(PLUGIN), encoding='utf-8')
        (self.pack / 'management.py').write_text(textwrap.dedent(MANAGEMENT), encoding='utf-8')
        (self.pack / 'manifest.json').write_text(json.dumps({
            'id': 'cli-fixture', 'title': 'CLI transport fixture', 'version': '1.00.00',
            'api_version': 1, 'entrypoint': 'plugin.py:Package', 'license': 'test',
            'platforms': ['windows'], 'execution': 'native', 'supports_session': True,
            'management': True, 'overview': True, 'tasks': [{'id': 'fixture', 'title': 'Fixture', 'kind': 'one-shot'}],
        }), encoding='utf-8')

    def launch(self, mode):
        command = [sys.executable, '-m', 'gameframe', mode, str(self.pack), '--data-dir', str(self.data)]
        if mode == 'run':
            command += ['--task', 'fixture', '--session', '--device', '{"type":"replay","frames":[]}']
        environment = os.environ.copy()
        environment['PYTHONIOENCODING'] = 'utf-8'
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding='utf-8', env=environment)
        lines = Queue()
        output = []
        def reader():
            for line in process.stdout:
                output.append(line)
                lines.put(line)
            lines.put(None)
        reader_thread = threading.Thread(target=reader, daemon=True)
        reader_thread.start()
        def close():
            if process.poll() is None:
                self.send(process, {'command': 'stop'})
                process.wait(timeout=10)
            reader_thread.join(timeout=3)
            process.stdin.close()
            process.stdout.close()
        self.addCleanup(close)
        self.process, self.lines, self.output = process, lines, output
        ready = self.wait_event(lambda value: value.get('event') == 'fixture-ready')
        self.assertNotEqual(ready['pid'], process.pid)
        return process

    @staticmethod
    def send(process, request):
        process.stdin.write(json.dumps(request, ensure_ascii=False) + '\n')
        process.stdin.flush()

    def wait_event(self, predicate):
        while True:
            try:
                line = self.lines.get(timeout=10)
            except Empty:
                self.fail('CLI child response timed out: ' + ''.join(self.output))
            if line is None:
                self.fail('CLI exited before expected response: ' + ''.join(self.output))
            value = json.loads(line)
            if predicate(value):
                return value

    def verify_forward_and_stop(self, mode, expected_code):
        process = self.launch(mode)
        commands = [
            {'command': 'get-schema', 'request_id': 'schema'},
            {'command': 'set-config', 'request_id': 'save', 'scope': 'task', 'id': 'fixture',
             'values': {'label': '合成配置', 'enabled': True}},
            {'command': 'invoke-action', 'request_id': 'action', 'task_id': 'fixture', 'action_id': 'clear'},
        ]
        for request in commands:
            self.send(process, request)
            response = self.wait_event(lambda value: value.get('request_id') == request['request_id'])
            self.assertEqual(response['received'], request)
            self.assertEqual(response['command'], request['command'])
            self.assertTrue(response['ok'])
        self.send(process, {'command': 'stop'})
        self.wait_event(lambda value: value.get('event') == 'fixture-stopped')
        self.assertEqual(process.wait(timeout=10), expected_code, ''.join(self.output))

    def test_session_forwards_three_configuration_commands_and_stop(self):
        self.verify_forward_and_stop('run', 130)  # Worker explicit cancellation contract.

    def test_management_forwards_three_configuration_commands_and_stop(self):
        self.verify_forward_and_stop('manage', 0)
        self.assertFalse((self.data / 'runs.sqlite').exists())

    def test_session_child_failure_is_not_swallowed(self):
        process = self.launch('run')
        self.send(process, {'command': 'invoke-action', 'request_id': 'failure', 'action_id': 'fail'})
        failure = self.wait_event(lambda value: value.get('event') == 'worker-failed')
        self.assertEqual(failure['error'], 'session fixture failure')
        self.assertEqual(process.wait(timeout=10), 1)

    def test_management_preserves_exact_child_nonzero_exit(self):
        process = self.launch('manage')
        self.send(process, {'command': 'invoke-action', 'request_id': 'failure', 'action_id': 'fail'})
        failure = self.wait_event(lambda value: value.get('event') == 'fixture-failed')
        self.assertEqual(failure['error'], 'management fixture failure')
        self.assertEqual(process.wait(timeout=10), 7)

    def test_overview_stop_and_metadata_version_gate(self):
        from gameframe.packages import PackageManifest
        from gameframe.controller import Controller
        from unittest.mock import patch
        manifest = PackageManifest.read(self.pack)
        self.assertTrue(manifest.overview)
        process = self.launch('overview')
        self.send(process, {'command': 'stop'})
        self.wait_event(lambda value: value.get('event') == 'fixture-stopped')
        self.assertEqual(process.wait(timeout=10), 0)
        self.assertEqual(list(self.data.iterdir()), [])
        value = json.loads((self.pack / 'manifest.json').read_text())
        value['version'] = '1.00.01'
        (self.pack / 'manifest.json').write_text(json.dumps(value))
        with patch.object(PackageManifest, 'load') as load:
            with self.assertRaisesRegex(ValueError, 'version changed'):
                Controller().start_overview(manifest, data_dir=self.data)
            load.assert_not_called()
        value.pop('overview')
        (self.pack / 'manifest.json').write_text(json.dumps(value))
        self.assertFalse(PackageManifest.read(self.pack).overview)


if __name__ == '__main__':
    unittest.main()
