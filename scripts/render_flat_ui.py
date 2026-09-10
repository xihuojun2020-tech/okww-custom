"""Render actual project pages using synthetic accounts and inert device services."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile
import threading
import time
import json
import gettext
import importlib
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication, QWidget, QScrollBar, QPushButton, QLabel, QAbstractButton, QComboBox
from PySide6.QtCore import QPoint, QTranslator, QLocale, QCoreApplication
from qfluentwidgets import FluentTranslator, ComboBox
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtGui import QIcon
from ok import og
from tests.TestFlatUI import MemoryConfig, example_task
from tests.fixture_support import make_account_environment
from src.gui.CodexTheme import apply_codex_light_theme


class InertConfig(MemoryConfig):
    def save_file(self): pass


def audit_texts(widget):
    """Export synthetic UI labels/options, including collapsed content, for review."""
    texts = set()
    for control in [widget, *widget.findChildren(QWidget)]:
        if isinstance(control, (QLabel, QAbstractButton)):
            texts.add(control.text())
        if isinstance(control, (QComboBox, ComboBox)):
            texts.update(control.itemText(i) for i in range(control.count()))
        texts.add(control.toolTip())
        if control.isWindow():
            texts.add(control.windowTitle())
    return sorted(text for text in texts if text.strip())


def render(output):
    app = QApplication.instance() or QApplication([])
    # Windows offscreen plugin has no automatic system-font fallback.
    for font in ('msyh.ttc', 'segoeui.ttf', 'seguiemj.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / font))
    app.setFont(QFont('Microsoft YaHei', 10))
    from ok.gui import resources
    fluent_translator = FluentTranslator(QLocale('zh_CN'))
    app.installTranslator(fluent_translator)
    translator = QTranslator(app)
    if translator.load('zh_CN', ':/i18n'):
        app.installTranslator(translator)
    catalog = gettext.translation('ok', localedir=Path(__file__).resolve().parents[1] / 'i18n', languages=['zh_CN'])
    apply_codex_light_theme(app)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
        env = make_account_environment(Path(temp))
        task = example_task()
        device = {'device': 'windows', 'connected': True, 'nick': '测试游戏窗口',
                  'address': '模拟设备', 'resolution': '1920×1080', 'imei': 'fake'}
        manager = SimpleNamespace(config={'preferred': 'fake', 'interaction': 'PostMessage'},
            windows_capture_config={'capture_method': ['WGC', 'BitBlt_RenderFull'], 'interaction': ['PostMessage', 'SendInput']},
            get_preferred_device=lambda: device, get_devices=lambda: [device],
            get_preferred_capture=lambda: 'WGC', set_capture=Mock(), set_interaction=Mock(),
            set_preferred_device=Mock(), refresh=Mock())
        from config import config, version
        from ok.util.GlobalConfig import basic_options, create_notification_options
        options = config['global_configs'] + [basic_options, create_notification_options()]
        global_entries = [(option.name, MemoryConfig(option.default_config), option) for option in options]
        configs = {name: value for name, value, _ in global_entries}
        basic = configs['Basic Options']
        global_config = SimpleNamespace(get_all_visible_configs=lambda: list(global_entries),
            get_config=lambda key: configs.get(key if isinstance(key, str) else key.name, MemoryConfig()))
        executor = SimpleNamespace(scene=None, text_fix={}, trigger_tasks=[], onetime_tasks=[task], current_task=None, paused=True,
                                   basic_options=basic, global_config=global_config, waiting_for_task=lambda _: '')
        from config import version
        fake_app = SimpleNamespace(tr=lambda text: catalog.gettext(QCoreApplication.translate('app', str(text))) if text else '', title='OK-WW', version=version,
                                   ok_config=InertConfig(), start_controller=SimpleNamespace(start=Mock()))
        for name, value in [('app', fake_app), ('executor', executor), ('device_manager', manager),
                            ('config', {'gui_icon': None}), ('task_manager', SimpleNamespace(imported_scripts={}))]:
            stack.enter_context(patch.object(og, name, value))
        hotkey_handler = stack.enter_context(patch('ok.gui.start.StartCard.Handler', Mock()))
        stack.enter_context(patch('src.gui.AccountConfigTab.get_default_repository', return_value=env.repository))
        stack.enter_context(patch('src.gui.SequenceManagementTab.get_default_repository', return_value=env.repository))
        stack.enter_context(patch('src.gui.DiagnosticStatusCard.default_root', return_value=Path(temp) / 'diagnostics'))
        stack.enter_context(patch('src.gui.DiagnosticStatusCard.DiagnosticStatusCard.refresh'))
        from src.task.DailyTask import DailyTask
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask
        from src.task.WeeklyBossTask import WeeklyBossTask
        for cls in (DailyTask, MultiAccountDailyTask):
            stack.enter_context(patch(cls.__module__ + '.get_default_service', return_value=env.integrity))
            stack.enter_context(patch(cls.__module__ + '.get_default_repository', return_value=env.repository))
        executor.onetime_tasks = []
        from config import config
        for collection in ('onetime_tasks', 'trigger_tasks'):
            instances = []
            for module, name in config[collection]:
                cls = getattr(importlib.import_module(module), name)
                instance = cls(executor=executor, app=None)
                instance.config = MemoryConfig(instance.default_config)
                instances.append(instance)
            setattr(executor, collection, instances)
        from src.gui.GeneralSettingsTab import GeneralSettingsTab
        from src.gui.AccountSettingsTab import AccountSettingsTab
        from src.gui.TaskHubTab import TaskHubTab
        from src.gui.AssistantHubTab import AssistantHubTab
        from src.gui.ToolsHubTab import ToolsHubTab
        from ok.gui.MainWindow import MainWindow
        for method in ('auto_backup_config', '_start_backup_cleanup_timer', '_handle_first_show'):
            stack.enter_context(patch.object(MainWindow, method))
        stack.enter_context(patch('ok.gui.MainWindow.Config', side_effect=lambda name, defaults: InertConfig(defaults)))
        stack.enter_context(patch('ok.gui.MainWindow.QSystemTrayIcon'))
        stack.enter_context(patch('ok.notification.NotificationManager'))
        stack.enter_context(patch('src.gui.TaskStatusWindow.TaskStatusWindow'))
        window = MainWindow(fake_app, {'windows': {'exe': 'fake'}}, InertConfig(), QIcon(), 'OK-WW', version,
                            exit_event=threading.Event(), global_config=global_config, executor=executor, handler=Mock())
        stack.enter_context(patch.object(og, 'main_window', window))
        settings = window.general_settings_tab
        sample_state = os.environ.get('OKWW_UI_SAMPLE_STATE', '')
        if sample_state:
            if sample_state not in ('running', 'error'):
                raise ValueError('OKWW_UI_SAMPLE_STATE must be running or error')
            sample_task = window.task_hub_tab.task_tab.card_widgets[0].task
            sample_task._enabled = sample_state == 'running'
            sample_task.running = sample_state == 'running'
            sample_task.start_time = time.time() - 10
            sample_task.info['离线样板'] = '模拟运行中' if sample_state == 'running' else '模拟错误详情：未连接游戏'
            if sample_state == 'running':
                executor.current_task = sample_task
            window.task_hub_tab.task_tab.last_task = sample_task
            window.task_hub_tab.task_tab.current_info_run = (id(sample_task), sample_task.start_time)
            window.task_hub_tab.task_tab.update_info_table()
            for card in window.task_hub_tab.task_tab.card_widgets:
                card.update_buttons(card.task)
        pages = [window.task_hub_tab, window.account_settings_tab, window.assistant_hub_tab,
                 window.tools_hub_tab, settings]
        hotkey_handler.assert_called_once()
        from src.gui.navigation_sections import build_navigation_manifest
        nav = window.navigationInterface.panel
        assert len(nav.items) == 5, 'Unexpected navigation destination'
        for page, item in zip(pages, build_navigation_manifest()):
            widget = nav.items[page.objectName()].widget
            assert (nav.bottomLayout.indexOf(widget) >= 0) == (item['position'] == 'bottom')
        assert window.stackedWidget.currentWidget() is pages[0], 'Default page must be tasks'
        assert settings.preferences.backup_config_card is None
        assert pages[3].maintenance_tab.backup_config_card.has_key('Config Backup Directory')
        pages[3].diagnostic_panel._show_status('最后成功：无\n最近上传错误：无\n最近采集警告：无')
        actual = [card.task for page in (pages[0].task_tab, pages[2].trigger_panel, pages[3].experiments)
                  for card in page.card_widgets]
        expected = [task for task in executor.onetime_tasks + executor.trigger_tasks if task.visible]
        assert sorted(map(id, actual)) == sorted(map(id, expected)), 'Missing or duplicated task cards'
        apply_codex_light_theme(app)
        # Detach pages for content-width checks only after checking the real shell.
        window.resize(1200, 800)
        window.show()
        for _ in range(8): app.processEvents()
        window.grab().save(str(output / 'MainWindow.png'))
        window.hide()
        window.stackedWidget.currentChanged.disconnect(window._onCurrentInterfaceChanged)
        for page in pages:
            window.stackedWidget.removeWidget(page)
            page.setParent(None)
            if os.environ.get('OKWW_UI_EXPAND_ALL'):
                from src.gui.SectionPanel import SectionPanel
                from ok.gui.tasks.ConfigCard import ConfigCard
                for section in page.findChildren(SectionPanel):
                    section.set_expanded(True)
                for card in page.findChildren(ConfigCard):
                    card.setExpand(True)
            for width, height in [(760, 700), (1100, 800)]:
                page.resize(width, height)
                page.show()
                for _ in range(8): app.processEvents()
                assert not page.findChildren(QComboBox), 'Native dropdown remains on page'
                page.grab().save(str(output / f'{type(page).__name__}-{width}.png'))
                if sample_state and page is window.task_hub_tab:
                    assert page.task_tab.task_summary.isVisible(), 'Sample status must be visible'
                    assert '离线样板' in page.task_tab.task_summary.text()
                inner = [bar for bar in page.findChildren(QScrollBar)
                         if bar.isVisible() and bar.maximum() > 0
                         and bar not in (page.verticalScrollBar(), page.horizontalScrollBar())]
                print(type(page).__name__, width, 'inner_scrollbars=', len(inner),
                      'content_width=', page.view.width(), 'viewport_width=', page.viewport().width(), flush=True)
                for control in page.findChildren(QPushButton):
                    if os.environ.get('OKWW_UI_LAYOUT_DEBUG') and ('管理' in control.text() or 'Manage' in control.text()):
                        print('action', control.text(), control.isVisible(), control.geometry(), control.parentWidget().geometry())
                    if control.isVisible() and (control.width() < 10 or control.height() < 10):
                        raise AssertionError(f'Collapsed action: {control.text()} {control.geometry()}')
                    if control.isVisible() and control.mapTo(page.view, QPoint(control.width(), 0)).x() > page.view.width():
                        raise AssertionError(f'Action outside page: {control.text()}')
                if inner or page.view.width() > page.viewport().width():
                    raise AssertionError('nested scroll or horizontal overflow')
                page.verticalScrollBar().setValue(page.verticalScrollBar().maximum())
                for _ in range(4): app.processEvents()
                page.grab().save(str(output / f'{type(page).__name__}-{width}-bottom.png'))
            page.hide()
        text_audit = {type(page).__name__: audit_texts(page) for page in pages}
        from ok.gui.tasks.TaskTab import TaskTab
        for task_tab in QApplication.allWidgets():
            if isinstance(task_tab, TaskTab):
                task_tab.timer.stop()
        for page in pages:
            page.close()
            page.deleteLater()
        window.deleteLater()
        from src.gui.AccountConfigTab import AccountTemplateDialog, NewAccountDialog
        for dialog in (AccountTemplateDialog(dict(executor.onetime_tasks[0].default_config)),
                       NewAccountDialog(['S1', 'S2'])):
            dialog.show()
            for _ in range(5): app.processEvents()
            dialog.grab().save(str(output / f'{type(dialog).__name__}.png'))
            text_audit[type(dialog).__name__] = audit_texts(dialog)
            for button in dialog.findChildren(QPushButton):
                # Fluent dropdowns are buttons inside the scrollable form, not footer actions.
                if isinstance(button, ComboBox):
                    continue
                if button.isVisible() and not dialog.rect().contains(button.mapTo(dialog, button.rect().center())):
                    raise AssertionError(f'Dialog button outside window: {button.text()}')
            dialog.close()
            dialog.deleteLater()
        app.processEvents()
        from src.gui.ChoiceControls import QtComboBox
        from PySide6.QtTest import QTest
        control = QtComboBox()
        control.resize(300, 36)
        control.addItems(['无', '测试选项', '较长的测试选项，用于核对完整文字与圆角菜单'])
        control.show()
        control.activateWindow()
        control.setFocus()
        app.processEvents()
        control.grab().save(str(output / 'Dropdown-focus.png'))
        QTest.mouseMove(control, QPoint(20, 20))
        app.processEvents()
        control.grab().save(str(output / 'Dropdown-hover.png'))
        control._toggleComboMenu()
        QTest.qWait(250)
        control.dropMenu.grab().save(str(output / 'Dropdown-menu.png'))
        control._closeComboMenu()
        control.setEnabled(False)
        app.processEvents()
        control.grab().save(str(output / 'Dropdown-disabled.png'))
        control.close()
        control.deleteLater()
        (output / 'ui-text-audit.json').write_text(json.dumps(text_audit, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    render(Path(sys.argv[1] if len(sys.argv) > 1 else 'tests/output/flat-ui'))
