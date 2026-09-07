import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from src.runtime.diagnostic_collector import FileCollector
from src.runtime.diagnostic_policy import POLICY, settings
from src.runtime.diagnostic_session import DiagnosticSession
from src.runtime.diagnostic_uploader import retry_pending, upload_one, validate_remote
from src.runtime.diagnostic_retention import weekly_cleanup, purge_remote_logs, WEEK


class TestDiagnosticPolicy(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'spool'
        self.remote = Path(self.temp.name) / 'nas'
        self.session = DiagnosticSession(self.root, '1.37.00')

    def tearDown(self):
        self.session.finish(timeout=5)
        self.temp.cleanup()

    def test_policy_is_mandatory_and_preserves_start_boundary(self):
        first = settings(self.root)
        value = dict(first, enabled=False)
        (self.root / 'settings.json').write_text(json.dumps(value))
        second = settings(self.root)
        self.assertTrue(second['enabled'])
        self.assertEqual(first['started_at'], second['started_at'])
        self.assertEqual(first['device_id'], second['device_id'])

    @unittest.skipUnless(os.name == 'nt', 'Windows scheduled task')
    def test_scheduler_revision_migrates_cached_console_task(self):
        from src.runtime.diagnostic_policy import ensure_task, SCHEDULER_REVISION
        state = self.root / 'scheduler.json'
        state.write_text(json.dumps({'status': 'installed', 'root': str(self.root),
                                    'checked_at': time.time(), 'revision': SCHEDULER_REVISION - 1}))
        with patch('src.runtime.diagnostic_policy.subprocess.run', return_value=SimpleNamespace(returncode=0)) as run:
            ensure_task(self.root)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)
            ensure_task(self.root)
            self.assertEqual(run.call_count, 1)
        self.assertEqual(json.loads(state.read_text())['revision'], SCHEDULER_REVISION)

    @unittest.skipUnless(os.name == 'nt', 'Windows scheduled task')
    def test_installer_selects_pythonw_without_registering_real_task(self):
        script = Path(__file__).resolve().parents[1] / 'src/runtime/install_diagnostic_task.ps1'
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        command = ('& ' + quote(script) + ' -Preview -TaskName okww-silent-action-preview'
                   + ' -PythonExe ' + quote(sys.executable) + ' -Root ' + quote(self.root))
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', command],
                                capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        action = json.loads(result.stdout.decode(errors='replace'))
        chosen = Path(action['Execute'])
        self.assertEqual(chosen.name.casefold(), 'pythonw.exe')
        self.assertEqual(chosen.parent, Path(sys.executable).parent)

    def test_old_manifest_is_never_backfilled(self):
        self.session.record_event('old', {})
        self.session.finish(timeout=5)
        for p in self.session.run.glob('batches/*/manifest.json'):
            manifest = json.loads(p.read_text(encoding='utf-8'))
            manifest.pop('policy')
            p.write_text(json.dumps(manifest))
        calls = []
        retry_pending(self.root, self.remote, transfer=lambda *args: calls.append(args))
        self.assertEqual(calls, [])

    def test_incremental_files_skip_history_and_include_new_images(self):
        from PIL import Image
        source = Path(self.temp.name) / 'app'
        logs, pictures = source / 'logs', source / 'screenshots'
        logs.mkdir(parents=True)
        pictures.mkdir()
        log = logs / 'app.log'
        log.write_text('HISTORICAL_MUST_NOT_UPLOAD\n', encoding='utf-8')
        Image.new('RGB', (5, 5), 'red').save(pictures / 'old.png')
        collector = FileCollector(source, self.root)
        with log.open('a', encoding='utf-8') as stream:
            stream.write('NEW_DATA\n')
        Image.new('RGB', (5, 5), 'blue').save(pictures / 'new.png')
        collector.collect(self.session.run)
        manifests = list(self.session.run.glob('batches/*/manifest.json'))
        all_data = b''
        images = 0
        for path in manifests:
            for item in json.loads(path.read_text(encoding='utf-8'))['files']:
                all_data += (path.parent / item['path']).read_bytes()
                images += item['path'].startswith('截图/')
        self.assertIn(b'NEW_DATA', all_data)
        self.assertNotIn(b'HISTORICAL_MUST_NOT_UPLOAD', all_data)
        self.assertEqual(images, 1)
        FileCollector(source, self.root).collect(self.session.run)
        self.assertEqual(len(list(self.session.run.glob('batches/*/manifest.json'))), len(manifests))

    def test_weekly_cleanup_retains_images_pending_and_unrelated_files(self):
        from PIL import Image
        self.session.record_event('new-log', {'text': 'diagnostic evidence'})
        source = Path(self.temp.name) / 'image.png'
        Image.new('RGB', (10, 10)).save(source)
        self.session.add_screenshot(source)
        self.session.finish(timeout=5)
        retry_pending(self.root, self.remote, transfer=lambda b, t, _: upload_one(b, t))
        unrelated = self.remote / 'unrelated.log'
        unrelated.write_text('KEEP')
        now = time.time() + WEEK + 1
        weekly_cleanup(self.root, self.remote, now=now,
                       purge=lambda b, t: purge_remote_logs(b, t, now=now))
        self.assertTrue(list(self.remote.rglob('*.png')))
        self.assertTrue(list((self.session.run / 'screenshots').glob('*.png')))
        self.assertEqual(unrelated.read_text(), 'KEEP')
        self.assertFalse((self.session.run / 'events.jsonl').exists())
        self.assertFalse(list(self.remote.rglob('_UPLOAD_COMPLETE')))
        self.assertTrue(list(self.remote.rglob('_LOGS_PURGED')))
        for marker in self.remote.rglob('_LOGS_PURGED'):
            retained = validate_remote(marker.parent)
            self.assertTrue(retained['logs_purged'])
            self.assertTrue(all(item['path'].startswith('截图/') for item in retained['files']))
        # A second pass in the same week performs no deletes/network access.
        weekly_cleanup(self.root, self.remote, now=now + 1,
                       purge=lambda *_: self.fail('ran twice in one week'))

    def test_cleanup_does_not_remove_unuploaded_or_young_logs(self):
        self.session.record_event('pending', {})
        self.session.finish(timeout=5)
        now = time.time() + WEEK + 1
        weekly_cleanup(self.root, self.remote, now=now,
                       purge=lambda *_: self.fail('unuploaded batch was deleted'))
        self.assertTrue((self.session.run / 'events.jsonl').exists())
        retry_pending(self.root, self.remote, transfer=lambda b, t, _: upload_one(b, t))
        for batch in self.session.run.glob('batches/*'):
            with self.assertRaises(ValueError):
                purge_remote_logs(batch, self.remote)

    def test_original_collected_log_is_removed_only_after_delivery(self):
        source = Path(self.temp.name) / 'app'
        (source / 'logs').mkdir(parents=True)
        collector = FileCollector(source, self.root)
        log = source / 'logs' / 'new.log'
        log.write_text('NEW\n')
        collector.collect(self.session.run)
        self.session.finish(timeout=5)
        retry_pending(self.root, self.remote, transfer=lambda b, t, _: upload_one(b, t))
        now = time.time() + WEEK + 1
        weekly_cleanup(self.root, self.remote, now=now, source_root=source,
                       purge=lambda b, t: purge_remote_logs(b, t, now=now))
        self.assertFalse(log.exists())

    def test_after_exit_collector_captures_late_file_and_does_not_repeat(self):
        from src.runtime.diagnostic_collector import collect_after_exit
        source = Path(self.temp.name) / 'app'
        (source / 'logs').mkdir(parents=True)
        (source / 'config.py').write_text('version = "1.37.00"\n')
        FileCollector(source, self.root)
        (source / 'logs' / 'late.log').write_text('LATE_EVENT\n')
        collect_after_exit(self.root, source)
        runs = [p for p in self.root.iterdir() if (p / 'metadata.json').exists()]
        self.assertEqual(len(runs), 2)
        collect_after_exit(self.root, source)
        self.assertEqual(len([p for p in self.root.iterdir() if (p / 'metadata.json').exists()]), 2)

    def test_rewritten_log_does_not_lose_new_prefix(self):
        source = Path(self.temp.name) / 'app'
        (source / 'logs').mkdir(parents=True)
        log = source / 'logs' / 'app.log'
        log.write_text('HISTORICAL\n')
        collector = FileCollector(source, self.root)
        log.write_text('NEW_PREFIX and a longer replacement record\n')
        collector.collect(self.session.run)
        payload = b''.join(p.read_bytes() for p in self.session.run.glob('batches/*/日志/*/*/*/*/*.log'))
        self.assertIn(b'NEW_PREFIX', payload)
        self.assertNotIn(b'HISTORICAL', payload)

    def test_incomplete_json_does_not_block_other_files_or_repeat_forever(self):
        source = Path(self.temp.name) / 'app'
        (source / 'logs').mkdir(parents=True)
        collector = FileCollector(source, self.root)
        bad = source / 'logs' / 'a.json'
        bad.write_text('{incomplete')
        (source / 'logs' / 'b.log').write_text('HEALTHY_LOG\n')
        collector.collect(self.session.run)
        self.assertFalse(collector.changed('logs/a.json', bad))
        self.assertTrue(list(self.session.run.glob('batches/*/_READY')))
        self.assertFalse(list(self.session.run.glob('collected-*.json')))
        bad.write_text('{"complete": true}')
        collector.collect(self.session.run)
        self.assertTrue(list(self.session.run.glob('collected-*.json')))

    def test_interrupted_retention_resumes_without_deleting_images(self):
        self.session.record_event('retention-fault', {})
        self.session.finish(timeout=5)
        batch = next(p for p in self.session.run.glob('batches/*')
                     if any(x['path'].endswith('.jsonl') for x in json.loads((p / 'manifest.json').read_text(encoding='utf-8'))['files']))
        upload_one(batch, self.remote)
        original = Path.unlink
        def fail(path, *args, **kwargs):
            if path.is_relative_to(self.remote) and path.suffix == '.jsonl':
                raise OSError('synthetic retention interruption')
            return original(path, *args, **kwargs)
        now = time.time() + WEEK + 1
        with patch.object(Path, 'unlink', fail):
            with self.assertRaises(OSError):
                purge_remote_logs(batch, self.remote, now=now)
        self.assertFalse(list(self.remote.rglob('_UPLOAD_COMPLETE')))
        self.assertTrue(list(self.remote.rglob('_PURGING_LOGS')))
        purge_remote_logs(batch, self.remote, now=now)
        self.assertTrue(list(self.remote.rglob('_LOGS_PURGED')))
        self.assertFalse(list(self.remote.rglob('_PURGING_LOGS')))


if __name__ == '__main__':
    unittest.main()
