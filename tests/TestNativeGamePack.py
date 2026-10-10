"""Portable native combat package checks, never an operating-system input test."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from gameframe.packages import PackageManifest, install_archive
from scripts.build_native_gamepack import build_native_gamepack
from scripts.build_gamepack import source_metadata


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'gamepacks/wuthering_waves_native'


class TestNativeGamePack(unittest.TestCase):
    def test_discovery_loads_only_metadata(self):
        expected = [task['class'] if task['class'] != 'AutoCombatTask' else 'auto-combat'
                    for task in source_metadata(ROOT)['tasks'][1:]]
        code = f'''
import sys
sys.path.insert(0, {str(ROOT)!r})
sys.modules['ok'] = None
sys.modules['src'] = None
sys.modules['PySide6'] = None
from gameframe.packages import PackageManifest
manifest = PackageManifest.read({str(PACK)!r})
package = manifest.load()
assert manifest.execution == 'native'
assert package.engine is None
assert [task.id for task in manifest.tasks] == {expected!r}
print('metadata-only')
'''
        result = subprocess.run([sys.executable, '-I', '-c', code], capture_output=True,
                                text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_installed_archive_runs_production_rotation_without_old_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = build_native_gamepack(root / 'native.zip')
            manifest = install_archive(archive, root / 'packages')
            self.assertEqual(manifest.id, 'wuthering_waves_native')
            self.assertTrue((manifest.root / 'payload/assets/coco_annotations.json').is_file())
            self.assertFalse((manifest.root / 'payload/config.py').exists())
            from tests.fixture_support import make_account_environment
            make_account_environment(root / 'data')
            code = f'''
import importlib.abc
import json
import sys
import threading
import traceback
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
class BlockLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {{'ok', 'PySide6', 'qfluentwidgets', 'custom_ok', 'config', 'main'}}:
            raise ImportError('Forbidden old runtime dependency: ' + fullname)
sys.meta_path.insert(0, BlockLegacy())
from gameframe.api import Cancelled
from gameframe.devices.replay import ReplayDevice
from gameframe.packages import PackageManifest
from gameframe.runtime import Runtime
from gameframe.state import RunStore
manifest = PackageManifest.read({str(manifest.root)!r})
package = manifest.load()
data_dir = Path({str(root / 'data')!r})
package.prepare('auto-combat', data_dir)
stop = threading.Event()
device = ReplayDevice([{str(ROOT / 'tests/images/in_combat.png')!r}] * 32)
submit = device.submit
calls = []
def record(action):
    submit(action)
    if action.kind.endswith('_down'):
        calls.extend(row.name for row in traceback.extract_stack())
        stop.set()
device.submit = record
release = device.release_all
released = []
def cleanup():
    released.append(True)
    release()
device.release_all = cleanup
store = RunStore(data_dir / 'runs.sqlite')
store.set_enabled(manifest.id, 'auto-combat', True)
watchdog = threading.Timer(30, stop.set)
watchdog.start()
try:
    try:
        Runtime(store, lambda event: None).run(
            manifest, package, 'auto-combat', device, data_dir,
            config={{'Switch to Healer before and after Combat': False}}, stop=stop)
    except Cancelled:
        pass
    else:
        raise AssertionError('Expected explicit device-boundary stop')
    for name in ('_run_combat', 'perform_combat_rotation', 'perform', 'do_perform'):
        assert name in calls, (name, calls)
    assert device.actions and released == [True] and not device.held
    assert store.history()[0]['status'] == 'cancelled'
    assert store.enabled(manifest.id, 'auto-combat')
    payload = (manifest.root / 'payload').resolve()
    actual = {{name: str(Path(module.__file__).resolve())
              for name, module in sys.modules.items()
              if name.startswith('src.') and getattr(module, '__file__', None)}}
    assert actual and all(Path(path).is_relative_to(payload) for path in actual.values()), actual
    assert not any(name.split('.')[0] in {{'ok', 'PySide6', 'qfluentwidgets', 'custom_ok'}} for name in sys.modules)
    print('NATIVE_ACCEPTANCE=' + json.dumps({{'actions': len(device.actions), 'modules': len(actual), 'status': 'cancelled', 'enabled': True}}))
finally:
    watchdog.cancel()
    watchdog.join()
    store.close()
'''
            result = subprocess.run([sys.executable, '-I', '-c', code], cwd=root,
                                    capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            marker = next(line for line in result.stdout.splitlines()
                          if line.startswith('NATIVE_ACCEPTANCE='))
            evidence = json.loads(marker.split('=', 1)[1])
            self.assertGreater(evidence['actions'], 0)
            self.assertGreater(evidence['modules'], 50)


if __name__ == '__main__':
    unittest.main()
