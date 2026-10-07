import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from src.runtime.diagnostic_session import DiagnosticSession
from src.runtime.diagnostic_archive import build_archive, upload_archive, pending_days, hash_file


class TestDiagnosticArchive(unittest.TestCase):
    def test_bad_old_day_does_not_block_verified_later_upload(self):
        from src.runtime.diagnostic_archive import automatic_upload
        with tempfile.TemporaryDirectory() as temporary:
            root, nas = Path(temporary) / 'root', Path(temporary) / 'nas'
            old = self._dated_session(root, '2026-09-25')
            recent = self._dated_session(root, '2026-10-05')
            broken = list(old.run.glob('batches/*/_READY'))
            for path in broken:
                path.write_text('incomplete', encoding='ascii')
            with patch('src.runtime.diagnostic_archive.send_archive',
                       side_effect=lambda archive: upload_archive(archive, nas)):
                with self.assertRaisesRegex(ValueError, '2026-09-25'):
                    automatic_upload(root, today='2026-10-06')
                progress = json.loads((root / 'archives/progress.json').read_text())
                self.assertEqual('failed', progress['stage'])
                self.assertEqual(1, len(progress['uploaded']))
                remote = Path(progress['uploaded'][0])
                local = root / 'archives' / remote.name
                self.assertEqual(hash_file(local), hash_file(remote))
                self.assertTrue(all(path.read_text() == 'incomplete' for path in broken))
                self.assertTrue(all(json.loads(path.read_text())['status'] == 'uploaded'
                                    for path in (root / 'states').glob(recent.run.name + '--*.json')))
                with self.assertRaises(ValueError):
                    automatic_upload(root, today='2026-10-06')
                self.assertEqual(1, len(list((nas / '待分析/压缩包').glob('*.zip'))))

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
                                'exe': str(REPO / 'owned-python.exe')}
                process.cwd.return_value = str(REPO)
                process.children.return_value = []
            with patch('psutil.process_iter', return_value=[owned, other]), patch('psutil.wait_procs', return_value=([], [])):
                stop_legacy_uploaders(root)
            owned.terminate.assert_called_once()
            other.terminate.assert_not_called()

    def test_archive_keeps_sources_and_marks_only_after_upload(self):
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

    def test_existing_remote_is_replaced_without_readback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'root'
            session=DiagnosticSession(root,'test');session.finish(timeout=5)
            archive=build_archive(root)
            target=Path(temporary)/'nas'
            remote=target/'待分析/压缩包'/archive.name
            remote.parent.mkdir(parents=True);remote.write_bytes(b'conflict')
            upload_archive(archive,target)
            self.assertEqual(archive.read_bytes(),remote.read_bytes())

    def test_broken_ready_does_not_block_other_batches_or_get_acknowledged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'root'
            session = DiagnosticSession(root, 'test')
            session.record_event('one', {})
            session.finish(timeout=5)
            batches = sorted(root.glob('*/batches/*/_READY'))
            self.assertGreaterEqual(len(batches), 2)
            broken = batches[0]
            broken.write_text('incomplete', encoding='ascii')
            archive = build_archive(root)
            receipt = json.loads(archive.with_suffix('.json').read_text(encoding='utf-8'))
            key = session.run.name + '--' + broken.parent.name
            self.assertEqual(key, receipt['skipped_batches'][0]['key'])
            self.assertNotIn(key, [item['key'] for item in receipt['batches']])
            upload_archive(archive, Path(temporary) / 'nas')
            self.assertFalse((root / 'states' / (key + '.json')).exists())
            self.assertEqual('incomplete', broken.read_text(encoding='ascii'))

    def test_manual_policy_never_wakes_network_worker(self):
        from src.runtime.diagnostic_lifecycle import wake_uploader
        with tempfile.TemporaryDirectory() as temporary, patch('src.runtime.diagnostic_lifecycle.subprocess.Popen') as spawn:
            wake_uploader(Path(temporary))
            spawn.assert_not_called()

    def test_pack_and_upload_never_hash_or_read_back_contents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'root'
            session = DiagnosticSession(root, 'test')
            session.finish(timeout=5)
            target = Path(temporary) / 'nas'
            opened = Path.open
            def no_remote_read(path, mode='r', *args, **kwargs):
                if path.is_relative_to(target) and mode == 'rb':
                    raise AssertionError('upload must not read NAS content')
                return opened(path, mode, *args, **kwargs)
            with patch('src.runtime.diagnostic_archive.hash_file', side_effect=AssertionError('no full file hashing')), \
                    patch('src.runtime.diagnostic_export.digest', side_effect=AssertionError('no member hashing')), \
                    patch('zipfile.ZipFile.testzip', side_effect=AssertionError('no ZIP reread')), \
                    patch.object(Path, 'open', no_remote_read):
                archive = build_archive(root)
                remote = Path(upload_archive(archive, target))
                upload_archive(archive, target)
            self.assertEqual(archive.read_bytes(), remote.read_bytes())
            receipt = json.loads(archive.with_suffix('.json').read_text())
            self.assertEqual(hash_file(archive), receipt['sha256'])
            self.assertNotIn('verified_at', receipt)
            self.assertNotIn('verified_at', json.loads(remote.with_suffix('.json').read_text()))

    def test_resume_appends_without_remote_content_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'root'
            session = DiagnosticSession(root, 'test'); session.finish(timeout=5)
            archive = build_archive(root)
            target = Path(temporary) / 'nas'
            remote = target / '待分析/压缩包' / archive.name
            remote.parent.mkdir(parents=True)
            partial = remote.with_name(remote.name + '.partial')
            partial.write_bytes(archive.read_bytes()[:100])
            uploaded = Path(upload_archive(archive, target))
            self.assertEqual(hash_file(archive), hash_file(uploaded))
            self.assertEqual(hash_file(archive), json.loads(archive.with_suffix('.json').read_text())['sha256'])
            self.assertFalse(partial.exists())

    def test_legacy_receipt_checksum_is_not_compared_before_upload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'root'
            session = DiagnosticSession(root, 'test'); session.finish(timeout=5)
            archive = build_archive(root)
            receipt_path = archive.with_suffix('.json')
            receipt = json.loads(receipt_path.read_text())
            receipt['sha256'] = '0' * 64
            receipt_path.write_text(json.dumps(receipt))
            remote = Path(upload_archive(archive, Path(temporary) / 'nas'))
            self.assertEqual(archive.read_bytes(), remote.read_bytes())
            self.assertEqual(hash_file(archive), json.loads(receipt_path.read_text())['sha256'])

    def test_network_write_failure_keeps_archive_and_batches_pending(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'root'
            session = DiagnosticSession(root, 'test'); session.finish(timeout=5)
            archive = build_archive(root)
            opened = Path.open
            def fail_upload(path, mode='r', *args, **kwargs):
                if path.suffix == '.partial' and mode == 'wb':
                    raise OSError('synthetic network failure')
                return opened(path, mode, *args, **kwargs)
            with patch.object(Path, 'open', fail_upload):
                with self.assertRaisesRegex(OSError, 'synthetic network failure'):
                    upload_archive(archive, Path(temporary) / 'nas')
            self.assertTrue(archive.exists())
            self.assertEqual('packed', json.loads(archive.with_suffix('.json').read_text())['status'])
            self.assertFalse(list((root / 'states').glob('*.json')))
