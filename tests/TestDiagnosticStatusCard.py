import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from src.gui.DiagnosticStatusCard import DiagnosticStatusCard, diagnostic_error_message, diagnostic_status_text, format_archive_progress


class TestDiagnosticStatusCard(unittest.TestCase):
    def test_progress_formats_speed_and_eta(self):
        text = format_archive_progress({'mode':'automatic','day':'2026-09-15','stage':'uploading',
            'copied':650117120,'total':1621932239,'speed_bps':19451084,
            'average_speed_bps':18126322,'elapsed_seconds':35.8,'eta_seconds':49.9})
        self.assertIn('自动上传：2026-09-15', text)
        self.assertIn('MiB/s', text)
        self.assertIn('预计剩余：50 秒', text)

    def test_progress_formats_packing_batches(self):
        text = format_archive_progress({'mode':'manual','day':'2026-09-16','stage':'packing',
                                        'completed_batches':1250,'total_batches':1840})
        self.assertIn('批次：1250 / 1840', text)
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait(self, widget):
        deadline = time.monotonic() + 5
        while widget.operation.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertFalse(widget.operation.busy)

    def test_settings_and_retry_only_touch_local_state(self):
        with tempfile.TemporaryDirectory() as temp, patch('src.gui.DiagnosticStatusCard.default_root', return_value=Path(temp)), patch('src.gui.DiagnosticStatusCard.wake_uploader') as wake:
            card = DiagnosticStatusCard()
            try:
                card.timer.stop()
                self.wait(card)
                self.assertFalse(hasattr(card, 'enabled'))
                card.target.setText(str(Path(temp) / 'remote'))
                card.save()
                self.wait(card)
                self.assertTrue(json.loads((Path(temp) / 'settings.json').read_text())['enabled'])
                states = Path(temp) / 'states'
                states.mkdir()
                for state in ('blocked', 'retrying'):
                    (states / (state + '.json')).write_text(json.dumps({'status': state, 'next_retry': 123}))
                with patch('src.runtime.diagnostic_archive.manual_upload', return_value='synthetic.zip') as upload:
                    card.retry()
                    self.wait(card)
                    upload.assert_called_once_with(Path(temp))
                self.assertEqual(json.loads((states / 'blocked.json').read_text())['next_retry'], 123)
                self.assertEqual(json.loads((states / 'retrying.json').read_text())['next_retry'], 123)
                self.assertTrue(wake.called)
                (states / 'retrying.json').write_text(json.dumps({'status': 'retrying', 'next_retry': 123}))
                card.password.setText('not-a-real-password')
                with patch('src.gui.DiagnosticStatusCard.save_credentials') as save_credentials:
                    card.save()
                    self.wait(card)
                self.assertTrue(save_credentials.called)
                self.assertEqual(json.loads((states / 'retrying.json').read_text())['next_retry'], 0)
            finally:
                card.deleteLater()
                self.app.processEvents()

    def test_upload_errors_have_actionable_messages(self):
        self.assertIn('重启程序', diagnostic_error_message("No module named 'win32timezone'"))
        self.assertIn('重新填写密码', diagnostic_error_message('NAS authentication failed, Windows code 86'))

    def test_collection_warning_does_not_replace_upload_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            batch = root / 'run' / 'batches' / 'batch'
            batch.mkdir(parents=True)
            (batch / '_READY').touch()
            states = root / 'states'
            states.mkdir()
            (states / 'run--batch.json').write_text(json.dumps({
                'status': 'retrying', 'last_error': 'SMB worker timed out'}), encoding='utf-8')
            (root / 'collector-error.json').write_text(json.dumps({
                'error': 'image file is truncated'}), encoding='utf-8')
            status = diagnostic_status_text(root)
            self.assertIn('最近上传错误：SMB worker timed out', status)
            self.assertIn('最近采集警告：image file is truncated', status)

    def test_scheduler_status_distinguishes_cache_from_system_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'scheduler.json').write_text(json.dumps({'status': 'installed'}))
            self.assertIn('已缓存（未验证系统任务）', diagnostic_status_text(root))
            (root / 'scheduler.json').write_text(json.dumps({
                'status': 'installed', 'system_verified': True}))
            self.assertIn('已由系统验证', diagnostic_status_text(root))

    def test_capture_status_distinguishes_missing_frames_from_upload_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run = root / 'run'
            run.mkdir()
            (run / 'evidence-status.json').write_text(json.dumps({
                'updated_at': time.time(), 'ring_frames': 3, 'warning': 'stale_frame'}))
            text = diagnostic_status_text(root)
            self.assertIn('已缓存 3 张', text)
            self.assertIn('画面未更新', text)
            self.assertIn('最近上传错误：无', text)

    def test_manual_capture_only_queues_diagnostics(self):
        from unittest.mock import Mock
        from src.runtime import diagnostic_lifecycle
        with tempfile.TemporaryDirectory() as temp, patch('src.gui.DiagnosticStatusCard.default_root', return_value=Path(temp)):
            card = DiagnosticStatusCard()
            try:
                card.timer.stop()
                self.wait(card)
                session = Mock(closed_session=False)
                with patch.object(diagnostic_lifecycle, '_session', session):
                    card.test_capture()
                self.assertEqual(session.record_error.call_args.args[0]['source'], 'manual_test')
                session.record_event.assert_called_once()
                self.assertIn('已触发截图测试', card.status.text())
            finally:
                card.deleteLater()
                self.app.processEvents()

    def test_navigation_status_uses_existing_theme_and_bounded_recent_rows(self):
        from src.runtime import navigation_status as nav
        from src.gui.CodexTheme import apply_codex_light_theme
        from PySide6.QtGui import QFont, QFontDatabase
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
        apply_codex_light_theme(self.app)
        self.app.setFont(QFont('Microsoft YaHei', 10))
        with tempfile.TemporaryDirectory() as temp, patch('src.gui.DiagnosticStatusCard.default_root', return_value=Path(temp)):
            card=DiagnosticStatusCard()
            try:
                self.wait(card)
                card.timer.stop(); card.navigation_timer.stop()
                with patch.object(nav, '_recent', __import__('collections').deque(maxlen=30)):
                    for index in range(40):
                        nav.publish(str(index), '若梦仍有回声', '单人挑战', '等待切页', 1, 2.4, 15.6, max_attempts=2)
                    self.assertEqual(len(nav.snapshot()),30)
                    from PySide6.QtWidgets import QWidget, QVBoxLayout
                    host=QWidget();host.setStyleSheet('background: white;')
                    layout=QVBoxLayout(host);layout.addWidget(card);layout.addStretch()
                    card.set_expanded(True);host.resize(900,950);host.show();self.app.processEvents()
                    card.refresh_navigation();self.app.processEvents()
                    self.assertIn('1/2 次',card.navigation_status.text())
                    self.assertEqual(card.navigation_status.text().count('单人挑战'),5)
                    Path('test_out').mkdir(exist_ok=True)
                    host.layout().activate();card.layout().activate();card.content_layout.activate()
                    self.app.processEvents()
                    host.grab().save('test_out/navigation-status-card.png')
                    host.close()
            finally:
                card.close();card.deleteLater();self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
