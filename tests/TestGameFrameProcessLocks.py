"""Real kernel leases between fixture processes; no devices are constructed."""

from contextlib import ExitStack
import json
import os
from pathlib import Path
from queue import Queue, Empty
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest

from gameframe.process_locks import device_input_lease, package_lease

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = '''
import json, os, sys, time
from contextlib import ExitStack
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from gameframe.process_locks import device_input_lease, package_lease, data_lease, LeaseUnavailable
options = json.loads(sys.argv[2])
def event(name):
    print(json.dumps({'event': name, 'pid': os.getpid()}), flush=True)
try:
    with ExitStack() as leases:
        if 'package' in options:
            leases.enter_context(package_lease(options['package'], options.get('exclusive', False)))
        if 'data' in options:
            leases.enter_context(data_lease(options['data'], options.get('exclusive', False)))
        if 'device' in options:
            leases.enter_context(device_input_lease(options['device']))
        event('acquired')
        if options.get('probe'):
            pass
        elif 'ready_file' in options:
            Path(options['ready_file']).write_text(json.dumps({'pid': os.getpid()}))
            while not Path(options['release_file']).exists():
                time.sleep(.02)
        else:
            for line in sys.stdin:
                if line.strip() == 'cleanup':
                    event('cleanup')  # Device cleanup still runs inside both leases.
                    continue
                if line.strip() == 'stop':
                    break
    event('released')
except LeaseUnavailable as error:
    event('blocked')
    raise SystemExit(23)
'''


class TestGameFrameProcessLocks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pack = self.root / 'fixture-package'
        self.pack.mkdir()
        self.script = self.root / 'lease-fixture.py'
        self.script.write_text(textwrap.dedent(FIXTURE), encoding='utf-8')
        self.serial = 'gameframe-synthetic-' + self.root.name

    def command(self, options):
        return [sys.executable, '-u', str(self.script), str(ROOT), json.dumps(options)]

    def launch(self, options):
        process = subprocess.Popen(self.command(options), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding='utf-8')
        lines = Queue()
        output = []
        def read():
            for line in process.stdout:
                output.append(line)
                lines.put(line)
            lines.put(None)
        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        def close():
            if process.poll() is None:
                process.stdin.write('stop\n')
                process.stdin.flush()
                process.wait(timeout=5)
            thread.join(timeout=2)
            process.stdin.close()
            process.stdout.close()
        self.addCleanup(close)
        def event():
            try:
                line = lines.get(timeout=5)
            except Empty:
                self.fail('Fixture timed out: ' + ''.join(output))
            self.assertIsNotNone(line, ''.join(output))
            return json.loads(line)
        return process, event

    def holder(self, options):
        process, event = self.launch(options)
        self.assertEqual(event()['event'], 'acquired')
        return process, event

    def probe(self, options, expected):
        result = subprocess.run(self.command({**options, 'probe': True}), text=True,
                                encoding='utf-8', capture_output=True, timeout=5)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        events = [json.loads(line)['event'] for line in result.stdout.splitlines()]
        self.assertEqual(events, ['blocked'] if expected else ['acquired', 'released'])

    def release(self, process, event):
        process.stdin.write('stop\n')
        process.stdin.flush()
        self.assertEqual(event()['event'], 'released')
        self.assertEqual(process.wait(timeout=5), 0)

    def test_adb_serial_is_exclusive_across_processes(self):
        device = {'type': 'adb', 'serial': self.serial}
        process, event = self.holder({'device': device})
        self.probe({'device': {**device, 'adb_path': 'different-adb'}}, 23)
        self.probe({'device': {'type': 'adb', 'serial': self.serial + '-other'}}, 0)
        self.release(process, event)
        self.probe({'device': device}, 0)

    def test_mumu_installation_and_instance_are_the_input_identity(self):
        installation = self.root / 'synthetic-mumu'
        installation.mkdir()
        device = {'type': 'mumu', 'install_dir': str(installation), 'instance_index': 2}
        process, event = self.holder({'device': device})
        alternate = {**device, 'install_dir': str(installation / '..' / installation.name),
                     'app_index': 7, 'package_name': 'synthetic.other', 'dll_path': 'unused.dll'}
        self.probe({'device': alternate}, 23)
        self.probe({'device': {**device, 'instance_index': 3}}, 0)
        self.release(process, event)

    @unittest.skipUnless(os.name == 'nt', 'Real Windows station/desktop identity requires Windows')
    def test_windows_input_ignores_hwnd_pid_package_and_data_directory(self):
        device = {'type': 'windows', 'hwnd': 101, 'pid': 202, 'data_dir': 'synthetic-a'}
        process, event = self.holder({'device': device})
        self.probe({'device': {'type': 'windows', 'hwnd': 303, 'pid': 404,
                               'data_dir': 'synthetic-b', 'package_name': 'synthetic-other'}}, 23)
        self.release(process, event)
        self.probe({'device': device}, 0)

    def test_replay_does_not_take_a_real_input_lease(self):
        process, event = self.holder({'device': {'type': 'replay'}})
        self.probe({'device': {'type': 'replay'}}, 0)
        self.probe({'device': {'type': 'adb', 'serial': self.serial}}, 0)
        self.release(process, event)

    def test_package_shared_owners_and_exclusive_replacement(self):
        owner1, event1 = self.holder({'package': str(self.pack)})
        owner2, event2 = self.holder({'package': str(self.pack / '..' / self.pack.name)})
        self.probe({'package': str(self.pack), 'exclusive': True}, 23)
        other = self.root / 'different-package'
        other.mkdir()
        self.probe({'package': str(other), 'exclusive': True}, 0)
        self.release(owner1, event1)
        self.probe({'package': str(self.pack), 'exclusive': True}, 23)
        self.release(owner2, event2)
        updater, update_event = self.holder({'package': str(self.pack), 'exclusive': True})
        self.probe({'package': str(self.pack)}, 23)
        self.probe({'package': str(self.pack), 'exclusive': True}, 23)
        self.release(updater, update_event)
        self.probe({'package': str(self.pack), 'exclusive': True}, 0)
        self.assertEqual(len(list((self.root / '.gameframe-locks').glob('package-*.lock'))), 2)

    def test_package_and_device_stay_locked_until_cleanup_finishes(self):
        options = {'package': str(self.pack), 'device': {'type': 'adb', 'serial': self.serial}}
        process, event = self.holder(options)
        process.stdin.write('cleanup\n')
        process.stdin.flush()
        self.assertEqual(event()['event'], 'cleanup')
        self.probe({'device': options['device']}, 23)
        self.probe({'package': str(self.pack), 'exclusive': True}, 23)
        self.release(process, event)
        self.probe({**options, 'exclusive': True}, 0)

    def test_shared_data_owner_blocks_restore_until_it_exits(self):
        data = self.root / 'synthetic-data'
        data.mkdir()
        process, event = self.holder({'data': str(data)})
        self.probe({'data': str(data / '..' / data.name)}, 0)
        self.probe({'data': str(data), 'exclusive': True}, 23)
        self.release(process, event)
        self.probe({'data': str(data), 'exclusive': True}, 0)
        self.assertEqual(len(list((self.root / '.gameframe-locks').glob('data-*.lock'))), 1)

    def test_kernel_releases_both_leases_when_owner_process_dies(self):
        options = {'package': str(self.pack), 'exclusive': True,
                   'device': {'type': 'adb', 'serial': self.serial}}
        process, event = self.launch(options)
        acquired = event()
        self.assertEqual(acquired['event'], 'acquired')
        import psutil
        owner = psutil.Process(acquired['pid'])
        owner.terminate()  # Only the actual interpreter of this owned fixture.
        owner.wait(timeout=5)
        process.wait(timeout=5)
        self.probe(options, 0)
        self.assertEqual(len(list((self.root / '.gameframe-locks').glob('package-*.lock'))), 1)

    def test_child_retains_leases_after_its_launching_parent_exits(self):
        ready = self.root / 'child-ready.json'
        release = self.root / 'child-release'
        options = {'package': str(self.pack), 'exclusive': True,
                   'device': {'type': 'adb', 'serial': self.serial},
                   'ready_file': str(ready), 'release_file': str(release)}
        launcher = ('import subprocess,sys,time\nfrom pathlib import Path\n'
                    'subprocess.Popen(sys.argv[2:], stdin=subprocess.DEVNULL, '
                    'stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n'
                    'while not Path(sys.argv[1]).exists(): time.sleep(.02)\n')
        parent = subprocess.run([sys.executable, '-c', launcher, str(ready), *self.command(options)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(parent.returncode, 0, parent.stderr)
        self.addCleanup(release.touch)
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(ready.exists(), 'Orphaned fixture did not acquire leases')
        import psutil
        child = psutil.Process(json.loads(ready.read_text())['pid'])
        self.assertTrue(child.is_running())
        self.probe({'device': options['device']}, 23)
        self.probe({'package': str(self.pack)}, 23)
        release.touch()
        child.wait(timeout=5)
        self.probe({'device': options['device'], 'package': str(self.pack), 'exclusive': True}, 0)

    def test_exception_unwinds_both_contexts(self):
        with self.assertRaisesRegex(RuntimeError, 'fixture cleanup failure'):
            with ExitStack() as leases:
                leases.enter_context(package_lease(self.pack, exclusive=True))
                leases.enter_context(device_input_lease({'type': 'adb', 'serial': self.serial}))
                raise RuntimeError('fixture cleanup failure')
        self.probe({'package': str(self.pack), 'exclusive': True,
                    'device': {'type': 'adb', 'serial': self.serial}}, 0)


if __name__ == '__main__':
    unittest.main()
