"""Production scheduler/hub/dispatcher boundaries with no OS or network calls."""
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest

from gameframe.api import Cancelled
from src.runtime.native_combat_host import NativeCombatHost
from src.runtime.native_desktop_notifications import OwnerDesktopNotifications
from src.runtime.native_notification_hub import NativeNotificationHub
from src.runtime.native_notifications import DEFAULTS


ROOT = Path(__file__).resolve().parents[1]


class TestNativeNotificationOwnerIntegration(unittest.TestCase):
    def fixture(self):
        trace, events = [], []
        stop, pause = threading.Event(), threading.Event()
        def check_stop():
            if stop.is_set():
                raise Cancelled()
        context = SimpleNamespace(stop=stop, pause=pause, check_stop=check_stop,
            device=SimpleNamespace(release_all=lambda: trace.append('release')),
            emit=lambda name, **values: events.append((name, values)))
        config = {**DEFAULTS, 'QQ Desktop Notification (Not Reliable)': True,
                  'QQ Desktop Nickname': 'fixture'}
        http = SimpleNamespace(config=config, close=lambda: trace.append('http-close'))
        backend = SimpleNamespace(foreground=lambda: None)
        def send(*args):
            trace.append('send')
            stop.set()
            return {'route': 'qq-desktop', 'status': 'delivered'}
        sender = SimpleNamespace(backend=backend, send=send)
        owner = OwnerDesktopNotifications(context, sender, config, owner_check=lambda: None)
        host = NativeCombatHost.__new__(NativeCombatHost)
        host.context = context
        host.notifications = NativeNotificationHub(context, http, desktop=owner)
        host.uid_overlay = None
        host.executor = SimpleNamespace(paused=False, session_checkpoint=None, nullable_frame=lambda: None)
        host.task = SimpleNamespace(enabled=True, config={'_enabled': True}, should_trigger=lambda: True)
        host._combat_recovery = None
        return host, owner, trace, events

    def test_background_unwinds_and_releases_before_owner_send(self):
        host, owner, trace, events = self.fixture()
        def poll():
            trace.append('poll')
            host.notify_external('title', 'message')
            self.assertEqual(events, [])
            try:
                host.executor.session_checkpoint()
            finally:
                trace.append('unwind')
        host.poll = poll
        with self.assertRaises(Cancelled):
            host.run_service()
        self.assertEqual(trace, ['poll', 'unwind', 'release', 'release', 'send', 'release'])
        self.assertIsNone(host.executor.session_checkpoint)
        self.assertTrue(host.task.enabled)
        self.assertTrue(host.task.config['_enabled'])
        self.assertFalse(owner.pending)
        self.assertEqual(events[0][1]['results'][0]['status'], 'delivered')
        host.notifications.close()

    def test_pause_retains_queue_stop_close_cancels_without_disabling_combat(self):
        host, owner, trace, events = self.fixture()
        host.notify_external('title', 'message')
        host.context.pause.set()
        self.assertFalse(host.drain_desktop_notification())
        self.assertTrue(owner.pending)
        self.assertEqual(trace, [])
        self.assertEqual(events, [])
        host.context.stop.set()
        host.notifications.close()
        self.assertFalse(owner.pending)
        self.assertEqual(events[0][1]['results'], [{'route': 'desktop', 'status': 'cancelled'}])
        self.assertEqual(trace, ['http-close'])
        self.assertTrue(host.task.enabled)
        self.assertTrue(host.task.config['_enabled'])

    def run_probe(self, body, *, source_root=ROOT, core_root=None, package_root=None):
        source_root = Path(source_root).resolve()
        package_root = (Path(package_root).resolve() if package_root is not None else
                        source_root / 'gamepacks/wuthering_waves_native')
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'notification_owner_probe.py'
            script.write_text(
                'import sys\nfrom pathlib import Path\n'
                'source_root = Path(sys.argv[1]).resolve()\n'
                'root = Path(sys.argv[2])\n'
                'package_root = Path(sys.argv[3]).resolve()\n'
                'core_root = Path(sys.argv[4]).resolve() if len(sys.argv) > 4 else None\n'
                'sys.path.insert(0, str(source_root))\n'
                'if core_root is not None: sys.path.insert(1, str(core_root))\n'
                + textwrap.dedent(body), encoding='utf-8')
            command = [sys.executable, '-I', '-B', '-X', 'utf8', str(script),
                       str(source_root), directory, str(package_root)]
            if core_root is not None:
                command.append(str(core_root))
            result = subprocess.run(command, capture_output=True, text=True,
                                    encoding='utf-8', timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout

    def test_plugin_foreground_boundary_error_cleanup_and_retry(self):
        output = self.run_probe('''
import sys, threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from gameframe.api import TaskContext
from gameframe.packages import PackageManifest
from src.runtime import native_combat_host, native_desktop_notifications, native_notifications
from src.runtime.native_desktop_notifications import OwnerDesktopNotifications
package = PackageManifest.read(package_root).load()
import inspect
assert Path(inspect.getfile(type(package))).resolve() == package_root / 'plugin.py'
assert Path(native_combat_host.__file__).resolve().is_relative_to(source_root)
assert Path(native_desktop_notifications.__file__).resolve().is_relative_to(source_root)
assert Path(native_notifications.__file__).resolve().is_relative_to(source_root)
if core_root is not None:
    import gameframe.api
    assert Path(gameframe.api.__file__).resolve().is_relative_to(core_root)
package.engine = object()
trace, owners, clients = [], [], []
context = TaskContext(SimpleNamespace(capabilities=frozenset(), release_all=lambda: trace.append('release')),
                      {}, root, threading.Event(), 'notification-owner-fixture', lambda e: None)
context._input_owner_thread = threading.get_ident()
callback, cwd = context.events, Path.cwd()
class Http:
    def __init__(self, config): self.config=config; self.closed=False; clients.append(self)
    def close(self): self.closed=True; trace.append('http-close')
def desktop(context, engine, config):
    config['QQ Desktop Notification (Not Reliable)']=True
    backend=SimpleNamespace(foreground=lambda: None)
    def send(*args):
        trace.append('send')
        return {'route':'qq-desktop','status':'delivered'}
    owner=OwnerDesktopNotifications(context, SimpleNamespace(backend=backend,send=send), config,
                                    owner_check=context.assert_input_owner)
    owners.append(owner)
    return owner
class Host:
    fail=False
    def __init__(self, context, **options):
        self.context=context; self.executor=SimpleNamespace(); self.global_configs=options['global_options']
        self.task=SimpleNamespace(info={})
    def run_once(self):
        self.notifications.notify('title','message')
        assert owners[-1].pending and 'send' not in trace
        trace.append('foreground')
        if self.fail: raise ValueError('fixture execution failure')
        trace.append('foreground-unwind')
        return {'status':'completed'}
    def drain_desktop_notification(self): return self.notifications.desktop.drain_one()
    def clear_uid_overlay(self): pass
with patch.object(native_combat_host,'NativeCombatHost',Host), \
     patch.object(native_notifications,'NativeNotifications',Http), \
     patch.object(native_desktop_notifications,'create_owner_desktop_notifications',desktop):
    # Real plugin selects a one-time task and drains only after run_once returns.
    task_id=next(t['id'] for t in package.manifest['tasks'] if t['kind'] != 'service')
    result=package.run(task_id,context)
    assert result['business_result']['status']=='completed'
    assert trace.index('foreground-unwind') < trace.index('send') < trace.index('http-close')
    assert owners[-1].closed and clients[-1].closed and package._notifications is None
    trace.clear(); Host.fail=True
    try: package.run(task_id,context)
    except ValueError as error: assert str(error)=='fixture execution failure'
    else: raise AssertionError('execution failure swallowed')
    assert 'send' not in trace and owners[-1].closed and not owners[-1].pending
    assert clients[-1].closed and package._notifications is None
    assert context.events is callback and Path.cwd()==cwd
    trace.clear(); Host.fail=False
    package.run(task_id,context)
    assert len(owners)==3 and all(owner.closed for owner in owners)
    assert all(client.closed for client in clients) and package._notifications is None
package.close()
print('notification-owner-plugin-ok')
''')
        self.assertIn('notification-owner-plugin-ok', output)



if __name__ == '__main__':
    unittest.main()
