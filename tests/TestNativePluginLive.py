"""Exercise the real plugin live bridge in an isolated, device-free process."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestNativePluginLive(unittest.TestCase):
    def test_current_context_observation_restore_retry_and_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            code = f'''
import importlib.abc
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, {str(ROOT)!r})
class BlockLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {{'ok', 'PySide6', 'qfluentwidgets'}}:
            raise ImportError('Forbidden legacy import: ' + fullname)
sys.meta_path.insert(0, BlockLegacy())
from gameframe.api import TaskContext
from gameframe.packages import PackageManifest
from src.runtime.native_live_status import NativeLiveReader, NativeLiveWriter
from src.runtime import native_combat_host
package = PackageManifest.read({str(ROOT / 'gamepacks/wuthering_waves_native')!r}).load()
package.engine = object()  # This fixture never needs an OCR model or device.
root = Path({temporary!r})
events = []
created = []
class Host:
    def __init__(self, context, **options):
        from src.runtime import combat_api
        assert combat_api._native and combat_api._mode == 'native'
        self.context = context
        self.writer = options['live_status']
        assert self.writer.context is context
        self.executor = SimpleNamespace()
        self.global_configs = options['global_options']
        created.append(self)
    def run_service(self):
        self.context.emit('combat-state', enabled=True, recovery_status='fixture-ready')
        self.context.emit('task-paused', paused=True)
        return {{'fixture':self.context.run_id}}
    def run_session(self, task_id):
        return self.run_service()
def first_events(event): events.append(('first',event))
def second_events(event): events.append(('second',event))
one = TaskContext(None, {{}}, root, threading.Event(), 'context-one', first_events)
two = TaskContext(None, {{}}, root, threading.Event(), 'context-two', second_events)
cwd = Path.cwd()
with patch.object(native_combat_host, 'NativeCombatHost', Host):
    assert package.run('auto-combat', one) == {{'fixture':'context-one'}}
    assert one.events is first_events and Path.cwd() == cwd
    first_writer = package._live_writer
    assert first_writer.value['context_run_id'] == 'context-one'
    assert first_writer.value['services']['auto-combat']['enabled']
    assert first_writer.value['paused']
    assert len(events) == 2
    assert package.run('auto-combat', two) == {{'fixture':'context-two'}}
    assert two.events is second_events and package._live_writer is not first_writer
    second_writer = package._live_writer
    assert second_writer.context is two
    one.emit('task-paused', paused=False)
    assert second_writer.value['paused'] is True
    owners = NativeLiveReader(root).owners()
    assert len(owners) == 1 and owners[0]['context_run_id'] == 'context-two'
    # An optional observer failure still invokes the original event receiver.
    with patch.object(NativeLiveWriter, 'observe_event', side_effect=ValueError('fixture observer')):
        before = len(events)
        assert package.run_session('auto-combat', two) == {{'fixture':'context-two'}}
        assert len(events) == before + 2 and two.events is second_events
    # Original execution errors remain errors, while callback/cwd cleanup still happens.
    with patch.object(Host, 'run_service', side_effect=ValueError('fixture task failure')):
        try:
            package.run('auto-combat', two)
        except ValueError as error:
            assert str(error) == 'fixture task failure'
        else:
            raise AssertionError('task failure swallowed')
        assert two.events is second_events and Path.cwd() == cwd
from src.evidence import service
from src.runtime import native_diagnostics
with patch.object(service, 'close_existing_evidence_service') as evidence_close, \
     patch.object(native_diagnostics, 'close_native_diagnostics', side_effect=ValueError('fixture diagnostic close')):
    try:
        package.close()
    except ValueError as error:
        assert str(error) == 'fixture diagnostic close'
    else:
        raise AssertionError('diagnostic close failure swallowed')
    evidence_close.assert_called_once()
assert package._live_writer is None and NativeLiveReader(root).owners() == []
assert not any(name.split('.')[0] in ('ok','PySide6','qfluentwidgets') for name in sys.modules)
print('plugin-live-bridge-ok')
'''
            result = subprocess.run([sys.executable, '-I', '-X', 'utf8', '-c', code],
                                    capture_output=True, text=True, encoding='utf-8', timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('plugin-live-bridge-ok', result.stdout)


if __name__ == '__main__':
    unittest.main()
