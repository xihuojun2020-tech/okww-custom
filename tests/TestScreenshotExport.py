import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np

from src.evidence.export import export_screenshots, export_state, asset_lock
from src.evidence.repository import EvidenceRepository

ACCOUNT = '00000000-0000-4000-8000-000000000001'
OTHER = '00000000-0000-4000-8000-000000000002'
FIRST = '2026-10-01T12:00:00+08:00'
SECOND = '2026-10-01T13:00:00+08:00'


class TestScreenshotExport(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = EvidenceRepository(Path(self.temp.name) / 'okww监控室' / 'CompletionEvidence')

    def save(self, when=FIRST, profile=ACCOUNT, project='sea_ruins'):
        return self.repo.save(dict(profile_id=profile, project_id=project, captured_at=when,
                                   source='automatic', completion_status='partial'),
                              np.zeros((5, 8, 3), np.uint8))

    def export(self, when=FIRST, **kwargs):
        return export_screenshots(self.repo, ACCOUNT, '昵称:/测试', when, **kwargs)

    def entries(self, result):
        with ZipFile(result['path']) as archive:
            self.assertIsNone(archive.testzip())
            names = archive.namelist()
            self.assertTrue(all(name.endswith('.png') or name.endswith('/') for name in names))
            return names

    def test_all_history_over_page_limit_statuses_recycle_and_account_isolation(self):
        for index in range(65):
            row = self.save(project='daily_activity' if index % 2 else 'sea_ruins')
            if index == 64:
                self.repo.trash(row['evidence_id'])
        self.save(profile=OTHER)
        self.repo.save(dict(profile_id=ACCOUNT, project_id='weekly_boss', captured_at=FIRST), None)
        result = self.export()
        self.assertEqual(result['count'], 2)
        entries = self.entries(result)
        self.assertEqual(len(entries), 2)
        self.assertTrue(any(name.startswith('回收区/') for name in entries))
        self.assertTrue(any(name.startswith('活跃度/') for name in entries))
        self.assertIn('昵称__测试_20261001-120000_至_20261001-120000', Path(result['path']).name)
        self.assertEqual(Path(result['path']).parent, self.repo.root.parent / '完成截图打包')
        self.assertEqual(export_state(self.repo, OTHER), {})
        self.assertEqual(self.export()['count'], 0)
        self.assertEqual(export_state(self.repo, ACCOUNT)['cutoff'], FIRST)

    def test_incremental_same_second_late_save_future_save_restart_and_rename(self):
        self.save()
        self.export()
        self.save()  # Same-second image saved after the first snapshot must not disappear.
        self.save(when='2026-09-25T09:00:00+08:00')
        future = self.save(when='2026-10-01T14:00:00+08:00')
        repo = EvidenceRepository(self.repo.root)
        result = export_screenshots(repo, ACCOUNT, '新昵称', SECOND)
        self.assertEqual(result['count'], 2)
        self.assertTrue(any('20260925-090000' in name for name in self.entries(result)))
        self.assertTrue(Path(result['path']).name.startswith('新昵称_20261001-120000'))
        result = self.export(when=future['captured_at'])
        self.assertEqual(result['count'], 1)

    def test_capture_while_exporting_is_not_blocked_and_is_exported_next(self):
        self.save()
        self.export(progress=lambda done, total: self.save(when=SECOND))
        self.assertEqual(self.export(when=SECOND)['count'], 1)

    def test_missing_corrupt_cancel_and_disk_failure_do_not_advance(self):
        self.save()
        self.export()
        new = self.save(when=SECOND)
        path = self.repo.asset_path(new['image_path'])
        original = path.read_bytes()
        path.unlink()
        with self.assertRaisesRegex(OSError, '原图缺失'):
            self.export(SECOND)
        path.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, '校验失败'):
            self.export(SECOND)
        path.write_bytes(original)
        cancel = threading.Event()
        with self.assertRaises(InterruptedError):
            self.export(SECOND, cancelled=cancel, progress=lambda *_: cancel.set())
        with patch('src.evidence.export.ZipFile.writestr', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.export(SECOND)
        self.assertEqual(export_state(self.repo, ACCOUNT)['cutoff'], FIRST)
        self.assertFalse(list(self.repo.root.parent.rglob('*.pending')))
        self.assertEqual(self.export(SECOND)['count'], 1)

    def test_receipt_failure_keeps_zip_and_retry_preserves_it(self):
        self.save()
        with patch.object(self.repo, 'set_preference', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, '续打包记录保存失败'):
                self.export()
        first = list(self.repo.root.parent.rglob('*.zip'))[0]
        self.assertEqual(export_state(self.repo, ACCOUNT), {})
        result = self.export()
        self.assertNotEqual(Path(result['path']), first)
        self.assertTrue(first.is_file())

    def test_zip_verification_failure_does_not_advance(self):
        self.save()
        with patch('src.evidence.export.ZipFile.testzip', return_value='broken.png'):
            with self.assertRaisesRegex(ValueError, '完整性校验失败'):
                self.export()
        self.assertEqual(export_state(self.repo, ACCOUNT), {})
        self.assertFalse(list(self.repo.root.parent.rglob('*.zip')))
        self.assertEqual(self.export()['count'], 1)

    def test_shared_image_confirmation_is_not_duplicated_and_private_metadata_is_excluded(self):
        row = self.save()
        from uuid import uuid4
        alias = dict(row, evidence_id=str(uuid4()), source='manual_confirmation',
                     completion_status='completed', login_password='PRIVATE_TEST_ONLY')
        with self.repo._connect() as db:
            db.execute('INSERT INTO evidence VALUES (?, ?, ?, ?, ?, 0, ?)',
                       (alias['evidence_id'], ACCOUNT, alias['project_id'], alias['captured_at'],
                        alias['period_id'], json.dumps(alias)))
        result = self.export()
        self.assertEqual(result['count'], 1)
        self.assertEqual(len(self.entries(result)), 1)

    def test_late_older_same_day_is_ignored_but_new_last_picture_is_exported(self):
        self.save()
        self.export()
        self.save(when='2026-10-01T11:00:00+08:00')
        self.assertEqual(self.export(SECOND)['count'], 0)
        last = self.save(when=SECOND)
        result = self.export(SECOND)
        self.assertEqual(result['count'], 1)
        self.assertTrue(self.entries(result)[0].endswith(Path(last['image_path']).name))
        self.repo.trash(last['evidence_id'])
        self.repo.permanently_delete(last['evidence_id'], confirmed=True)
        self.assertEqual(self.export(SECOND)['count'], 0)

    def test_beijing_calendar_day_not_four_am_game_period(self):
        self.save(when='2026-09-30T23:59:59+08:00', project='daily_activity')
        self.save(when='2026-10-01T03:59:59+08:00', project='daily_activity')
        last = self.save(when='2026-10-01T04:00:00+08:00', project='daily_activity')
        result = self.export()
        self.assertEqual(result['count'], 2)
        entries = self.entries(result)
        self.assertTrue(any(name.endswith(Path(last['image_path']).name) for name in entries))
        self.assertFalse(any('20261001-035959' in name for name in entries))

    def test_legacy_receipts_preserved_after_rule_change(self):
        row = self.save()
        self.repo.set_preference('screenshot_export:' + ACCOUNT, json.dumps(dict(
            cutoff=FIRST, images=[row['image_path']])))
        self.assertEqual(self.export(SECOND)['count'], 0)
        self.save(when=SECOND)
        result = self.export(SECOND)
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['state']['cutoff'], SECOND)

    def test_permanent_delete_waits_for_export_without_blocking_saves(self):
        row = self.save()
        self.repo.trash(row['evidence_id'])
        started, done = threading.Event(), threading.Event()
        def delete():
            started.set()
            EvidenceRepository(self.repo.root).permanently_delete(row['evidence_id'], confirmed=True)
            done.set()
        with asset_lock(self.repo.root):
            worker = threading.Thread(target=delete)
            worker.start()
            self.assertTrue(started.wait(1))
            self.assertFalse(done.wait(.05))
            self.save()
        worker.join(2)
        self.assertTrue(done.is_set())

    def test_ui_button_order_selected_account_freezing_and_open_failure(self):
        from PySide6.QtWidgets import QApplication
        from src.gui.CompletionCheckTab import CompletionCheckTab
        app = QApplication.instance() or QApplication([])
        self.save()
        page = CompletionCheckTab(SimpleNamespace(), self.repo, lambda: None)
        page.timer.stop()
        try:
            page._selected = ACCOUNT
            page._profiles = {ACCOUNT: 'A1-昵称-199****0001'}
            page._nicknames = {ACCOUNT: '昵称'}
            actions = page.export_button.parent().layout().itemAt(2).layout()
            self.assertLess(actions.indexOf(page.export_button), actions.indexOf(page.capture_button))
            with patch.object(page.export_operation, 'start') as start:
                page.export_account_screenshots()
                work, loaded, failed = start.call_args.args
                page._selected = OTHER
                result = work()
                with patch('src.gui.CompletionCheckTab.subprocess.Popen', side_effect=OSError('unavailable')):
                    loaded(result)
                self.assertIn('打开文件夹失败', page.export_status.text())
                self.assertTrue(Path(result['path']).exists())
                self.assertEqual(export_state(self.repo, OTHER), {})
                self.assertEqual(export_state(self.repo, ACCOUNT)['count'], 1)
        finally:
            page.service.close()
            page.deleteLater()
            app.processEvents()


if __name__ == '__main__':
    unittest.main()
