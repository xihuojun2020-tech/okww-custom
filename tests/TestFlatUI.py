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

    def test_fluent_sample_description_and_actions(self):
        from ok.gui.tasks.TaskCard import TaskCard
        from PySide6.QtTest import QTest
        for sample in (False, True):
            with self.subTest(sample=sample), \
                 patch.object(og, 'app', SimpleNamespace(tr=str, start_controller=SimpleNamespace(start=Mock()))), \
                 patch.object(og, 'executor', SimpleNamespace(waiting_for_task=lambda _: '')):
                task = example_task()
                card = TaskCard(task, True, fluent_sample=sample)
                card.resize(760, 500)
                card.show()
                self.app.processEvents()
                self.assertFalse(card.isExpand)
                self.assertEqual(card.card.contentLabel.isVisible(), sample)
                self.assertEqual(card.objectName(), 'fluentTaskSample' if sample else 'configSection')
                QTest.mouseClick(card.start_button, Qt.LeftButton)
                og.app.start_controller.start.assert_called_once_with(task)
                self.assertFalse(card.isExpand)
                QTest.mouseClick(card.card.titleLabel, Qt.LeftButton)
                self.assertTrue(card.isExpand)
                QTest.mouseClick(card.card.contentLabel, Qt.LeftButton)
                self.assertEqual(card.isExpand, not sample)
                card.setExpand(True)
                QTest.mouseClick(card.config_widget_by_key['目标'], Qt.LeftButton)
                self.assertTrue(card.isExpand)
                task.enabled, task.running = True, True
                card.update_buttons(task)
                self.app.processEvents()
                QTest.mouseClick(card.pause_button, Qt.LeftButton)
                QTest.mouseClick(card.stop_button, Qt.LeftButton)
                task.pause.assert_called_once()
                task.disable.assert_called_once()
                self.assertTrue(card.isExpand)
                card.close()
                card.deleteLater()

    def test_fluent_sample_only_enabled_on_task_hub(self):
        from src.gui.TaskHubTab import TaskHubTab
        from ok.gui.tasks.OneTimeTaskTab import OneTimeTaskTab
        task = example_task()
        with patch.object(og, 'app', SimpleNamespace(tr=str)), \
             patch.object(og, 'executor', SimpleNamespace(onetime_tasks=[task], current_task=None,
                                                        waiting_for_task=lambda _: '')), \
             patch.object(og, 'task_manager', SimpleNamespace(imported_scripts={})):
            hub = TaskHubTab()
            legacy = OneTimeTaskTab(section='tasks')
            self.assertEqual(hub.task_tab.card_widgets[0].objectName(), 'fluentTaskSample')
            self.assertEqual(legacy.card_widgets[0].objectName(), 'configSection')
            hub.task_tab.card_widgets[0].setExpand(True)
            hub.task_tab.refresh_ui()
            self.assertTrue(hub.task_tab.card_widgets[0].isExpand)
            for widget in (hub.task_tab, legacy):
                widget.timer.stop()
            hub.deleteLater()
            legacy.deleteLater()

    def test_fluent_description_only_has_no_empty_disclosure(self):
        from ok.gui.tasks.TaskCard import TaskCard
        task = example_task('🎮 测试任务')
        task.config = MemoryConfig()
        task.default_config = {}
        task.config_type = {}
        with patch.object(og, 'app', SimpleNamespace(tr=str)), \
             patch.object(og, 'executor', SimpleNamespace(waiting_for_task=lambda _: '')):
            card = TaskCard(task, True, fluent_sample=True)
            self.assertTrue(card.card.expandButton.isHidden())
            card.setExpand(True)
            self.assertFalse(card.isExpand)
            self.assertEqual(card.card.titleLabel.text(), '测试任务')
            self.assertEqual(task.name, '🎮 测试任务')
            card.deleteLater()

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
            self.assertFalse(card.isExpand)
            card.setExpand(True)
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
            card.setExpand(False)
            task.running = True
            task.enabled = True
            card.update_buttons(task)
            card.update_config()
            self.app.processEvents()
            self.assertFalse(card.isExpand)
            self.assertTrue(card.stop_button.isVisible())
            self.assertEqual(task.config['目标'], '测试首领')
            card.setExpand(True)
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

    def test_header_clicks_and_actions_are_independent(self):
        from ok.gui.tasks.TaskCard import TaskCard
        from PySide6.QtTest import QTest
        controller = SimpleNamespace(start=Mock())
        with patch.object(og, 'app', SimpleNamespace(tr=str, start_controller=controller)), \
             patch.object(og, 'executor', SimpleNamespace(waiting_for_task=lambda _: '')):
            task = example_task()
            card = TaskCard(task, True)
            card.resize(700, 500)
            card.show()
            self.app.processEvents()
            self.assertFalse(card.isExpand)
            card.start_button.setEnabled(False)
            QTest.mouseClick(card.start_button, Qt.LeftButton)
            self.assertFalse(card.isExpand)
            card.start_button.setEnabled(True)
            QTest.mouseClick(card.start_button, Qt.LeftButton)
            controller.start.assert_called_once_with(task)
            self.assertFalse(card.isExpand)
            QTest.mouseClick(card.card, Qt.LeftButton, pos=QPoint(8, 8))
            self.assertTrue(card.isExpand)
            QTest.mouseClick(card.card.titleLabel, Qt.LeftButton)
            self.assertFalse(card.isExpand)
            QTest.keyClick(card.card.expandButton, Qt.Key_Space)
            self.assertTrue(card.isExpand)
            QTest.mouseClick(card.card.contentLabel, Qt.LeftButton)
            self.assertTrue(card.isExpand)
            QTest.mouseClick(card.card.expandButton, Qt.LeftButton)
            self.assertFalse(card.isExpand)
            task.enabled, task.running = True, True
            card.update_buttons(task)
            self.app.processEvents()
            QTest.mouseClick(card.pause_button, Qt.LeftButton)
            task.pause.assert_called_once()
            self.assertFalse(card.isExpand)
            QTest.mouseClick(card.stop_button, Qt.LeftButton)
            task.disable.assert_called_once()
            self.assertFalse(card.isExpand)
            card.close()
            card.deleteLater()

    def test_disclosure_preserves_values_and_reveals_errors(self):
        from src.gui.SectionPanel import SectionPanel
        from PySide6.QtWidgets import QLineEdit, QToolButton
        from PySide6.QtTest import QTest
        sections = [SectionPanel('高级配置', collapsible=True) for _ in range(2)]
        for section in sections:
            field = QLineEdit('保留草稿')
            row = section.add_row('名称', field)
            section.show()
            self.app.processEvents()
            self.assertFalse(field.isVisible())
            QTest.keyClick(section.toggle_button, Qt.Key_Space)
            self.assertTrue(section.toggle_button.isChecked())
            self.assertTrue(field.isVisible())
            section.set_expanded(False)
            row.set_error('请检查名称')
            self.assertTrue(section.toggle_button.isChecked())
            self.assertEqual(field.text(), '保留草稿')
            self.assertEqual(field.accessibleName(), '名称')
            self.assertIs(row.label.buddy(), field)
            self.assertFalse(section.findChildren(QAbstractScrollArea))
        self.assertTrue(all(section.toggle_button.isChecked() for section in sections))
        for section in sections:
            section.close()
            section.deleteLater()

    def test_task_list_refresh_preserves_expansion(self):
        from ok.gui.tasks.OneTimeTaskTab import OneTimeTaskTab
        task = example_task()
        with patch.object(og, 'app', SimpleNamespace(tr=str)), \
             patch.object(og, 'executor', SimpleNamespace(onetime_tasks=[task], current_task=None,
                                                        waiting_for_task=lambda _: '')), \
             patch.object(og, 'task_manager', SimpleNamespace(imported_scripts={})):
            tab = OneTimeTaskTab(section='tasks')
            tab.card_widgets[0].setExpand(True)
            tab.refresh_ui()
            self.assertTrue(tab.card_widgets[0].isExpand)
            tab.timer.stop()
            tab.deleteLater()

    def test_category_headers_filter_hidden_tasks_and_survive_refresh(self):
        from ok.gui.tasks.OneTimeTaskTab import OneTimeTaskTab
        from ok.gui.tasks.TriggerTaskTab import TriggerTaskTab
        def sample(name, section='tasks', visible=True):
            task = type(name, (), {})()
            task.__dict__.update(vars(example_task()))
            task.navigation_section, task.visible = section, visible
            return task
        daily, weekly, hidden = sample('DailyTask'), sample('WeeklyBossTask'), sample('TacetTask', visible=False)
        experiment, activity = sample('AutoAbyssTask', 'tests'), sample('EventTask', 'activities')
        activity.activity_category = '常驻活动'
        helper = sample('AutoCombatTask')
        helper.enabled = True
        helper.enable = Mock()
        with patch.object(og, 'app', SimpleNamespace(tr=str)), \
                patch.object(og, 'executor', SimpleNamespace(onetime_tasks=[weekly, experiment, hidden, activity, daily],
                    trigger_tasks=[helper], current_task=None, waiting_for_task=lambda _: '')), \
                patch.object(og, 'task_manager', SimpleNamespace(imported_scripts={})):
            tasks = OneTimeTaskTab(section='tasks', group_tasks=True)
            tools = OneTimeTaskTab(section='tests')
            helpers = TriggerTaskTab()
            self.assertEqual([card.task for card in tasks.card_widgets], [daily, weekly, activity])
            self.assertEqual([label.text() for label in tasks._category_labels], ['每日执行', '每周任务', '活动'])
            self.assertEqual([card.task for card in tools.card_widgets], [experiment])
            helpers.card_widgets[0].setExpand(True)
            tasks.refresh_ui()
            helpers.refresh_ui()
            self.assertEqual(len(tasks._category_labels), 3)
            self.assertEqual([label.text() for label in helpers._category_labels], ['战斗与拾取'])
            self.assertTrue(helpers.card_widgets[0].isExpand)
            self.assertTrue(helper.enabled)
            helper.enable.assert_not_called()
            helper.disable.assert_not_called()
            helpers.card_widgets[0].enable_button.setChecked(False)
            helper.disable.assert_called_once()
            for tab in (tasks, tools, helpers):
                tab.timer.stop()
                tab.deleteLater()

    def test_settings_header_action_and_account_groups(self):
        from src.gui.FlatSettingGroup import FlatActionSettingCard
        from PySide6.QtTest import QTest
        card = FlatActionSettingCard('导出', None, '账号配置', '范围说明')
        callback = Mock()
        card.clicked.connect(callback)
        card.show()
        self.app.processEvents()
        QTest.mouseClick(card.control, Qt.LeftButton)
        callback.assert_called_once()
        self.assertFalse(card.toggle_button.isChecked())
        QTest.mouseClick(card.header, Qt.LeftButton, pos=QPoint(8, 8))
        self.assertTrue(card.toggle_button.isChecked())
        card.deleteLater()
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(Path(temp))
            tab = AccountConfigTab(AccountConfigEditor(env.repository))
            self.assertTrue(all(not section.toggle_button.isChecked() for section in tab.form_sections.values()))
            self.assertEqual(tab.form_sections[1].title, '清理体力')
            self.assertEqual(tab.form_sections[2].title, '周本挑战')
            self.assertTrue(tab.form_sections[2].isAncestorOf(tab.form_widgets['Weekly Boss Target']))
            self.assertFalse(tab.form_sections[1].isAncestorOf(tab.form_widgets['Weekly Boss Target']))
            tab.deleteLater()

    def test_connection_summary_keeps_hotkey_failure_visible(self):
        from ok.gui.start.StartCard import StartCard
        header = Mock()
        card = SimpleNamespace(disclosure_header=header, hotkey_warning=QLabel('快捷键注册失败'),
                               current_hotkey=None, start_button=Mock(), status_bar=Mock(), tr=str)
        with patch.object(og, 'executor', SimpleNamespace(paused=True)), \
             patch.object(og, 'device_manager', SimpleNamespace(get_preferred_device=lambda: {'connected': True})):
            StartCard.update_status(card)
        self.assertIn('快捷键注册失败', header.set_summary.call_args.args[0])

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

    def test_account_form_refresh_preserves_disclosure(self):
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(Path(temp))
            tab = AccountConfigTab(AccountConfigEditor(env.repository))
            self.assertFalse(tab.form_sections[1].toggle_button.isChecked())
            tab.form_sections[1].set_expanded(True)
            tab._render_form()
            self.assertTrue(tab.form_sections[1].toggle_button.isChecked())
            self.assertFalse(tab.identity_group.toggle_button.isChecked())
            tab.deleteLater()

    def test_small_screen_window_geometry_stays_reachable(self):
        from custom_ok.ok.gui.MainWindow import MainWindow
        from PySide6.QtCore import QRect
        window = SimpleNamespace(screen=Mock(), ok_config={
            'window_width': 1600, 'window_height': 1000, 'window_x': 4000,
            'window_y': 2000, 'window_maximized': False},
            setMinimumSize=Mock(), setGeometry=Mock(), apply_navigation_state=Mock())
        screen = QRect(1920, 0, 960, 540)
        with patch('custom_ok.ok.gui.MainWindow.QScreen.availableGeometry', return_value=screen):
            MainWindow.set_window_size(window, 1200, 800, 1200, 800)
        minimum = window.setMinimumSize.call_args.args[0]
        self.assertLessEqual(minimum.width(), screen.width())
        self.assertLessEqual(minimum.height(), screen.height())
        geometry = QRect(*window.setGeometry.call_args.args)
        self.assertTrue(screen.contains(geometry))

    def test_account_categories_keep_values_and_identity_controls_unique(self):
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(Path(temp))
            tab = AccountConfigTab(AccountConfigEditor(env.repository))
            tab.draft.tasks.update({'Weekly Garden Check Day': 'Monday', 'Merge Echo on Sunday': True,
                                    'Logout After Daily Task': True, 'Weekly Boss Target': '无',
                                    '备用识别名称': True, '备用识别名称内容': 'fixture'})
            before = dict(tab.draft.tasks)
            tab._render_form()
            for index, title in ((1, '清理体力'), (2, '周本挑战'), (3, '周常安排'), (4, '收尾行为')):
                section = tab.form_sections[index]
                self.assertEqual(section.title_label.text(), title)
                self.assertFalse(section.toggle_button.isChecked())
            for key in ('Weekly Garden Check Day', 'Merge Echo on Sunday'):
                self.assertTrue(tab.form_sections[3].isAncestorOf(tab.form_widgets[key]))
            self.assertTrue(tab.form_sections[4].isAncestorOf(tab.form_widgets['Logout After Daily Task']))
            self.assertTrue(tab.identity_group.isAncestorOf(tab.form_widgets['备用识别名称内容']))
            self.assertEqual(tab.draft.tasks, before)
            tab.deleteLater()

    def test_task_management_buttons_navigate_without_mutating_task_metadata_or_draft(self):
        from ok.gui.tasks.TaskCard import TaskCard
        for name, key, callback in (('DailyTask', 'Manage Daily Profiles', 'open_account_editor'),
                                    ('MultiAccountDailyTask', '管理序列', 'open_sequence_editor')):
            task = type(name, (), {})()
            task.__dict__.update(vars(example_task()))
            original = dict(task.config_type)
            draft = object()
            window = SimpleNamespace(navigate_tab=Mock(), account_settings_tab=SimpleNamespace(
                account_tab=SimpleNamespace(profile_combo=QLabel(), draft=draft), section_panels=[QLabel(), QLabel()]))
            with patch.object(og, 'app', SimpleNamespace(tr=str)), \
                    patch.object(og, 'executor', SimpleNamespace(waiting_for_task=lambda _: '')), \
                    patch.object(og, 'main_window', window), patch('src.gui.SectionPanel.reveal_widget') as reveal:
                card = TaskCard(task, True)
                self.assertIn(key, card.config_widget_by_key)
                card.config_type[key]['callback']()
                window.navigate_tab.assert_called_once_with('accounts')
                reveal.assert_called_once()
                self.assertEqual(task.config_type, original)
                self.assertIs(window.account_settings_tab.account_tab.draft, draft)
                self.assertFalse(card.isExpand)
                card.deleteLater()

    def test_auto_combat_manual_control_is_not_called_by_state_refresh(self):
        from ok.gui.tasks.TaskCard import TaskCard
        task = example_task('自动战斗')
        task.set_enabled_from_ui = Mock()
        task.recovery_status = '手动保持开启'
        task.enabled = True
        with patch.object(og, 'app', SimpleNamespace(tr=str)), \
                patch.object(og, 'executor', SimpleNamespace(waiting_for_task=lambda _: '')):
            card = TaskCard(task, False)
            card.update_buttons(task)
            task.set_enabled_from_ui.assert_not_called()
            self.assertIn('手动保持开启', card.state_label.text())
            card.enable_button.setChecked(False)
            task.set_enabled_from_ui.assert_called_once_with(False)
            card.deleteLater()


if __name__ == '__main__':
    unittest.main()
