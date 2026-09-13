import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import time
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase
from src.gui.DiagnosticDetails import DiagnosticDetails


class TestDiagnosticDetailsUI(unittest.TestCase):
    def test_refresh_preserves_identity_and_missing_screenshot_status(self):
        app = QApplication.instance() or QApplication([])
        font_file = Path('C:/Windows/Fonts/msyh.ttc')
        if font_file.exists():
            QFontDatabase.addApplicationFont(str(font_file))
        app.setFont(QFont('Microsoft YaHei', 10))
        with tempfile.TemporaryDirectory() as temp:
            dialog = DiagnosticDetails(Path(temp))
            dialog.timer.stop()
            deadline = time.monotonic() + 5
            while dialog.operation.busy and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            self.assertFalse(dialog.operation.busy)
            event = dict(incident_id='test-event', triggered_at='2026-09-13T15:04:23',
                version='test', triggers=[{'message':'示例：活跃度校验失败，备用转换已取消'}],
                state='incomplete', upload_status='partial', incomplete_reasons=['post_frames_missing'],
                frames=[dict(phase='pre', relative_seconds=-1.1, observed_at='15:04:21.9',
                             freshness='fresh', upload_status='missing')])
            snapshot = dict(updated_at=time.time(), pending_bytes=1024, counts={'retrying':1},
                warnings=[], scheduler={}, collector={}, sources=[], files=[], batches=[], incidents=[event])
            dialog.loaded(snapshot)
            dialog.tabs.setCurrentIndex(1)
            dialog.tables[1].selectRow(0)
            self.assertEqual('test-event', dialog.selected()['incident_id'])
            dialog.loaded(dict(snapshot, incidents=[dict(event, incident_id='new'), event]))
            self.assertEqual('test-event', dialog.selected()['incident_id'])
            self.assertIn('错误后截图缺失', dialog.detail.toPlainText())
            self.assertEqual('未找到封存文件', dialog.timeline.item(0,4).text())
            dialog.show()
            app.processEvents()
            output=Path('test_out/diagnostic-details-ui.png')
            output.parent.mkdir(exist_ok=True)
            self.assertTrue(dialog.grab().save(str(output)))
            dialog.close()
            dialog.deleteLater()
            app.processEvents()


if __name__ == '__main__':
    unittest.main()
