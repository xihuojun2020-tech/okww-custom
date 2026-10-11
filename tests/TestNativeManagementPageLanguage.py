"""Real offscreen widgets and English catalogs, without scheduler or maintenance IO."""
import gettext
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtWidgets import QApplication, QPushButton

from src.gui.NativeMaintenanceTab import NativeMaintenanceTab
from src.gui.NativeScheduleTab import NativeScheduleTab
from src.runtime import native_language


class TestNativeManagementPageLanguage(unittest.TestCase):
    def test_english_controls_status_and_untranslated_user_data(self):
        app = QApplication.instance() or QApplication([])
        catalogs = Path(__file__).resolve().parents[1] / 'i18n'
        language = native_language.NativeLanguage('en_US', 'en_US', catalogs,
            gettext.translation('native', localedir=catalogs, languages=['en_US']))
        backend = Mock(user='用户原样', package='包路径原样', data_dir='资料路径原样')
        backend.launcher_device.return_value = {'type': 'windows', 'title': '窗口原样'}
        backend.list.return_value = [dict(name='fixture', binding={'task_id': '任务ID原样', 'trigger': 'daily'},
            next_run='tomorrow', last_result=0, requires_migration=False)]
        service = Mock()
        service.paths.return_value = {key: Path('用户路径原样') / key for key in ('data', 'configs', 'backups')}
        coordinate = Mock()
        widgets = []
        with patch.object(native_language, '_active', language):
            try:
                schedule = NativeScheduleTab('unused', 'unused', backend=backend)
                maintenance = NativeMaintenanceTab(service, coordinate)
                widgets = [schedule, maintenance]
                for widget in widgets: widget.show()
                app.processEvents()
                for widget, sources in ((schedule, ('刷新', '创建/更新')),
                                        (maintenance, ('创建完整备份', '验证备份'))):
                    visible = {button.text() for button in widget.findChildren(QPushButton) if button.isVisible()}
                    for source in sources:
                        translated = language.translate(source)
                        self.assertNotEqual(translated, source)
                        self.assertIn(translated, visible)
                self.assertEqual(schedule.device.toPlainText(), '{"type": "windows", "title": "窗口原样"}')
                schedule.refresh()
                row_source = '{task} | {trigger} | {next_run} | 结果 {last_result}'
                self.assertNotEqual(language.translate(row_source), row_source)
                self.assertEqual(schedule.items.item(0).text(), language.translate(row_source).format(
                    task='任务ID原样', trigger='daily', next_run='tomorrow', last_result=0))
                self.assertEqual(maintenance.status.text(), language.translate('等待操作。'))
                self.assertIsNone(maintenance._selected())
                self.assertEqual(maintenance.status.text(), language.translate('请先选择备份目录。'))
                maintenance._verified(SimpleNamespace(ok=True, files=('用户文件原样',)))
                verified_source = '备份验证通过：{count}个文件。'
                self.assertNotEqual(language.translate(verified_source), verified_source)
                self.assertEqual(maintenance.status.text(), language.translate(verified_source).format(count=1))
                coordinate.assert_not_called()
                service.create_snapshot.assert_not_called()
                service.restore.assert_not_called()
                service.cleanup.assert_not_called()
            finally:
                for widget in widgets: widget.close()
                app.processEvents()


if __name__ == '__main__':
    unittest.main()
