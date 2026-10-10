"""Device-free subprocesses publish live state under their real identities."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.runtime.native_live_status import NativeLiveReader


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = '''
import json, sys, threading
from pathlib import Path
from types import SimpleNamespace
from src.runtime import combat_api
combat_api.configure(native=True, data_dir=sys.argv[1])
from src.runtime import native_live_status
from src.daily_timing import DailyTiming
from src.task_status import publish_task_status
count = 0
atomic = native_live_status.atomic_json
def write(*args):
    global count
    count += 1
    atomic(*args)
native_live_status.atomic_json = write
context = SimpleNamespace(data_dir=Path(sys.argv[1]), run_id='framework-run', pause=threading.Event())
profile_id = sys.argv[2]
writer = native_live_status.NativeLiveWriter(context, 'fixture', '1.97.69')
task = type('DailyTask', (), {})()
task.info = {}
task.log_info = lambda *args: None
task.executor = SimpleNamespace(current_task=task, live_status=writer)
writer.begin_foreground(task)
repo = SimpleNamespace(save_daily_timing=lambda record: None, daily_timings=lambda identity: [])
timer = DailyTiming(task, repo)
timer.begin_account(profile_id, 'A1')
print(json.dumps({'session':writer.value['process_session'], 'writes':count,
                  'legacy_loaded':any(name.split('.')[0] in ('ok','PySide6') for name in sys.modules)}), flush=True)
for line in sys.stdin:
    command = line.strip()
    if command == 'stage':
        publish_task_status(task, profile_id=profile_id, task_id='forgery', run_id='business-run',
                            stage='材料副本', detail='执行中')
    elif command == 'pause':
        writer.observe_event({'event':'task-paused','paused':True})
    elif command == 'finish':
        timer.finish()
        writer.finish_foreground(task)
    elif command == 'host_failure':
        from src.runtime.native_combat_host import NativeCombatHost
        host = NativeCombatHost.__new__(NativeCombatHost)
        host.context = context
        context.check_stop = lambda: None
        host.task, host.executor, host.live_status = task, task.executor, writer
        task.executor.wait_on_pause = False
        task.executor.reset_scene = lambda: None
        task.on_destroy = lambda: None
        def run():
            assert writer.value['running']
            publish_task_status(task, profile_id=profile_id, task_id='forgery', run_id='new-business-run')
            raise ValueError('fixture task failure')
        task.run = run
        try:
            host.run_once()
        except ValueError:
            assert not writer.value['running'] and writer.value['timing'] is None
        else:
            raise AssertionError('host swallowed task failure')
    elif command == 'close':
        writer.close()
        break
    elif command == 'exit_without_close':
        break
    print(json.dumps({'writes':count}), flush=True)
'''


class TestNativeLiveStatus(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def start(self, profile='profile'):
        code = f'import sys; sys.path.insert(0, {str(ROOT)!r})\n' + FIXTURE
        child = subprocess.Popen([sys.executable, '-I', '-X', 'utf8', '-u', '-c', code, str(self.root), profile],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, encoding='utf-8')
        self.addCleanup(self.cleanup, child)
        ready = json.loads(child.stdout.readline())
        self.assertFalse(ready['legacy_loaded'])
        return child, ready['session']

    @staticmethod
    def cleanup(child):
        if child.poll() is None:
            child.stdin.write('close\n')
            child.stdin.flush()
        child.communicate(timeout=15)

    def command(self, child, command):
        child.stdin.write(command + '\n')
        child.stdin.flush()
        if command in ('close', 'exit_without_close'):
            output, error = child.communicate(timeout=15)
            self.assertEqual(child.returncode, 0, output + error)
            return
        return json.loads(child.stdout.readline())

    def test_two_workers_keep_separate_business_identity_and_cached_elapsed(self):
        first, one = self.start()
        second, two = self.start()
        self.assertNotEqual(one, two)
        self.command(first, 'stage')
        self.command(second, 'stage')
        reader = NativeLiveReader(self.root)
        self.assertEqual({owner['process_session'] for owner in reader.owners()}, {one, two})
        with patch.object(Path, 'read_text', side_effect=AssertionError('elapsed must not reload files')):
            for session in (one, two):
                live = reader.live(session)
                self.assertEqual((live['profile_id'], live['task_id'], live['run_id']),
                                 ('profile', 'forgery', 'business-run'))
                self.assertGreaterEqual(live['elapsed'], 0)
            self.assertEqual(len(reader.timings()), 2)
        self.command(first, 'close')
        reader.reload()
        self.assertEqual([owner['process_session'] for owner in reader.owners()], [two])

    def test_duplicate_stages_do_not_write_and_pause_keeps_timing(self):
        child, session = self.start()
        first = self.command(child, 'stage')['writes']
        self.assertEqual(self.command(child, 'stage')['writes'], first)
        self.assertEqual(self.command(child, 'pause')['writes'], first + 1)
        self.assertEqual(self.command(child, 'pause')['writes'], first + 1)
        reader = NativeLiveReader(self.root)
        self.assertTrue(reader.owners()[0]['paused'])
        self.assertEqual(len(reader.timings()), 1)
        self.command(child, 'finish')
        reader.reload()
        self.assertEqual(reader.live(session), {})
        self.assertEqual(reader.timings(), {})

    def test_dead_or_reused_identity_is_not_live_without_mtime_selection(self):
        child, session = self.start()
        self.command(child, 'stage')
        reader = NativeLiveReader(self.root)
        path = reader.directory / (session + '.json')
        value = json.loads(path.read_text(encoding='utf-8'))
        value['worker_create_time'] += 1
        path.write_text(json.dumps(value), encoding='utf-8')
        reader.reload()
        self.assertEqual(reader.owners(), [])
        self.assertEqual(reader.live(session), {})
        value['worker_create_time'] -= 1
        path.write_text(json.dumps(value), encoding='utf-8')
        reader.reload()
        self.assertEqual(len(reader.owners()), 1)
        self.command(child, 'exit_without_close')
        self.assertTrue(path.exists())
        self.assertEqual(reader.owners(), [])
        self.assertEqual(reader.timings(), {})

    def test_host_failure_clears_foreground_and_preserves_original_exception(self):
        child, session = self.start()
        self.command(child, 'host_failure')
        reader = NativeLiveReader(self.root)
        self.assertEqual(reader.live(session), {})
        self.assertEqual(reader.timings(), {})

    def test_unreadable_state_reports_failure_instead_of_retaining_active_cache(self):
        child, session = self.start()
        self.command(child, 'stage')
        reader = NativeLiveReader(self.root)
        self.assertEqual(reader.live(session)['task_id'], 'forgery')
        (reader.directory / (session + '.json')).write_text('{broken', encoding='utf-8')
        with self.assertRaises(ValueError):
            reader.reload()
        self.assertEqual(reader.live(session), {})
        self.assertEqual(reader.timings(), {})


if __name__ == '__main__':
    unittest.main()
