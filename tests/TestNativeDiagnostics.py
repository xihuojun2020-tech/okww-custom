"""Local native evidence over Replay; every external side effect is blocked."""

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PRELUDE = '''
import importlib.abc
import json
import logging
import os
import threading
import time
import zipfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import sys
sys.path.insert(0, sys.argv[1])
if len(sys.argv) > 3:
    sys.path.append(sys.argv[3])
source = Path(sys.argv[1])
root = Path(sys.argv[2])
class BlockLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ok','PySide6','qfluentwidgets','config','main','custom_ok'}:
            raise ImportError('native diagnostics imported ' + fullname)
sys.meta_path.insert(0, BlockLegacy())
from src.runtime import diagnostic_lifecycle
from src.runtime.native_diagnostics import (start_native_diagnostics, attach_native_executor,
    record_native_event, diagnostic_root, close_native_diagnostics)
from src.runtime.diagnostic_archive import build_archive
from src.runtime.diagnostic_policy import installation_id
data_dir = root / 'data'
data_dir.mkdir()
external = ExitStack()
boundaries = ('subprocess.Popen', 'src.runtime.diagnostic_policy.ensure_task',
    'src.runtime.diagnostic_policy.connect', 'src.runtime.diagnostic_policy.save_credentials',
    'src.runtime.diagnostic_lifecycle.wake_uploader',
    'src.runtime.diagnostic_lifecycle.start_automatic_archive_upload',
    'src.runtime.diagnostic_archive.send_archive', 'src.runtime.diagnostic_archive.connect',
    'src.runtime.diagnostic_archive_retention.maintenance_loop',
    'src.runtime.diagnostic_archive_retention.connect', 'src.runtime.diagnostic_uploader.connect')
spies = [external.enter_context(patch(name, side_effect=AssertionError('external boundary ' + name)))
         for name in boundaries]
def finish():
    close_native_diagnostics()
def assert_local():
    for spy in spies:
        spy.assert_not_called()
    assert not any(name.split('.')[0] in {'ok','PySide6','qfluentwidgets','config','main','custom_ok'}
                   for name in sys.modules)
'''

HOST = '''
from gameframe.api import TaskContext
from gameframe.devices.replay import ReplayDevice
from src.runtime.native_combat_host import NativeCombatHost
from src.combat.settings import COMBAT_GLOBAL_DEFAULTS, TEMPLATE_MATCHING_DEFAULTS
image_path = root / 'frame.png'
import cv2
import numpy as np
frame = np.full((720, 1280, 3), 173, np.uint8)
assert cv2.imwrite(str(image_path), frame)
device = ReplayDevice([image_path] * 4)
context = TaskContext(device, {}, data_dir, threading.Event(), 'diagnostics-test', Mock())
host = NativeCombatHost(context, coco_path=source / 'assets/coco_annotations.json',
    global_options=COMBAT_GLOBAL_DEFAULTS, template_matching=TEMPLATE_MATCHING_DEFAULTS,
    ocr_engine=Mock(), task_entry='src.task.AutoCombatTask:AutoCombatTask')
host.executor.next_frame()
'''


class TestNativeDiagnostics(unittest.TestCase):
    def run_native(self, body, *, source_root=ROOT, core_root=None):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'diagnostic_probe.py'
            script.write_text(PRELUDE + '\ntry:\n' + textwrap.indent(textwrap.dedent(body), '    ')
                              + '\n    assert_local()\nfinally:\n    finish()\n    external.close()\n',
                              encoding='utf-8')
            command = [sys.executable, '-I', '-B', '-X', 'utf8', str(script), str(source_root), directory]
            if core_root is not None:
                command.append(str(core_root))
            result = subprocess.run(command, capture_output=True,
                                    text=True, encoding='utf-8', timeout=35)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_close_waits_for_queued_work_and_cached_frame(self):
        self.run_native('''
session = start_native_diagnostics(data_dir, 'native-test')
session.pending.join()
import numpy as np
import cv2
frame = np.ones((32, 48, 3), dtype=np.uint8)
session.frame_provider = Mock(return_value=frame)
session.sample_provider = lambda: None
entered, release = threading.Event(), threading.Event()
original_collect = session.collector.collect
def collect(run):
    entered.set()
    assert release.wait(5)
    return original_collect(run)
session.collector.collect = collect
session.request_batch('queued-before-close')
assert entered.wait(5)
closer = threading.Thread(target=close_native_diagnostics)
closer.start()
time.sleep(.05)
assert closer.is_alive() and session.worker.is_alive()
assert not session.lease.stream.closed and not session.collector_lease.stream.closed
release.set()
closer.join(5)
assert not closer.is_alive() and not session.worker.is_alive()
assert session.closed_session and session.pending.unfinished_tasks == 0
assert session.lease.stream.closed and session.collector_lease.stream.closed
session.frame_provider.assert_called_once()
assert list((session.run / 'screenshots').glob('*.png'))
assert diagnostic_lifecycle._session is None
before = {path: path.read_bytes() for path in session.run.rglob('*') if path.is_file()}
error = RuntimeError('original worker cleanup failure')
diagnostic_lifecycle.record_crash(type(error), error, error.__traceback__)
diagnostic_lifecycle.finish_diagnostics()
assert before == {path: path.read_bytes() for path in session.run.rglob('*') if path.is_file()}
close_native_diagnostics()
''')

    def test_close_stops_after_timeout_and_metadata_write_failure(self):
        self.run_native('''
session = start_native_diagnostics(data_dir, 'native-test')
session.pending.join()
entered, release = threading.Event(), threading.Event()
original_collect = session.collector.collect
def collect(run):
    entered.set()
    assert release.wait(5)
    return original_collect(run)
session.collector.collect = collect
session.request_batch('blocked')
assert entered.wait(5)
session.finish(timeout=0)
assert session.closed_session and session.worker.is_alive()
release.set()
close_native_diagnostics()
assert not session.worker.is_alive() and session.lease.stream.closed

# A real metadata-write boundary failure must still stop the actual daemon.
diagnostic_lifecycle._session = None
session = start_native_diagnostics(data_dir, 'native-test')
session.record_event('before-finalize', {'status': 'success'})
session.pending.join()
streams = list(session.streams.values())
from src.runtime import diagnostic_session
original_json = diagnostic_session.atomic_json
def write(path, value):
    if Path(path).name == 'metadata.json':
        raise OSError('metadata disk unavailable')
    return original_json(path, value)
session.frame_provider = Mock(side_effect=OSError('cached image unavailable'))
with patch.object(diagnostic_session, 'atomic_json', side_effect=write), \
     patch('src.runtime.native_diagnostics._failure') as failure:
    close_native_diagnostics()
    assert failure.call_count == 2
    assert 'cached image unavailable' in str(failure.call_args_list[0].args[0])
    assert 'metadata disk unavailable' in str(failure.call_args_list[1].args[0])
assert not session.worker.is_alive() and session.pending.unfinished_tasks == 0
assert all(stream.closed for stream in streams)
assert session.lease.stream.closed and session.collector_lease.stream.closed
close_native_diagnostics()
''')

    def test_close_existing_evidence_drains_without_creating_default_service(self):
        self.run_native('''
from src.evidence import service as evidence
with patch.object(evidence, 'EvidenceRepository', side_effect=AssertionError('default created')):
    evidence.close_existing_evidence_service()
assert evidence._service is None
entered, release = threading.Event(), threading.Event()
saved = []
class Repository:
    def save_run(self, metadata):
        entered.set()
        assert release.wait(5)
        saved.append(metadata)
service = evidence.EvidenceService(Repository())
with patch.object(evidence, '_service', service):
    future = service.submit({'result': 'completed'}, None, run=True)
    assert entered.wait(5)
    closer = threading.Thread(target=evidence.close_existing_evidence_service)
    closer.start()
    time.sleep(.05)
    assert closer.is_alive() and not future.done()
    release.set()
    closer.join(5)
    assert not closer.is_alive() and future.done()
    assert saved == [{'result': 'completed'}]
    evidence.close_existing_evidence_service()
''')

    def test_real_session_cached_replay_error_and_offline_archive(self):
        self.run_native('''
session = start_native_diagnostics(data_dir, 'native-test')
assert session.local_only and session.on_batch_ready is None
assert session.root == diagnostic_root(data_dir)
assert session.collector.source == data_dir
assert session.metadata['installation_id'] == installation_id(data_dir)
''' + HOST + '''
attach_native_executor(host.executor)
cached = host.executor._diagnostic_frame
original = cached[0].copy()
with patch.object(device, 'next_frame', side_effect=AssertionError('diagnostics captured')), \
     patch.object(device, 'submit', side_effect=AssertionError('diagnostics sent input')):
    sample = session.sample_provider()
    assert sample[1:] == cached[1:]
    from src.runtime.account_task_support import native_blur_area
    box = native_blur_area(1280, 720)
    assert not sample[0][box.y:box.y+box.height, box.x:box.x+box.width].any()
    assert np.array_equal(cached[0], original)
    assert not np.shares_memory(sample[0], original)
    session.record_event('replay_failure', {'message': 'api_key=synthetic-secret'})
    session.record_error({'message': 'account failed', 'exception_type': 'RuntimeError'})
    session.pending.join()
    diagnostic_lifecycle.finish_diagnostics()
    assert session.closed_session
assert host.task.enabled
assert not device.actions
assert list(session.run.glob('incidents/*/event.json'))
archive = build_archive(session.root)
with zipfile.ZipFile(archive) as package:
    text = b'\\n'.join(package.read(name) for name in package.namelist() if name.endswith(('.log','.json','.jsonl')))
    assert b'synthetic-secret' not in text
    assert b'replay_failure' in text
    assert any(name.endswith('.png') for name in package.namelist())
assert_local()
''')

    def test_one_exact_screenshot_hook_for_host_task_and_helper(self):
        self.run_native('''
session = start_native_diagnostics(data_dir, 'native-test')
''' + HOST + '''
from src.runtime.native_screenshots import save_native_screenshot
from src.runtime.native_task import NativeBaseTask
raw = data_dir / 'okww监控室/CompletionEvidence/private.png'
raw.parent.mkdir(parents=True)
raw.write_bytes(cv2.imencode('.png', frame)[1].tobytes())
material = data_dir / 'okww监控室/material.png'
material.write_bytes(cv2.imencode('.png', frame)[1].tobytes())
with patch.object(session, 'add_screenshot', wraps=session.add_screenshot) as observed:
    direct = save_native_screenshot(data_dir, 'direct', frame)
    host.save_screenshot('host', frame)
    host.task.screenshot('adapted', frame)
    NativeBaseTask.screenshot(host.task, 'base', frame)
    assert observed.call_count == 4
    assert observed.call_args_list[0].args == (direct,)
    with patch('src.runtime.native_screenshots.cv2.imencode', return_value=(False, None)):
        try: save_native_screenshot(data_dir, 'failed', frame)
        except OSError: pass
        else: raise AssertionError('encoding failure hidden')
    assert observed.call_count == 4
    write_error = OSError('screenshot disk unavailable')
    with patch.object(Path, 'write_bytes', side_effect=write_error):
        try: save_native_screenshot(data_dir, 'write-failed', frame)
        except OSError as error: assert error is write_error
        else: raise AssertionError('write failure hidden')
    assert observed.call_count == 4 and host.task.enabled
session.pending.join()
session.finish(timeout=5)
assert len(list((session.run / 'screenshots').glob('*.png'))) == 4
archive = build_archive(session.root)
with zipfile.ZipFile(archive) as package:
    assert not any('private.png' in name or 'material.png' in name for name in package.namelist())
assert frame.all() and host.task.enabled
''')

    def test_observer_sampling_and_setup_failure_preserve_task_intent_and_png(self):
        self.run_native('''
session = start_native_diagnostics(data_dir, 'native-test')
''' + HOST + '''
attach_native_executor(host.executor)
from src.runtime.native_screenshots import save_native_screenshot
with patch.object(session, 'record_event', side_effect=OSError('observer unavailable')):
    record_native_event('native_task', task='AutoCombatTask', status='failed', stage='execution',
                        error=RuntimeError('private-phone-19910000001'))
    destination = save_native_screenshot(data_dir, 'observer-failed', frame)
assert destination.is_file()
with patch('src.runtime.native_diagnostics.masked_native_frame', side_effect=OSError('mask unavailable')):
    session.record_error({'message': 'failure with unavailable cached image'})
    session.pending.join()
    assert session.evidence.active['incomplete_reasons']
assert host.task.enabled
before = (data_dir / 'configs/AutoCombatTask.json').read_bytes()
with patch('src.runtime.native_diagnostics.diagnostic_root', side_effect=OSError('storage unavailable')):
    assert start_native_diagnostics(data_dir, 'native-test') is None
assert host.task.enabled
assert (data_dir / 'configs/AutoCombatTask.json').read_bytes() == before
''')

    def test_same_worker_runtime_retry_rebinds_host_without_closing_session(self):
        self.run_native('''
import importlib.util
from tests.fixture_support import make_account_environment
acl = external.enter_context(patch('src.secure_backup.harden_directory_permissions',
                                   side_effect=lambda path: Path(path)))
make_account_environment(data_dir, names=('A1', 'A3', 'A4'), publish=False)
spec = importlib.util.spec_from_file_location('native_plugin', source / 'gamepacks/wuthering_waves_native/plugin.py')
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)
package = plugin.create_package()
package.prepare('auto-combat', data_dir)
session = diagnostic_lifecycle._session
package.engine = Mock()
''' + HOST + '''
from gameframe.api import Cancelled
from gameframe.packages import PackageManifest
from gameframe.runtime import Runtime
from gameframe.state import RunStore
manifest = PackageManifest.read(package.root)
store = RunStore(root / 'run-state')
store.set_enabled(manifest.id, 'auto-combat', True)
runtime = Runtime(store, Mock())
hosts = []
original_init = NativeCombatHost.__init__
def create(actual, *args, **kwargs):
    original_init(actual, *args, **kwargs)
    hosts.append(actual)
def service(actual):
    actual.executor.next_frame()
    assert not session.closed_session
    assert session is diagnostic_lifecycle._session
    assert np.array_equal(session.sample_provider()[0], __import__(
        'src.runtime.native_screenshots', fromlist=['masked_native_frame']).masked_native_frame(actual.executor._frame))
    if len(hosts) == 1:
        raise RuntimeError('retry failure')
    raise Cancelled('explicit test stop')
with patch.object(NativeCombatHost, '__init__', create), \
     patch.object(NativeCombatHost, 'run_service', service):
    runtime.run_service(manifest, package, 'auto-combat', device, data_dir, stop=threading.Event())
assert len(hosts) == 2 and hosts[0] is not hosts[1]
assert all(actual.task.enabled for actual in hosts)
assert store.enabled(manifest.id, 'auto-combat')
assert not session.closed_session
session.pending.join()
events = (session.run / 'events.jsonl').read_text(encoding='utf-8')
assert '"status": "failed"' in events and '"status": "stopped"' in events
assert len(list(session.root.glob('*/metadata.json'))) == 1
from src.evidence import service as evidence
evidence._service.close()
''')

    def test_original_login_branches_emit_private_free_events_and_preserve_exceptions(self):
        self.run_native('''
session = start_native_diagnostics(data_dir, 'native-test')
from src.runtime import combat_api
combat_api.configure(native=True, data_dir=data_dir)
from src.runtime.login_flow_service import LoginFlowService
from src.runtime.native_errors import TaskDisabledException
private = '19910000001 private-nickname UTEST0001A feature001234'
def make_task():
    task = SimpleNamespace(executor=SimpleNamespace(check_enabled=Mock(), get_task_by_class=Mock(return_value=None)),
        _guard_account_transition=Mock(), _begin_account_switch_evidence=Mock(),
        do_find_account_drop_down=Mock(return_value=object()), _evidence_stage=Mock(),
        _wait_login_screen_stable=Mock(), _select_account_with_retry=Mock(), sleep=Mock(),
        _click_login_for_target=Mock(), ensure_main=Mock(), log_info=Mock(), log_warning=Mock(),
        _finish_account_switch_evidence=Mock(return_value=None), _enabled=True)
    return task
with patch.object(session, 'record_error', wraps=session.record_error) as incident:
    task = make_task()
    assert LoginFlowService(task).switch_to_account(private) == private
    assert task._enabled
    failure = RuntimeError(private)
    task = make_task()
    task._select_account_with_retry.side_effect = failure
    try: LoginFlowService(task).switch_to_account(private)
    except RuntimeError as observed: assert observed is failure
    else: raise AssertionError('original failure hidden')
    assert task._enabled
    stopped = TaskDisabledException(private)
    task = make_task()
    task._select_account_with_retry.side_effect = stopped
    try: LoginFlowService(task).switch_to_account(private)
    except TaskDisabledException as observed: assert observed is stopped
    else: raise AssertionError('original stop hidden')
    assert task._enabled and incident.call_count == 1
    before = session.sequence
    task = make_task()
    task.executor.check_enabled.side_effect = stopped
    try: LoginFlowService(task).switch_to_account(private)
    except TaskDisabledException: pass
    else: raise AssertionError('early stop hidden')
    task._guard_account_transition.assert_not_called()
    task._begin_account_switch_evidence.assert_not_called()
    assert session.sequence == before
    task = make_task()
    with patch.object(session, 'record_event', side_effect=OSError('observer failed')):
        assert LoginFlowService(task).switch_to_account(private) == private
    assert task._enabled and incident.call_count == 1
session.pending.join()
events = [json.loads(line) for line in (session.run / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
account = [event['data'] for event in events if event['event'] == 'account_switch']
assert [item['status'] for item in account] == ['started','succeeded','started','failed','started','stopped']
assert not any(value in json.dumps(account) for value in private.split())
assert all(set(item) <= {'task','status','stage','exception_type'} for item in account)
''')

    def test_installed_payload_diagnostics_runs_without_checkout_modules(self):
        from scripts.build_native_gamepack import build_native_gamepack
        from gameframe.packages import install_archive
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            installed = install_archive(build_native_gamepack(destination / 'pack.zip'), destination / 'installed')
            core_root = destination / 'core'
            shutil.copytree(ROOT / 'gameframe', core_root / 'gameframe', ignore=shutil.ignore_patterns('__pycache__'))
            self.run_native('''
session = start_native_diagnostics(data_dir, 'installed-test')
assert Path(sys.modules['src.runtime.native_diagnostics'].__file__).is_relative_to(source)
from gameframe.api import TaskContext
from src.runtime.native_combat_executor import NativeCombatExecutor
import numpy as np
executor = NativeCombatExecutor(TaskContext(Mock(), {}, data_dir, threading.Event(), 'installed', Mock()))
executor._diagnostic_frame = (np.ones((720,1280,3),np.uint8), time.time(), time.monotonic())
attach_native_executor(executor)
record_native_event('native_task', task='AutoCombatTask', status='failed', stage='execution',
                    error=RuntimeError('private failure'))
session.pending.join()
session.capture_last_frame()
session.finish(timeout=5)
assert build_archive(session.root).is_file()
''', source_root=installed.root / 'payload', core_root=core_root)


if __name__ == '__main__':
    unittest.main()
