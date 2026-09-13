import json
import tempfile
import time
import unittest
from pathlib import Path

from src.runtime.diagnostic_session import DiagnosticSession
from src.runtime.diagnostic_archive import build_archive, upload_archive, hash_file
from src.runtime.diagnostic_archive_retention import DAY, cleanup_local, cleanup_remote, mark_reviewed


class TestDiagnosticArchiveRetention(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / 'local'
        self.target = self.base / 'nas'
        self.session = DiagnosticSession(self.root, 'test')
        self.session.record_event('evidence', {'text': 'preserve me'})
        self.session.finish(timeout=5)
        self.archive = build_archive(self.root)
        self.remote = Path(upload_archive(self.archive, self.target))
        self.stamp = json.loads(self.archive.with_suffix('.json').read_text())['uploaded_at']

    def tearDown(self):
        self.session.finish(timeout=5)
        self.temp.cleanup()

    def test_local_day_boundary_keeps_receipts_and_unuploaded(self):
        cleanup_local(self.root, now=self.stamp + DAY - 1, source_root=self.base / 'source')
        self.assertTrue(self.archive.exists())
        payload = list(self.session.run.glob('batches/*/日志/**/*.jsonl'))
        self.assertTrue(payload)
        cleanup_local(self.root, now=self.stamp + DAY + 1, source_root=self.base / 'source')
        self.assertFalse(self.archive.exists())
        self.assertTrue(self.archive.with_suffix('.json').exists())
        self.assertFalse(any(path.exists() for path in payload))
        self.assertTrue(self.remote.exists())
        with self.assertRaisesRegex(ValueError, '没有尚未上传'):
            build_archive(self.root)

    def test_pending_session_is_not_deleted(self):
        states = list((self.root / 'states').glob('*.json'))
        states[0].write_text(json.dumps({'status': 'retrying', 'uploaded_at': self.stamp}))
        cleanup_local(self.root, now=self.stamp + DAY + 1, source_root=self.base / 'source')
        self.assertTrue(list(self.session.run.glob('batches/*/日志/**/*.jsonl')))

    def test_active_session_lock_prevents_local_deletion(self):
        from src.runtime.diagnostic_session import FileLease
        with FileLease(self.session.run / '.session.lock'):
            cleanup_local(self.root, now=self.stamp + DAY + 1, source_root=self.base / 'source')
        self.assertTrue(list(self.session.run.glob('batches/*/日志/**/*.jsonl')))

    def test_unreviewed_thirty_days(self):
        uploaded = json.loads(self.remote.with_suffix('.json').read_text())['uploaded_at']
        cleanup_remote(self.target, now=uploaded + 30 * DAY - 1)
        self.assertTrue(self.remote.exists())
        cleanup_remote(self.target, now=uploaded + 30 * DAY)
        self.assertFalse(self.remote.exists())
        self.assertEqual(cleanup_remote(self.target, now=uploaded + 31 * DAY), 0)

    def test_review_requires_report_and_retains_report_after_three_days(self):
        report = self.base / 'review.md'
        report.write_text('', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '不能为空'):
            mark_reviewed(self.remote.name, report, hash_file(self.remote), target=self.target)
        report.write_text('# 检查报告\n已检查合成事件，未执行游戏。', encoding='utf-8')
        reviewed = self.stamp + 2 * DAY
        result = Path(mark_reviewed(self.remote.name, report, hash_file(self.remote), target=self.target, now=reviewed))
        moved = self.target / '已检查/压缩包' / self.remote.name
        self.assertTrue(moved.exists())
        self.assertFalse(self.remote.exists())
        cleanup_remote(self.target, now=reviewed + 3 * DAY - 1)
        self.assertTrue(moved.exists())
        cleanup_remote(self.target, now=reviewed + 3 * DAY)
        self.assertFalse(moved.exists())
        self.assertTrue(result.exists())

    def test_modified_report_blocks_evidence_deletion(self):
        report = self.base / 'review.md'
        report.write_text('review done', encoding='utf-8')
        result = Path(mark_reviewed(self.remote.name, report, hash_file(self.remote), target=self.target, now=self.stamp))
        result.write_text('changed', encoding='utf-8')
        cleanup_remote(self.target, now=self.stamp + 31 * DAY)
        self.assertTrue((self.target / '已检查/压缩包' / self.remote.name).exists())

    def test_review_rejects_traversal(self):
        with self.assertRaises(ValueError):
            mark_reviewed('../outside.zip', self.base / 'report', 'bad', target=self.target)

    def test_legacy_complete_batches_expire_without_touching_unrelated_files(self):
        from src.runtime.diagnostic_uploader import upload_one
        batches = [p.parent for p in self.session.run.glob('batches/*/_READY')]
        for batch in batches:
            upload_one(batch, self.target)
        outsider = self.target / 'keep.txt'
        outsider.write_text('keep')
        markers = list(self.target.glob('待分析/日志/okww-custom/*/*/*/_UPLOAD_COMPLETE'))
        now = max(p.stat().st_mtime for p in markers) + 30 * DAY + 1
        cleanup_remote(self.target, now=now)
        self.assertFalse(any(p.exists() for p in markers))
        self.assertTrue(outsider.exists())
        self.assertTrue(list(self.target.rglob('_EVIDENCE_EXPIRED.json')))

    def test_source_cleanup_only_removes_unchanged_acknowledged_files(self):
        from src.runtime.diagnostic_collector import FileCollector
        source = self.base / 'source'
        (source / 'logs').mkdir(parents=True)
        old, changed = source / 'logs/old.log', source / 'logs/changed.log'
        old.write_text('old')
        changed.write_text('old')
        cursors = {f'logs/{p.name}': dict(FileCollector.stamp(p), run_id=self.session.run.name,
                    pre_policy=False) for p in (old, changed)}
        (self.root / 'source-cursors.json').write_text(json.dumps(cursors))
        changed.write_text('new writing must survive')
        cleanup_local(self.root, now=self.stamp + DAY + 1, source_root=source)
        self.assertFalse(old.exists())
        self.assertTrue(changed.exists())


if __name__ == '__main__':
    unittest.main()
