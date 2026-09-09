"""Render actual project pages using synthetic accounts and inert device services."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile
import threading
import gettext
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication, QWidget, QScrollBar, QPushButton
from PySide6.QtCore import QPoint, QTranslator, QLocale
from qfluentwidgets import FluentTranslator
from PySide6.QtGui import QFontDatabase, QFont
from ok import og
from tests.TestFlatUI import MemoryConfig, example_task
from tests.fixture_support import make_account_environment
from src.gui.CodexTheme import apply_codex_light_theme


class InertConfig(MemoryConfig):
    def save_file(self): pass


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
        hotkeys = MemoryConfig({'Echo Key': 'Q', 'Liberation Key': 'R'})
        basic = MemoryConfig({'Start/Stop': 'F9'})
        option = SimpleNamespace(name='游戏快捷键', description='', default_config=dict(hotkeys), config_description={}, config_type={}, icon=None)
        global_config = SimpleNamespace(get_all_visible_configs=lambda: [('Game Hotkey', hotkeys, option), ('Basic Options', basic, option)],
                                        get_config=lambda _: MemoryConfig())
        executor = SimpleNamespace(scene=None, text_fix={}, trigger_tasks=[], onetime_tasks=[task], current_task=None, paused=True,
                                   basic_options=basic, global_config=global_config, waiting_for_task=lambda _: '')
        from config import version
        fake_app = SimpleNamespace(tr=lambda text: catalog.gettext(str(text)) if text else '', title='OK-WW', version=version,
                                   ok_config=InertConfig(), start_controller=SimpleNamespace(start=Mock()))
        for name, value in [('app', fake_app), ('executor', executor), ('device_manager', manager),
                            ('config', {'gui_icon': None}), ('task_manager', SimpleNamespace(imported_scripts={}))]:
            stack.enter_context(patch.object(og, name, value))
        stack.enter_context(patch('ok.gui.start.StartCard.Handler', Mock()))
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
        for cls in (DailyTask, MultiAccountDailyTask, WeeklyBossTask):
            instance = cls(executor=executor, app=None)
            instance.config = MemoryConfig(instance.default_config)
            executor.onetime_tasks.append(instance)
        from src.gui.GeneralSettingsTab import GeneralSettingsTab
        from src.gui.AccountSettingsTab import AccountSettingsTab
        from src.gui.TaskHubTab import TaskHubTab
        from src.gui.ActivityHubTab import ActivityHubTab
        from src.gui.TestHubTab import TestHubTab
        pages = [GeneralSettingsTab({'windows': {'exe': 'fake'}}, threading.Event(), executor, global_config),
                 AccountSettingsTab(), TaskHubTab(), ActivityHubTab(), TestHubTab()]
        apply_codex_light_theme(app)
        for page in pages:
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
                page.grab().save(str(output / f'{type(page).__name__}-{width}.png'))
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
        for page in pages:
            page.close()
            page.deleteLater()
        from src.gui.AccountConfigTab import AccountTemplateDialog, NewAccountDialog
        for dialog in (AccountTemplateDialog(dict(executor.onetime_tasks[0].default_config)),
                       NewAccountDialog(['S1', 'S2'])):
            dialog.show()
            for _ in range(5): app.processEvents()
            dialog.grab().save(str(output / f'{type(dialog).__name__}.png'))
            for button in dialog.findChildren(QPushButton):
                if button.isVisible() and not dialog.rect().contains(button.mapTo(dialog, button.rect().center())):
                    raise AssertionError(f'Dialog button outside window: {button.text()}')
            dialog.close()
            dialog.deleteLater()
        app.processEvents()


if __name__ == '__main__':
    render(Path(sys.argv[1] if len(sys.argv) > 1 else 'tests/output/flat-ui'))
