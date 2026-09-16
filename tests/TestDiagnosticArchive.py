import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from src.runtime.diagnostic_session import DiagnosticSession
from src.runtime.diagnostic_archive import build_archive, upload_archive, pending_days, hash_file


class TestDiagnosticArchive(unittest.TestCase):
    def _dated_session(self, root, day):
        from datetime import datetime
        session = DiagnosticSession(root, 'test')
        session.finish(timeout=5)
        for manifest_path in session.run.glob('batches/*/manifest.json'):
            value = json.loads(manifest_path.read_text(encoding='utf-8'))
            value['created_at'] = datetime.fromisoformat(day + 'T12:00:00').timestamp()
            manifest_path.write_text(json.dumps(value), encoding='utf-8')
            manifest_path.with_name('_READY').write_text(hash_file(manifest_path), encoding='ascii')
        return session

    def test_pending_days_and_daily_archive_exclude_today(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'root'
            old = self._dated_session(root, '2026-09-14')
            today = self._dated_session(root, '2026-09-16')
            self.assertEqual(['2026-09-14'], pending_days(root, today='2026-09-16'))
            archive = build_archive(root, day='2026-09-16', mode='manual', flush_current=False)
            receipt = json.loads(archive.with_suffix('.json').read_text(encoding='utf-8'))
            self.assertEqual(('2026-09-16', 'manual'), (receipt['day'], receipt['mode']))
            self.assertEqual({today.run.name}, {item['key'].split('--', 1)[0] for item in receipt['batches']})
            old.finish(timeout=1); today.finish(timeout=1)

    def test_active_archive_flush_keeps_session_open_and_later_events_pending(self):
        from src.runtime import diagnostic_lifecycle
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'root'
            session = DiagnosticSession(root, 'test')
            try:
                session.record_event('before_upload', {})
                with patch.object(diagnostic_lifecycle, '_session', session):
                    first = build_archive(root)
                self.assertFalse(session.closed_session)
                upload_archive(first, Path(temporary) / 'nas')
                session.record_event('after_upload', {})
                session.finish(timeout=5)
                second = build_archive(root)
                with zipfile.ZipFile(second) as package:
                    logs = b''.join(package.read(name) for name in package.namelist() if name.endswith('日志汇总.log'))
                    self.assertIn(b'after_upload', logs)
            finally:
                session.finish(timeout=5)

    def test_legacy_worker_stop_requires_exact_root_and_owned_runtime(self):
        from unittest.mock import MagicMock
        from src.runtime.diagnostic_policy import stop_legacy_uploaders, REPO
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owned, other = MagicMock(), MagicMock()
            for pid, process, spool in ((12345, owned, root), (12346, other, root / 'other')):
                process.pid = pid
                process.info = {'cmdline': ['python', '-m', 'src.runtime.diagnostic_uploader', '--root', str(spool)],
                                'exe': str(REPO / '.venv/Scripts/python.exe')}
                process.cwd.return_value = str(REPO)
                process.children.return_value = []
            with patch('psutil.process_iter', return_value=[owned, other]), patch('psutil.wait_procs', return_value=([], [])):
                stop_legacy_uploaders(root)
            owned.terminate.assert_called_once()
            other.terminate.assert_not_called()

    def test_archive_keeps_sources_and_marks_only_after_verified_upload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'root'
            session=DiagnosticSession(root,'test')
            session.record_event('test',{'message':'synthetic'})
            session.finish(timeout=5)
            originals=list(root.glob('*/batches/*/_READY'))
            archive=build_archive(root)
            self.assertFalse(list((root/'states').glob('*.json')))
            with zipfile.ZipFile(archive) as package:
                self.assertIsNone(package.testzip())
                self.assertIn('manifest.json',package.namelist())
                self.assertTrue(any(name.startswith('sessions/') for name in package.namelist()))
            remote=Path(upload_archive(archive,Path(temporary)/'nas'))
            self.assertEqual(archive.read_bytes(),remote.read_bytes())
            self.assertTrue(all(path.exists() for path in originals))
            self.assertTrue(all(json.loads(path.read_text())['transport']=='archive' for path in (root/'states').glob('*.json')))
            with self.assertRaisesRegex(ValueError,'没有尚未上传'):build_archive(root)

    def test_remote_conflict_does_not_acknowledge_batches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'root'
            session=DiagnosticSession(root,'test');session.finish(timeout=5)
            archive=build_archive(root)
            target=Path(temporary)/'nas'
            remote=target/'待分析/压缩包'/archive.name
            remote.parent.mkdir(parents=True);remote.write_bytes(b'conflict')
            with self.assertRaisesRegex(ValueError,'冲突'):upload_archive(archive,target)
            self.assertFalse(list((root/'states').glob('*.json')))

    def test_manual_policy_never_wakes_network_worker(self):
        from src.runtime.diagnostic_lifecycle import wake_uploader
        with tempfile.TemporaryDirectory() as temporary, patch('src.runtime.diagnostic_lifecycle.subprocess.Popen') as spawn:
            wake_uploader(Path(temporary))
            spawn.assert_not_called()

    def test_upload_copies_without_rehashing_the_zip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'root'
            session = DiagnosticSession(root, 'test')
            session.finish(timeout=5)
            archive = build_archive(root)
            real_hash = __import__('src.runtime.diagnostic_archive', fromlist=['hash_file']).hash_file
            with patch('src.runtime.diagnostic_archive.hash_file', side_effect=lambda path: (
                    real_hash(path) if Path(path).name == 'manifest.json' else
                    (_ for _ in ()).throw(AssertionError('ZIP must not be rehashed')))):
                remote = Path(upload_archive(archive, Path(temporary) / 'nas'))
            self.assertEqual(archive.stat().st_size, remote.stat().st_size)
