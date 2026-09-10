import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from src.runtime.diagnostic_evidence import EvidenceWindow


class TestDiagnosticEvidence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = 0.
        self.published = []
        self.identity = dict(device_id='device', installation_id='install', run_id='run', version='1.00.00')
        self.window = EvidenceWindow(self.root, self.identity, self.publish, clock=lambda: self.now)

    def tearDown(self):
        self.temp.cleanup()

    def publish(self, index, pictures):
        self.published.append(json.loads(json.dumps(index)))
        return index

    def sample(self, at, captured=None):
        self.now = float(at)
        self.window.sample(np.full((24, 32, 3), int(at) % 255, dtype=np.uint8),
                           1700000000 + at, at if captured is None else captured)

    def test_pre_at_post_window(self):
        for at in range(10):
            self.sample(at)
        self.now = 10.
        self.window.trigger({'message': 'failure'}, self.now)
        for at in range(10, 16):
            self.sample(at)
            self.window.tick()
        event = self.published[-1]
        self.assertEqual(event['state'], 'complete')
        self.assertEqual([f['phase'] for f in event['frames']], ['pre'] * 10 + ['at'] + ['post'] * 5)
        self.assertEqual([f['relative_seconds'] for f in event['frames']], list(range(-10, 6)))
        self.assertTrue(list(self.root.glob('*/frames/*.png')))

    def test_warmup_and_stale_are_not_fabricated(self):
        self.sample(0)
        self.now = 1.
        self.window.trigger({'message': 'early'}, 1.)
        self.sample(1)
        for at in range(2, 7):
            self.sample(at, captured=1.)
            self.window.tick()
        event = self.published[-1]
        self.assertEqual(event['state'], 'incomplete')
        self.assertIn('warmup', event['incomplete_reasons'])
        self.assertIn('stale_frame', event['incomplete_reasons'])
        self.assertLess(len(event['frames']), 7)

    def test_errors_merge_but_window_is_bounded(self):
        for at in range(10):
            self.sample(at)
        self.now = 10.
        self.window.trigger({'message': 'one'}, 10.)
        self.sample(10)
        for at in range(11, 42):
            self.now = float(at)
            if at % 3 == 0:
                self.window.trigger({'message': 'again'}, self.now)
            self.sample(at)
            self.window.tick()
        completed = [p for p in self.published if p['state'] != 'collecting']
        self.assertTrue(completed)
        self.assertLessEqual(completed[0]['ended_monotonic'] - 10, 30)
        self.assertIn('window_limit', completed[0]['incomplete_reasons'])
        self.assertGreater(len(completed[0]['triggers']), 1)

    def test_finish_preserves_frames_as_incomplete(self):
        self.now = 0.
        self.window.trigger({'message': 'exit'}, 0.)
        self.sample(0)
        self.window.finish()
        self.assertEqual(self.published[-1]['state'], 'incomplete')
        self.assertIn('interrupted', self.published[-1]['incomplete_reasons'])

    def test_event_and_ring_bytes_are_bounded(self):
        self.window.event_limit = 1
        self.window.ring_limit = 1
        self.sample(0)
        self.assertEqual(len(self.window.ring), 0)
        self.now = 1.
        self.window.trigger({}, 1.)
        self.sample(1)
        self.window.finish()
        self.assertEqual(self.published[-1]['frames'], [])
        self.assertIn('event_size_limit', self.published[-1]['incomplete_reasons'])

    def batch_window(self):
        from src.runtime.diagnostic_export import atomic_json
        from src.runtime.diagnostic_policy import POLICY
        from src.runtime.diagnostic_session import publish_incident
        self.run = self.root / 'run'
        self.run.mkdir()
        atomic_json(self.run / 'metadata.json', dict(self.identity, policy=POLICY,
                                                   started_at='2026-09-10T00:00:00+00:00'))
        self.window = EvidenceWindow(self.run / 'incidents', self.identity,
                                     lambda index, pictures: publish_incident(self.run, index, pictures),
                                     clock=lambda: self.now)

    def complete_event(self, offset=0):
        for at in range(offset, offset + 10):
            self.sample(at)
        self.now = offset + 10.
        self.window.trigger({'message': 'synthetic diagnostic failure'}, self.now)
        for at in range(offset + 10, offset + 16):
            self.sample(at)
            self.window.tick()

    def test_twenty_events_verify_images_and_out_of_order_delivery(self):
        from src.runtime.diagnostic_incidents import scan_incidents
        from src.runtime.diagnostic_uploader import upload_one
        self.batch_window()
        remote = self.root / 'remote'
        for number in range(20):
            self.complete_event(number * 30)
        batches = sorted(self.run.glob('batches/*'), key=lambda path: path.stat().st_mtime_ns)
        # Last immutable snapshot goes first: its references must not be assumed delivered.
        upload_one(batches[-1], remote)
        scan_incidents(remote)
        first = json.loads(next((remote / '事件索引').rglob('*.json')).read_text(encoding='utf-8'))
        self.assertEqual(first['delivery_state'], 'waiting_for_frames')
        for batch in reversed(batches):
            upload_one(batch, remote)
        scan_incidents(remote)
        views = list((remote / '事件索引').rglob('*.json'))
        self.assertEqual(len(views), 20)
        for path in views:
            event = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(event['state'], 'complete')
            self.assertEqual(event['delivery_state'], 'verified')
            self.assertEqual(len(event['frames']), 16)
            self.assertEqual(event['missing_remote_frames'], [])
        self.assertEqual(len(list((remote / '待分析' / '截图').rglob('*.png'))), 320)
        self.assertEqual(scan_incidents(remote), [])

    def test_retention_removes_incident_text_but_keeps_verified_image_links(self):
        from src.runtime.diagnostic_incidents import scan_incidents
        from src.runtime.diagnostic_retention import purge_remote_logs, WEEK
        from src.runtime.diagnostic_uploader import upload_one
        self.batch_window()
        self.complete_event()
        remote = self.root / 'remote'
        batches = list(self.run.glob('batches/*'))
        for batch in batches:
            upload_one(batch, remote)
        scan_incidents(remote)
        for batch in batches:
            purge_remote_logs(batch, remote, now=time.time() + WEEK + 60)
        scan_incidents(remote)
        view = next((remote / '事件索引').rglob('*.json'))
        text = view.read_text(encoding='utf-8')
        self.assertNotIn('synthetic diagnostic failure', text)
        index = json.loads(text)
        self.assertTrue(index['log_retention_expired'])
        self.assertEqual(len(index['frames']), 16)
        self.assertEqual(index['delivery_state'], 'verified')
        self.assertTrue(list((remote / '待分析' / '截图').rglob('*.png')))

    def test_interrupted_local_event_is_recovered_with_saved_images(self):
        from src.runtime.diagnostic_evidence import recover_events
        from src.runtime.diagnostic_session import publish_incident
        self.batch_window()
        self.window.publish = Mock(side_effect=OSError('interrupted sealing'))
        self.window.trigger({'message': 'before process death'}, 0.)
        self.sample(0)
        recover_events(self.run, lambda index, images: publish_incident(self.run, index, images), interrupted=True)
        index = json.loads(next((self.run / 'incidents').glob('*/event.json')).read_text(encoding='utf-8'))
        self.assertEqual(index['state'], 'incomplete')
        self.assertIn('interrupted', index['incomplete_reasons'])
        self.assertEqual(index['published_revision'], index['revision'])
        self.assertTrue(index['frames'][0]['remote_path'])

    def test_executor_refresh_is_owned_and_does_not_mutate_task_frame(self):
        from custom_ok.ok.task.TaskExecutor import TaskExecutor
        sentinel = object()
        frame = np.zeros((24, 32, 3), dtype=np.uint8)
        owner = SimpleNamespace(_diagnostic_capture_enabled=True, _diagnostic_capture_after=0,
                                _diagnostic_frame=None, _frame=sentinel,
                                is_executor_thread=lambda: True, exit_event=threading.Event(),
                                can_capture=lambda: True, method=SimpleNamespace(get_frame=Mock(return_value=frame)))
        TaskExecutor._service_diagnostic_capture(owner)
        self.assertIs(owner._diagnostic_frame[0], frame)
        self.assertIs(owner._frame, sentinel)
        owner._diagnostic_capture_after = 0
        owner._diagnostic_frame = None
        owner.is_executor_thread = lambda: False
        TaskExecutor._service_diagnostic_capture(owner)
        self.assertEqual(owner.method.get_frame.call_count, 1)

    def test_shared_target_probe_leaves_existing_files_untouched(self):
        from src.runtime.diagnostic_uploader import bounded_probe
        remote = self.root / 'remote'
        remote.mkdir()
        keep = remote / 'keep.txt'
        keep.write_text('user file')
        result = bounded_probe(str(remote), timeout=10)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(list(remote.iterdir()), [keep])

    def test_busy_worker_seals_logs_without_waiting_for_empty_queue(self):
        from src.runtime.diagnostic_session import DiagnosticSession
        with patch('src.runtime.diagnostic_session.LOG_INTERVAL', .05):
            session = DiagnosticSession(self.root / 'spool', '1.00.00')
        try:
            session.record_event('busy-log', {'message': 'must flush'})
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not list(session.run.glob('batches/*/_READY')):
                session.request_batch('incident')
                time.sleep(.005)
            self.assertTrue(list(session.run.glob('batches/*/_READY')))
        finally:
            session.finish(timeout=5)

    def test_sampling_failure_does_not_stop_log_delivery(self):
        from src.runtime.diagnostic_session import DiagnosticSession
        with patch('src.runtime.diagnostic_session.LOG_INTERVAL', .05):
            session = DiagnosticSession(self.root / 'spool', '1.00.00')
        try:
            session.sample_provider = Mock(side_effect=ValueError('broken source'))
            session.record_event('healthy-log', {})
            session.request_batch('periodic')
            session.pending.join()
            self.assertTrue(list(session.run.glob('batches/*/_READY')))
        finally:
            session.finish(timeout=5)

    def test_machine_hashes_survive_phone_redaction_but_messages_do_not(self):
        from src.runtime.diagnostic_export import sanitize_incident
        phone = '19910000001'
        frame_id = 'a' + phone + 'b' * 20
        checksum = 'a' + phone + 'c' * 52
        data = {'device_id': frame_id, 'triggers': [{'message': 'phone=' + phone}],
                'frames': [{'frame_id': frame_id, 'sha256': checksum,
                            'remote_path': f'截图/okww-custom/2026-09-10/run/000000-abcdefabcdef/{frame_id}.png'}]}
        cleaned = sanitize_incident(data)
        self.assertEqual(cleaned['device_id'], frame_id)
        self.assertEqual(cleaned['frames'][0], data['frames'][0])
        self.assertNotIn(phone, cleaned['triggers'][0]['message'])

    def test_malformed_incident_does_not_break_other_views(self):
        from src.runtime.diagnostic_incidents import scan_incidents, validate_index
        with self.assertRaises(ValueError):
            validate_index({'schema_version': 1, 'revision': 1, 'state': 'complete', 'frames': ['bad']})
        remote = self.root / 'remote'
        directory = remote / '事件索引' / 'device' / 'run'
        directory.mkdir(parents=True)
        (directory / 'bad.json').write_text('{broken')
        self.assertEqual(scan_incidents(remote), [])

    def test_late_at_frame_cannot_hide_missing_early_post_frames(self):
        for at in range(10):
            self.sample(at)
        self.now = 10.
        self.window.trigger({}, 10.)
        for at in range(12, 16):
            self.sample(at)
            self.window.tick()
        self.assertEqual(self.published[-1]['state'], 'incomplete')
        self.assertIn('post_frames_missing', self.published[-1]['incomplete_reasons'])

    def test_final_sample_is_taken_at_deadline_despite_initial_jitter(self):
        for at in range(10):
            self.sample(at)
        self.now = 10.
        self.window.trigger({}, 10.)
        for at in (10.3, 11.3, 12.3, 13.3, 14.3, 15.):
            self.sample(at)
            self.window.tick()
        self.assertEqual(self.published[-1]['state'], 'complete')
        self.assertEqual(len(self.published[-1]['frames']), 16)

    def test_broken_local_event_does_not_block_ordinary_log_sealing(self):
        from src.runtime.diagnostic_session import seal_pending
        self.batch_window()
        directory = self.run / 'incidents' / 'broken'
        directory.mkdir(parents=True)
        (directory / 'event.json').write_text('{broken')
        (self.run / 'run.log').write_text('healthy log\n')
        seal_pending(self.run, 'periodic')
        self.assertTrue(list(self.run.glob('batches/*/_READY')))
        self.assertTrue((self.run / 'evidence-recovery-error.json').is_file())


if __name__ == '__main__':
    unittest.main()
