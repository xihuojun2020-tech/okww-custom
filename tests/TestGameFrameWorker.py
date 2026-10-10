import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
import psutil

from gameframe.controller import Controller
from gameframe.packages import PackageManifest
from gameframe.state import RunStore

ROOT = Path(__file__).resolve().parents[1]


class TestGameFrameWorker(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.controller = Controller()
        self.manifest = PackageManifest.read(ROOT / 'examples/vision_probe')
        template = np.random.default_rng(75).integers(10, 240, (6, 7, 3), dtype=np.uint8)
        image = np.zeros((20, 25, 3), dtype=np.uint8)
        image[8:14, 11:18] = template
        cv2.imwrite(str(self.root / 'needle.png'), template)
        cv2.imwrite(str(self.root / 'frame.png'), image)

    def tearDown(self):
        self.controller.close()
        self.temp.cleanup()

    def start(self, frames=None):
        return self.controller.start(self.manifest, 'find-template', data_dir=self.root,
                                     device={'type': 'replay', 'frames': frames if frames is not None
                                             else [str(self.root / 'frame.png')]},
                                     config={'template': str(self.root / 'needle.png')})

    def test_worker_image_action_and_persisted_result(self):
        process = self.start()
        output, _ = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 0, output)
        events = [json.loads(line) for line in output.splitlines()]
        self.assertEqual(events[-1]['status'], 'success')
        actions = json.loads((self.root / 'actions.json').read_text())
        self.assertEqual(actions, [{'kind': 'click', 'values': {'x': 14, 'y': 11}}])
        store = RunStore(self.root / 'runs.sqlite')
        try:
            self.assertEqual(store.history()[0]['details']['position'], [11, 8])
        finally:
            store.close()

    def test_failed_capture_returns_nonzero_and_failure_event(self):
        process = self.start(frames=[])
        output, _ = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 1)
        events = [json.loads(line) for line in output.splitlines()]
        self.assertEqual(events[-1]['event'], 'worker-failed')
        self.assertEqual(events[-1]['type'], 'TimeoutError')

    def make_waiting_package(self):
        pack = self.root / 'waiting'
        pack.mkdir()
        value = {'id': 'waiting', 'version': '1', 'api_version': 1, 'entrypoint': 'plugin.py:create_package',
                 'license': 'MIT', 'platforms': ['offline'], 'tasks': [
                     {'id': 'wait', 'title': 'Wait', 'kind': 'one-shot', 'default_config': {},
                      'required_capabilities': ['keyboard']}]}
        (pack / 'manifest.json').write_text(json.dumps(value))
        (pack / 'plugin.py').write_text(
            'class Package:\n'
            '    def run(self, task_id, context):\n'
            '        context.act("key_down", key="W")\n'
            '        context.emit("waiting")\n'
            '        context.sleep(30)\n'
            '        return {}\n'
            'def create_package(): return Package()\n')
        return PackageManifest.read(pack)

    def test_stop_only_owned_worker_and_records_cancelled(self):
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            process = self.controller.start(self.make_waiting_package(), 'wait',
                                           data_dir=self.root, device={'type': 'replay', 'frames': []})
            self.assertEqual(json.loads(process.stdout.readline())['event'], 'started')
            self.assertEqual(json.loads(process.stdout.readline())['event'], 'waiting')
            with self.assertRaisesRegex(RuntimeError, 'already running'):
                self.start()
            self.controller.stop()
            self.assertEqual(process.returncode, 130)
            self.assertIsNone(unrelated.poll())
            store = RunStore(self.root / 'runs.sqlite')
            try:
                self.assertEqual(store.history()[0]['status'], 'cancelled')
            finally:
                store.close()
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=5)

    def test_pause_resume_keeps_worker_alive_and_stop_remains_effective(self):
        process = self.controller.start(self.make_waiting_package(), 'wait',
                                       data_dir=self.root, device={'type': 'replay', 'frames': []})
        self.assertEqual(json.loads(process.stdout.readline())['event'], 'started')
        self.assertEqual(json.loads(process.stdout.readline())['event'], 'waiting')
        self.controller.pause()
        paused = json.loads(process.stdout.readline())
        self.assertEqual((paused['event'], paused['paused']), ('task-paused', True))
        self.assertIsNone(process.poll())
        self.controller.resume()
        resumed = json.loads(process.stdout.readline())
        self.assertEqual((resumed['event'], resumed['paused']), ('task-paused', False))
        self.controller.pause()
        self.assertTrue(json.loads(process.stdout.readline())['paused'])
        self.controller.stop()
        self.assertEqual(process.returncode, 130)
        store = RunStore(self.root / 'runs.sqlite')
        try:
            self.assertEqual(store.history()[0]['status'], 'cancelled')
        finally:
            store.close()

    def test_shared_session_delivers_task_and_service_requests_to_one_worker(self):
        pack = self.root / 'session'
        pack.mkdir()
        metadata = json.loads((self.manifest.root / 'manifest.json').read_text(encoding='utf-8'))
        metadata['id'] = 'session'
        metadata['supports_session'] = True
        (pack / 'manifest.json').write_text(json.dumps(metadata))
        source = (self.manifest.root / 'plugin.py').read_text(encoding='utf-8')
        source += '''
class SessionPackage(VisionProbe):
    def run_session(self, task_id, context):
        context.emit('session-ready', result=self.run(task_id, context))
        while True:
            context.check_stop()
            if context.requests.empty():
                context.sleep(.01)
                continue
            request = context.requests.get_nowait()
            if request['command'] == 'run-task':
                context.config.update(request['config'])
                result = self.run(request['task_id'], context)
                context.emit('session-result', result=result)
            elif request['command'] == 'reload-user-tasks':
                context.emit('user-tasks-reloaded', applied_revision='fixture-revision')
            elif request['command'] == 'reload-character-code':
                context.emit('character-code-reloaded', applied_character_revision='character-revision')
            else:
                context.emit('service-request', enabled=request['enabled'])
def create_package(): return SessionPackage()
'''
        (pack / 'plugin.py').write_text(source)
        manifest = PackageManifest.read(pack)
        process = self.controller.start(manifest, 'find-template', data_dir=self.root,
                                        config={'template': str(self.root / 'needle.png')},
                                        device={'type': 'replay', 'frames': [str(self.root / 'frame.png')] * 3},
                                        session=True)
        self.assertEqual(json.loads(process.stdout.readline())['event'], 'started')
        self.assertEqual(json.loads(process.stdout.readline())['event'], 'session-ready')
        self.controller.request_user_task_reload()
        self.assertEqual(json.loads(process.stdout.readline())['event'], 'user-tasks-reloaded')
        self.controller.request_character_reload()
        character_event = json.loads(process.stdout.readline())
        self.assertEqual(character_event['event'], 'character-code-reloaded')
        self.assertEqual(character_event['applied_character_revision'], 'character-revision')
        self.controller.set_service('any-service', False)
        service = json.loads(process.stdout.readline())
        self.assertEqual((service['event'], service['enabled']), ('service-request', False))
        self.controller.request_task('find-template', {'template': str(self.root / 'needle.png')})
        event = json.loads(process.stdout.readline())
        self.assertEqual(event['event'], 'session-result')
        self.assertEqual(event['result']['position'], [11, 8])
        self.assertIsNone(process.poll())
        self.controller.stop()
        self.assertEqual(process.returncode, 130)

    def test_inspect_does_not_import_a_game_entrypoint(self):
        pack = self.root / 'metadata'
        pack.mkdir()
        value = json.loads((self.manifest.root / 'manifest.json').read_text(encoding='utf-8'))
        (pack / 'manifest.json').write_text(json.dumps(value))
        (pack / 'plugin.py').write_text('raise AssertionError("metadata imported executable code")')
        result = subprocess.run([sys.executable, '-m', 'gameframe', 'inspect', str(pack)],
                                cwd=ROOT, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['id'], 'vision-probe')

    def test_core_import_does_not_import_legacy_or_device_libraries(self):
        command = ('import sys; import gameframe.worker; import gameframe.controller; '
                   'assert not any(n == "ok" or n.startswith("ok.") or '
                   'n.startswith("src.") or n == "windows_capture" or '
                   'n == "gameframe.devices.mumu" for n in sys.modules)')
        result = subprocess.run([sys.executable, '-c', command], cwd=ROOT,
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_external_config_is_rejected_before_process_start(self):
        with self.assertRaisesRegex(ValueError, 'JSON object'):
            self.controller.start(self.manifest, 'find-template', data_dir=self.root,
                                  config=[], device={'type': 'replay', 'frames': []})
        self.assertIsNone(self.controller.process)

    def test_failed_package_preparation_prevents_device_creation(self):
        from unittest.mock import patch
        from gameframe.worker import main
        manifest = self.make_waiting_package()
        (manifest.root / 'plugin.py').write_text(
            'class Package:\n'
            '    def prepare(self, task_id, data_dir):\n'
            '        raise RuntimeError("account integrity rejected")\n'
            'def create_package(): return Package()\n')
        with patch('gameframe.worker.create_device') as factory, \
                patch('gameframe.worker.threading.Thread'), \
                patch('gameframe.worker.emit') as events:
            result = main(['--package', str(manifest.root), '--task', 'wait',
                           '--data-dir', str(self.root), '--device', '{"type":"replay","frames":[]}'])
        self.assertEqual(result, 1)
        factory.assert_not_called()
        self.assertEqual(events.call_args.args[0],
                         {'event': 'worker-failed', 'type': 'RuntimeError',
                          'error': 'account integrity rejected'})

    def test_successful_package_preparation_runs_before_device_factory(self):
        from unittest.mock import patch
        from gameframe.worker import main
        manifest = self.make_waiting_package()
        (manifest.root / 'plugin.py').write_text(
            'from pathlib import Path\n'
            'class Package:\n'
            '    def prepare(self, task_id, data_dir):\n'
            '        (data_dir / "prepared.txt").write_text(task_id)\n'
            '    def run(self, task_id, context): return {}\n'
            'def create_package(): return Package()\n')
        from gameframe.devices.replay import ReplayDevice
        def create(options):
            self.assertEqual((self.root / 'prepared.txt').read_text(), 'wait')
            return ReplayDevice([])
        with patch('gameframe.worker.create_device', side_effect=create), \
                patch('gameframe.worker.threading.Thread'), patch('gameframe.worker.emit'):
            self.assertEqual(main(['--package', str(manifest.root), '--task', 'wait',
                                   '--data-dir', str(self.root), '--device', '{"type":"replay","frames":[]}']), 0)

    def test_relative_data_directory_is_resolved_in_callers_directory(self):
        from unittest.mock import patch
        with patch('gameframe.controller.subprocess.Popen') as popen, \
                patch('gameframe.controller.psutil.Process'):
            self.controller.start(self.manifest, 'find-template', data_dir=Path('relative-state'),
                                  device={'type': 'replay', 'frames': []})
            command = popen.call_args.args[0]
            actual = command[command.index('--data-dir') + 1]
            self.assertEqual(Path(actual), (Path.cwd() / 'relative-state').resolve())
        self.controller.process = None

    def test_relative_frames_and_template_use_callers_directory(self):
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            process = self.controller.start(self.manifest, 'find-template', data_dir='relative-state',
                                           device={'type': 'replay', 'frames': ['frame.png']},
                                           config={'template': 'needle.png'})
            output, _ = process.communicate(timeout=15)
        finally:
            os.chdir(previous)
        self.assertEqual(process.returncode, 0, output)
        self.assertTrue((self.root / 'relative-state' / 'actions.json').is_file())

    def test_unresponsive_worker_and_owned_descendant_are_both_stopped(self):
        pack = self.make_waiting_package()
        (pack.root / 'plugin.py').write_text(
            'import subprocess, sys, time\n'
            'class Package:\n'
            '    def run(self, task_id, context):\n'
            '        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])\n'
            '        context.emit("child-started", pid=child.pid)\n'
            '        time.sleep(30)\n'
            '        return {}\n'
            'def create_package(): return Package()\n')
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            process = self.controller.start(pack, 'wait', data_dir=self.root,
                                           device={'type': 'replay', 'frames': []})
            self.assertEqual(json.loads(process.stdout.readline())['event'], 'started')
            event = json.loads(process.stdout.readline())
            owned_child = psutil.Process(event['pid'])
            self.controller.stop(timeout=0.1)
            self.assertIsNotNone(process.returncode)
            self.assertFalse(owned_child.is_running())
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=5)

    def test_device_registered_python_family_survives_forced_worker_stop(self):
        pack = self.make_waiting_package()
        ready = self.root / 'game-ready.json'
        game_code = ('import json,os,subprocess,sys,time; '
                     'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
                     f'open({str(ready)!r},"w").write(json.dumps([os.getpid(),child.pid])); '
                     'time.sleep(30)')
        source = '''
import json, subprocess, sys, time
from pathlib import Path
import psutil
from gameframe.devices.windows import WindowsDevice
class Platform:
    def pid(self, hwnd): return hwnd
    def process_created(self, pid): return psutil.Process(pid).create_time()
    def windows(self, pid):
        if not READY.exists(): return []
        values = json.loads(READY.read_text())
        return [pid] if pid == values[0] else []
    def is_visible(self, hwnd): return True
class Package:
    def run(self, task_id, context):
        device = WindowsDevice(launch_command=[sys.executable, '-c', GAME_CODE],
                               target_executable=psutil.Process().exe(), window_backend=Platform())
        device.prepare(context.stop)
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        context.emit('fixture-ready', protected=json.loads(READY.read_text()), owned=child.pid)
        time.sleep(30)
        return {}
def create_package(): return Package()
'''
        (pack.root / 'plugin.py').write_text(
            f'READY = __import__("pathlib").Path({str(ready)!r})\nGAME_CODE = {game_code!r}\n' + source)
        protected = []
        try:
            process = self.controller.start(pack, 'wait', data_dir=self.root,
                                           device={'type': 'replay', 'frames': []})
            self.assertEqual(json.loads(process.stdout.readline())['event'], 'started')
            event = json.loads(process.stdout.readline())
            self.assertEqual(event['event'], 'fixture-ready', event)
            protected = [psutil.Process(pid) for pid in event['protected']]
            owned = psutil.Process(event['owned'])
            protected_path = self.controller._protected_path
            self.controller.stop(timeout=.1)
            self.assertIsNotNone(process.returncode)
            self.assertFalse(owned.is_running())
            self.assertTrue(all(item.is_running() for item in protected))
            self.controller.close()
            self.assertFalse(protected_path.exists())
        finally:
            # These are only explicitly created fixture processes.
            family = {item.pid: item for item in protected}
            for item in protected:
                try:
                    family.update((child.pid, child) for child in item.children(recursive=True))
                except psutil.NoSuchProcess:
                    pass
            for item in reversed(list(family.values())):
                if item.is_running():
                    item.terminate()
            psutil.wait_procs(list(family.values()), timeout=5)


if __name__ == '__main__':
    unittest.main()
