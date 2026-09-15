import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from src.runtime.diagnostic_session import DiagnosticSession
from src.runtime.diagnostic_archive import build_archive, upload_archive


class TestDiagnosticArchive(unittest.TestCase):
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

    def test_archive_splits_pending_batches_at_payload_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'root'
            session = DiagnosticSession(root, 'test')
            session.record_event('first', {'payload': 'x' * 200})
            session.request_batch('manual')
            session.record_event('second', {'payload': 'y' * 200})
            session.finish(timeout=5)
            with patch('src.runtime.diagnostic_archive.ARCHIVE_PAYLOAD_LIMIT', 1):
                first = build_archive(root)
                first_receipt = json.loads(first.with_suffix('.json').read_text(encoding='utf-8'))
                self.assertEqual(1, len(first_receipt['batches']))
                upload_archive(first, Path(temporary) / 'nas')
                second = build_archive(root)
                second_receipt = json.loads(second.with_suffix('.json').read_text(encoding='utf-8'))
                self.assertGreaterEqual(len(second_receipt['batches']), 1)

    def test_manual_upload_preserves_and_skips_oversized_legacy_archive(self):
        from src.runtime.diagnostic_archive import manual_upload
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archives = root / 'archives'
            archives.mkdir()
            receipt = archives / 'okww诊断证据_legacy.json'
            receipt.write_text(json.dumps({'status': 'packed', 'size': 2}), encoding='utf-8')
            with patch('src.runtime.diagnostic_archive.ARCHIVE_PAYLOAD_LIMIT', 1), \
                    patch('src.runtime.diagnostic_archive.send_archive') as send, \
                    patch('src.runtime.diagnostic_archive.build_archive', side_effect=ValueError('没有尚未上传的已封存资料')):
                with self.assertRaisesRegex(ValueError, '没有尚未上传'):
                    manual_upload(root)
            send.assert_not_called()
            self.assertEqual('oversized', json.loads(receipt.read_text(encoding='utf-8'))['status'])
