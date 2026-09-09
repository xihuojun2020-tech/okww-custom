import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QAbstractScrollArea, QDialog, QPlainTextEdit, QScrollBar, QSpinBox, QLabel, QPushButton
from ok import og
from src.gui.CodexTheme import apply_codex_light_theme
from src.gui.FlatChoiceList import FlatChoiceList
from src.gui.AccountConfigTab import AccountConfigTab
from src.account_config_editor import AccountConfigEditor
from tests.fixture_support import make_account_environment


class MemoryConfig(dict):
    def has_user_config(self): return True
    def get_default(self, key): return self.get(key)


def example_task(name='周本挑战'):
    config = MemoryConfig({'目标': '无', '挑战次数': 3, '备注': '用于验证长说明不会挤占任务按钮或者导致横向滚动。'})
    return SimpleNamespace(name=name, description='任务说明与参数自然换行；不连接游戏。', config=config,
        default_config=dict(config), config_description={'目标': '每个账号可分别配置。'},
        config_type={'目标': {'type': 'drop_down', 'options': ['无', '测试首领'],
                              'sub_configs': {'测试首领': ['挑战次数']}}}, icon=None,
        show_create_shortcut=False, enabled=False, paused=False, running=False,
        instructions='', first_run_alert='', navigation_section='tasks', group_name=None,
        start_time=0, info={}, disable=Mock(), unpause=Mock(), pause=Mock())


class TestFlatUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_codex_light_theme(cls.app)

    def test_choices_have_no_visible_scroll_area_and_keep_callbacks(self):
        widget = FlatChoiceList()
        widget.addItem('WGC')
        widget.addItem('BitBlt RenderFull')
        callback = Mock()
        widget.itemSelectionChanged.connect(callback)
        widget.resize(500, 160)
        widget.show()
        widget.group.button(1).click()
        self.assertEqual(widget.currentRow(), 1)
        callback.assert_called_once()
        self.assertFalse(widget.source.isVisible())
        widget.item(1).setText('更新后的采集方式')
        self.assertEqual(widget.group.button(1).text(), '更新后的采集方式')
        widget.close()
        widget.deleteLater()

    def test_wheel_over_spinbox_scrolls_page_without_changing_value(self):
        from ok.gui.widget.Tab import Tab
        page = Tab()
        spin = QSpinBox()
        spin.setValue(5)
        page.add_widget(spin)
        label = QLabel('内容')
        label.setMinimumHeight(1500)
        page.add_widget(label)
        page.resize(700, 400)
        page.show()
        self.app.processEvents()
        event = QWheelEvent(QPointF(10, 10), QPointF(spin.mapToGlobal(QPoint(10, 10))),
                            QPoint(), QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(spin, event)
        for _ in range(5): self.app.processEvents()
        self.assertEqual(spin.value(), 5)
        self.assertGreater(page.verticalScrollBar().value(), 0)
        page.close()
        page.deleteLater()

    def test_task_config_natural_height_and_conditional_fields(self):
        from ok.gui.tasks.TaskCard import TaskCard
        task = example_task()
        callback = Mock()
        task.config_type['管理配置'] = {'type': 'button', 'text': '管理配置', 'callback': callback}
        with patch.object(og, 'app', SimpleNamespace(tr=str)), \
             patch.object(og, 'executor', SimpleNamespace(waiting_for_task=lambda _: '')):
            card = TaskCard(task, True)
            self.assertNotIsInstance(card, QAbstractScrollArea)
            card.resize(700, 500)
            card.show()
            self.app.processEvents()
            child = card.config_widget_by_key['挑战次数']
            self.assertTrue(child.isHidden())
            card.config_widget_by_key['目标'].combo_box.setCurrentIndex(1)
            self.app.processEvents()
            self.assertFalse(child.isHidden())
            self.assertEqual(task.config['目标'], '测试首领')
            card.pause_clicked()
            task.pause.assert_called_once()
            card.stop_clicked()
            task.disable.assert_called_once()
            action = card.config_widget_by_key['管理配置']
            button = action.findChild(QPushButton)
            self.assertIsNotNone(button)
            self.assertTrue(button.isVisible())
            self.assertTrue(action.rect().contains(button.mapTo(action, button.rect().center())))
            button.click()
            callback.assert_called_once()
            self.assertFalse(any(bar.isVisible() and bar.maximum() > 0 for bar in card.findChildren(QScrollBar)))
            card.close()
            card.deleteLater()

    def test_account_json_cancel_and_apply_preserve_save_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(Path(temp))
            tab = AccountConfigTab(AccountConfigEditor(env.repository))
            original = dict(tab.draft.tasks)
            def cancel(dialog):
                dialog.findChild(QPlainTextEdit).setPlainText('{}')
                return QDialog.Rejected
            with patch.object(QDialog, 'exec', cancel):
                tab.edit_json()
            self.assertEqual(tab.draft.tasks, original)
            updated = dict(original, **{'Which to Farm': 'Forgery Challenge'})
            def accept(dialog):
                dialog.findChild(QPlainTextEdit).setPlainText(json.dumps(updated))
                return QDialog.Accepted
            with patch.object(QDialog, 'exec', accept):
                tab.edit_json()
            self.assertEqual(tab.draft.tasks['Which to Farm'], 'Forgery Challenge')
            self.assertNotEqual(tab.editor.load_draft(tab.draft.profile_id).tasks, tab.draft.tasks)
            self.assertTrue(tab.task_editor.isHidden())
            tab.deleteLater()


if __name__ == '__main__':
    unittest.main()
