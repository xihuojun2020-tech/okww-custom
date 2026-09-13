import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from src.runtime.diagnostic_collector import FileCollector
from src.runtime.diagnostic_performance import PerformanceSampler
from src.runtime.ocr_reuse import cached_ocr


class TestRuntimePerformance(unittest.TestCase):
    def test_finished_background_write_survives_destroyed_signal_source(self):
        from src.gui.BackgroundOperation import _Work
        from shiboken6 import delete
        callback = Mock(return_value='saved')
        worker = _Work(1, callback)
        delete(worker.signals)
        worker.run()
        callback.assert_called_once()

    def test_unchanged_history_never_reads_file_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'logs').mkdir()
            for n in range(100):
                (root / 'logs' / f'{n}.log').write_text('historical log\n')
            collector = FileCollector(root, root / 'spool')
            with patch.object(collector, 'stamp', side_effect=AssertionError('unexpected read')):
                collector.collect(root / 'run')
                self.assertFalse(any(collector.changed(n, p) for n, p in collector.files()))

    def test_process_samples_are_low_rate_and_failure_isolated(self):
        clock = Mock(return_value=0.)
        process = Mock(pid=123)
        process.cpu_percent.return_value = 12.5
        process.memory_info.return_value = SimpleNamespace(rss=1000)
        process.num_threads.return_value = 4
        process.io_counters.return_value = SimpleNamespace(read_bytes=100, write_bytes=200)
        sampler = PerformanceSampler(clock=clock, process=process)
        self.assertIsNone(sampler.sample())
        sampler.observe('ocr', .02)
        clock.return_value = 30
        first = sampler.sample()
        self.assertEqual(first['timing']['ocr']['mean_ms'], 20)
        self.assertIsNone(sampler.sample())
        process.io_counters.return_value = SimpleNamespace(read_bytes=120, write_bytes=260)
        clock.return_value = 60
        self.assertEqual(sampler.sample()['write_bytes_delta'], 60)
        process.io_counters.side_effect = OSError('denied')
        clock.return_value = 90
        self.assertFalse(sampler.sample()['available'])

    def test_ocr_only_reuses_same_unchanged_frame_and_detaches_boxes(self):
        frame = np.zeros((20, 30, 3), dtype=np.uint8)
        task = SimpleNamespace(executor=SimpleNamespace(frame=frame, paused=False), ocr_default_threshold=.2)
        invoke = Mock(return_value=[{'name': 'example'}])
        first = cached_ocr(task, invoke, (), {'match': 'example'})
        first[0]['name'] = 'modified by caller'
        self.assertEqual(cached_ocr(task, invoke, (), {'match': 'example'})[0]['name'], 'example')
        self.assertEqual(invoke.call_count, 1)
        frame[0, 0] = 255
        cached_ocr(task, invoke, (), {'match': 'example'})
        self.assertEqual(invoke.call_count, 2)
        task.executor.frame = frame.copy()
        cached_ocr(task, invoke, (), {'match': 'example'})
        self.assertEqual(invoke.call_count, 3)
        cached_ocr(task, invoke, (), {'frame': frame})
        cached_ocr(task, invoke, (), {'frame': frame})
        self.assertEqual(invoke.call_count, 5)

    def test_completed_upload_skips_manifest(self):
        from src.runtime.diagnostic_uploader import retry_pending
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / 'run/batches/batch'
            batch.mkdir(parents=True)
            (batch / '_READY').touch()
            (root / 'states').mkdir()
            (root / 'states/run--batch.json').write_text('{"status":"uploaded"}')
            # Deliberately omit manifest: completed batches need no manifest read.
            transfer = Mock()
            with patch('src.runtime.diagnostic_uploader.recover_sessions'):
                retry_pending(root, root / 'nas', transfer=transfer)
            transfer.assert_not_called()

    def test_pending_index_avoids_historical_walk_after_reconciliation(self):
        from src.runtime.diagnostic_queue import pending_batches, queue_batch, acknowledge
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / 'run/batches/new'
            batch.mkdir(parents=True)
            (batch / '_READY').touch()
            queue_batch(batch)
            self.assertEqual(list(pending_batches(root, now=1000)), [batch])
            original = Path.glob
            def no_history(path, pattern):
                if pattern == '*/batches/*/_READY':
                    raise AssertionError('historical scan')
                return original(path, pattern)
            with patch.object(Path, 'glob', no_history):
                self.assertEqual(list(pending_batches(root, now=1030)), [batch])
                acknowledge(batch)
                self.assertEqual(list(pending_batches(root, now=1060)), [])

    def test_error_storm_is_merged_and_final_count_persisted(self):
        from src.runtime.diagnostic_evidence import EvidenceWindow
        with tempfile.TemporaryDirectory() as directory:
            published = []
            clock = Mock(return_value=10.)
            def publish(index, pictures):
                published.append(index)
                return index
            window = EvidenceWindow(directory, {'run_id': 'run'}, publish, clock=clock)
            for n in range(100):
                window.trigger({'message': 'same'}, 10.)
            window.finish()
            self.assertEqual(len(published), 2)
            self.assertEqual(published[-1]['trigger_count'], 100)

    def test_capture_failure_backs_off_and_refreshes_window(self):
        from custom_ok.ok.task.TaskExecutor import TaskExecutor
        method = SimpleNamespace(get_frame=Mock(return_value=None),
                                 hwnd_window=SimpleNamespace(do_update_window_size=Mock()))
        executor = SimpleNamespace(method=method)
        with patch('custom_ok.ok.task.TaskExecutor.time.monotonic', return_value=10.):
            for _ in range(20):
                self.assertIsNone(TaskExecutor._capture_frame(executor))
        self.assertEqual(method.get_frame.call_count, 1)
        method.hwnd_window.do_update_window_size.assert_called_once()

    def test_migration_copies_verifies_and_preserves_originals(self):
        from scripts.migrate_runtime_storage import migrate
        from src.runtime.diagnostic_storage import storage_path
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            repo = base / 'repo'
            repo.mkdir()
            old = {kind: base / 'old' / kind for kind in ('diagnostics', 'CompletionEvidence', 'MaterialPlanner', 'screenshots')}
            for root in old.values():
                root.mkdir(parents=True)
                (root / 'keep.txt').write_text('permanent statistics')
            target = base / 'new'
            with patch('scripts.migrate_runtime_storage.sources', return_value=old), patch('scripts.migrate_runtime_storage.require_offline'):
                migrate(target, repo=repo, apply=False)
                self.assertFalse(target.exists())
                migrate(target, repo=repo, apply=True)
            for kind, root in old.items():
                self.assertEqual((root / 'keep.txt').read_bytes(), (target / kind / 'keep.txt').read_bytes())
                self.assertEqual(storage_path(kind, root, repo=repo), target / kind)

    def test_migration_failure_never_switches_config(self):
        from scripts.migrate_runtime_storage import migrate
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            repo = base / 'repo'
            repo.mkdir()
            old = base / 'old'
            old.mkdir()
            (old / 'keep.txt').write_text('keep')
            with patch('scripts.migrate_runtime_storage.sources', return_value={'diagnostics': old}), \
                    patch('scripts.migrate_runtime_storage.require_offline'), \
                    patch('scripts.migrate_runtime_storage.digest', side_effect=['a', 'b']):
                with self.assertRaises(OSError):
                    migrate(base / 'new', repo=repo, apply=True)
            self.assertFalse((repo / 'configs/runtime_storage.json').exists())
            self.assertEqual((old / 'keep.txt').read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
