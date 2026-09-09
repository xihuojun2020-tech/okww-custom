import json
import logging
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.runtime.diagnostic_export import sanitize_file, sanitize_text, safe_path, validate_manifest
from src.runtime.diagnostic_session import DiagnosticSession, FileLease, recover_sessions, seal_run
from src.runtime.diagnostic_uploader import upload_one, validate_remote, retry_pending, bounded_upload


class TestDiagnosticPipeline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'spool'
        self.remote = Path(self.temp.name) / 'nas'
        self.session = DiagnosticSession(self.root, '1.35.00')

    def tearDown(self):
        self.session.finish(timeout=5)
        self.temp.cleanup()

    def batch(self):
        self.session.record_event('test', {'message': 'safe event'})
        self.session.finish(timeout=5)
        return next(p for p in self.session.run.glob('batches/*')
                    if any(item['path'].endswith('.jsonl') for item in json.loads((p / 'manifest.json').read_text(encoding='utf-8'))['files']))

    def test_secrets_and_invalid_json_do_not_escape(self):
        secret = 'synthetic-value-DO-NOT-SHARE'
        for text in ('api_key=' + secret, 'Authorization: Bearer ' + secret,
                     '-----BEGIN PRIVATE KEY-----\n' + secret + '\n-----END PRIVATE KEY-----'):
            self.assertNotIn(secret, sanitize_text(text))
        source = self.session.run / 'sample.json'
        source.write_text(json.dumps({'access_token': secret, 'nested': {'password': secret}}))
        self.assertNotIn(secret.encode(), sanitize_file(source))
        source.write_text('{broken')
        with self.assertRaises(ValueError):
            sanitize_file(source)

    def test_unreviewed_images_are_blocked(self):
        from PIL import Image
        source = self.session.run / 'test.png'
        Image.new('RGB', (10, 10)).save(source)
        with self.assertRaisesRegex(ValueError, 'needs_review'):
            sanitize_file(source)
        self.assertTrue(sanitize_file(source, reviewed_image=True).startswith(b'\x89PNG'))

    def test_traversal_is_rejected(self):
        for name in ('../escape.log', '/escape.log', 'C:/escape.log', '日志/../../escape.log'):
            with self.assertRaises(ValueError):
                safe_path(self.root, name)

    def test_complete_batch_is_verified_and_idempotent(self):
        batch = self.batch()
        upload_one(batch, self.remote)
        control = next(self.remote.rglob('_UPLOAD_COMPLETE')).parent
        manifest = validate_remote(control)
        upload_one(batch, self.remote)
        self.assertEqual(manifest['run_id'], self.session.run_id)
        self.assertEqual(len(list(self.remote.rglob('_UPLOAD_COMPLETE'))), 1)
        first = next(self.remote.rglob('metadata.json'))
        first.write_text('changed')
        with self.assertRaises(ValueError):
            validate_remote(control)

    def test_failure_never_publishes_completion_marker(self):
        batch = self.batch()
        original = Path.replace
        def failed(source, target):
            if '.log.uploading.' in str(source) or '.jsonl.uploading.' in str(source):
                raise OSError('simulated disconnect')
            return original(source, target)
        with patch.object(Path, 'replace', failed):
            with self.assertRaises(OSError):
                upload_one(batch, self.remote)
        self.assertFalse(list(self.remote.rglob('_UPLOAD_COMPLETE')))
        upload_one(batch, self.remote)
        self.assertTrue(list(self.remote.rglob('_UPLOAD_COMPLETE')))

    def test_stale_upload_temporary_is_recovered(self):
        batch = self.batch()
        manifest = json.loads((batch / 'manifest.json').read_text(encoding='utf-8'))
        item = manifest['files'][0]
        destination = self.remote / '待分析' / item['path']
        destination.parent.mkdir(parents=True)
        destination.with_name(destination.name + '.uploading').write_bytes(
            (batch / item['path']).read_bytes())
        upload_one(batch, self.remote)
        self.assertTrue(destination.is_file())
        self.assertFalse(destination.with_name(destination.name + '.uploading').exists())

    def test_existing_foreign_upload_temporary_does_not_collide(self):
        batch = self.batch()
        manifest = json.loads((batch / 'manifest.json').read_text(encoding='utf-8'))
        item = manifest['files'][0]
        destination = self.remote / '待分析' / item['path']
        destination.parent.mkdir(parents=True)
        foreign = destination.with_name(destination.name + '.uploading.999.foreign')
        foreign.write_bytes(b'incomplete')
        upload_one(batch, self.remote)
        self.assertTrue(destination.is_file())
        self.assertEqual(foreign.read_bytes(), b'incomplete')

    def test_uploader_lock_contention_is_a_benign_noop(self):
        self.batch()
        with FileLease(self.root / '.uploader.lock'):
            self.assertFalse(retry_pending(self.root, self.remote))
        self.assertFalse((self.root / 'uploader-error.json').exists())

    def test_retry_survives_restart_and_preserves_batch(self):
        batch = self.batch()
        now = time.time()
        def failed(*args):
            raise OSError('offline')
        retry_pending(self.root, self.remote, now=now, transfer=failed)
        state_path = next((self.root / 'states').glob('*.json'))
        state = json.loads(state_path.read_text())
        self.assertEqual(state['status'], 'retrying')
        self.assertEqual(state['attempts'], 1)
        retry_pending(self.root, self.remote, now=now + 6, transfer=lambda b, t, _: upload_one(b, t))
        self.assertEqual(json.loads(state_path.read_text())['status'], 'uploaded')
        self.assertTrue(batch.exists())

    def test_running_session_is_not_recovered(self):
        recover_sessions(self.root)
        self.assertFalse((self.session.run / '_FINAL_SEALED').exists())
        self.session.lease.close()
        recover_sessions(self.root)
        self.assertEqual(json.loads((self.session.run / 'metadata.json').read_text())['process_status'], 'interrupted')

    def test_large_event_remains_valid_jsonl(self):
        self.session.record_event('large', {'text': 'a' * 90000})
        for line in (self.session.run / 'events.jsonl').read_text().splitlines():
            json.loads(line)

    def test_real_worker_process_uploads(self):
        batch = self.batch()
        bounded_upload(batch, self.remote, 10)
        self.assertTrue(list(self.remote.rglob('_UPLOAD_COMPLETE')))

    def test_worker_timeout_is_reported(self):
        with patch('src.runtime.diagnostic_uploader.subprocess.run', side_effect=subprocess.TimeoutExpired('worker', 1)):
            with self.assertRaisesRegex(OSError, 'timed out'):
                bounded_upload(self.root, self.remote, 1)

    def test_offline_evidence_keeps_retrying_after_24_hours(self):
        batch = self.batch()
        def offline(*args):
            raise OSError('offline')
        retry_pending(self.root, self.remote, now=time.time() + 90000, transfer=offline)
        state = json.loads(next((self.root / 'states').glob('*.json')).read_text())
        self.assertEqual(state['status'], 'retrying')
        self.assertTrue(batch.exists())

    def test_malformed_manifests_are_rejected(self):
        for value in (None, [], {'schema_version': 1, 'files': []},
                      {'schema_version': 1, 'files': [{'path': 3}]}):
            with self.assertRaises(ValueError):
                validate_manifest(self.root, value)

    def test_reader_indexes_once_and_ignores_partial_batches(self):
        from src.runtime.diagnostic_reader import scan
        batch = self.batch()
        self.assertEqual(scan(self.remote), [])
        upload_one(batch, self.remote)
        reports = scan(self.remote)
        self.assertEqual(len(reports), 1)
        self.assertEqual(json.loads(Path(reports[0]).read_text(encoding='utf-8'))['status'], 'validated_needs_analysis')
        self.assertEqual(scan(self.remote), [])

    def test_lifecycle_crash_is_local_and_finish_is_idempotent(self):
        from src.runtime import diagnostic_lifecycle as lifecycle
        with patch.object(lifecycle, '_session', self.session), patch.object(lifecycle, 'wake_uploader'):
            try:
                raise RuntimeError('synthetic crash')
            except RuntimeError as error:
                lifecycle.record_crash(type(error), error, error.__traceback__)
            lifecycle.finish_diagnostics()
            lifecycle.finish_diagnostics()
        self.assertEqual(self.session.metadata['process_status'], 'crashed')
        self.assertTrue(list(self.session.run.glob('batches/*/日志/*/*/*/*/*.json')))
        self.assertTrue((self.session.run / 'crash.json').is_file())

    def test_sealed_error_wakes_uploader(self):
        import threading
        ready = threading.Event()
        self.session.on_batch_ready = ready.set
        self.session.emit(logging.LogRecord('task', logging.ERROR, '', 0, 'task failed', (), None))
        self.assertTrue(ready.wait(3))
        self.assertEqual(self.session.metadata['process_status'], 'running')


if __name__ == '__main__':
    unittest.main()
