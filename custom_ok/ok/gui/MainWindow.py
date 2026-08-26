import os
import threading
import time

import pyappify
from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QScreen
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QApplication
from qfluentwidgets import qconfig, FluentIcon, NavigationItemPosition, MessageBox, InfoBar, \
    InfoBarPosition, MessageBoxBase, FluentWindow, NavigationDisplayMode, isDarkTheme, Theme
from qfluentwidgets.components.widgets.scroll_bar import ScrollBarHandleDisplayMode
from qfluentwidgets.common.style_sheet import updateStyleSheet

_original_MessageBoxBase_keyPressEvent = MessageBoxBase.keyPressEvent

def _patched_message_box_base_keyPressEvent(self, e):
    if e.key() == Qt.Key_Escape:
        if hasattr(self, 'cancelButton') and self.cancelButton.isEnabled() and self.cancelButton.isVisible():
            self.cancelButton.click()
            return
    elif e.key() == Qt.Key_Enter or e.key() == Qt.Key_Return:
        if hasattr(self, 'yesButton') and self.yesButton.isEnabled() and self.yesButton.isVisible():
            self.yesButton.click()
            return
    _original_MessageBoxBase_keyPressEvent(self, e)

MessageBoxBase.keyPressEvent = _patched_message_box_base_keyPressEvent


from ok.util.config import Config

from ok.gui.Communicate import communicate
from ok.gui.common.accent_color import qfluent_theme_source_color
from ok.gui.util.Alert import alert_error
from ok.gui.util.touch_scroll import enable_touch_scrolling
from ok.gui.util.pyappify_startup import get_startup_version_change
from ok.gui.widget.StartLoadingDialog import StartLoadingDialog
from ok.util.GlobalConfig import basic_options, KILL_LAUNCHER_AFTER_START, NOTIFICATION_OPTION_NAME
from ok.util.clazz import init_class_by_name
from ok.util.process import restart_as_admin, parse_arguments_to_map

from ok.util.logger import Logger
from src.gui.CodexTheme import apply_codex_light_theme

logger = Logger.get_logger(__name__)

NAVIGATION_EXPAND_MAX_WIDTH = 240
NAVIGATION_EXPAND_FIT_PADDING = 23


class MainWindow(FluentWindow):

    def __init__(self, app, config, ok_config, icon, title, version, debug=False, about=None, exit_event=None,
                 global_config=None, executor=None, handler=None):
        super().__init__()
        # Page pop transitions move scroll-area contents vertically and can show
        # a brief top/bottom flash when switching navigation tabs.
        self.stackedWidget.setAnimationEnabled(False)
        self._theme_cooldowns = set()
        logger.info('main window __init__')
        # The personal build deliberately stays light; Windows theme changes
        # must not mutate the UI while the game is running.
        apply_codex_light_theme(QApplication.instance())
        navigation_scroll_area = self.navigationInterface.panel.scrollArea
        navigation_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        enable_touch_scrolling(navigation_scroll_area)
        navigation_scroll_area.scrollDelagate.vScrollBar.setHandleDisplayMode(
            ScrollBarHandleDisplayMode.ALWAYS
        )
        self.app = app
        self.executor = executor
        self.handler = handler
        self.ok_config = ok_config
        self.basic_global_config = global_config.get_config(basic_options)
        self.main_window_config = Config('main_window', {'last_version': 'v0.0.0'})
        self.exit_event = exit_event
        from ok.gui.start.StartTab import StartTab
        self.start_tab = StartTab(config, exit_event)
        self.onetime_tab = None
        self.trigger_tab = None
        self.version = version
        self.emulator_starting_dialog = None
        self.do_not_quit = False
        self.config = config
        # Shared read-only account integrity service is installed by main.py
        # before OK constructs tasks.  Keep GUI review state separate from the
        # task guard: acknowledging a dialog never unlocks automatic work.
        try:
            from src.config_integrity import get_default_service
            self.integrity_service = get_default_service()
        except Exception:
            self.integrity_service = None
        self._integrity_review_blocked = False
        # The launcher handshake must complete before a modal integrity dialog
        # is shown.  Keep the post-show callback state explicit so a repeated
        # Qt show/activation event cannot start a task twice.
        self._startup_post_show_scheduled = False
        self._startup_post_show_complete = False
        self._startup_args = {}
        self.shown = False
        from ok.notification import NotificationManager
        self.notification_manager = NotificationManager(
            global_config, executor, exit_event, app_name=title, app_icon=config.get('gui_icon'))

        communicate.restart_admin.connect(self.restart_admin)
        if config.get('show_update_copyright'):
            communicate.copyright.connect(self.show_update_copyright)

        self.grouped_task_tabs = []
        self.schedule_tab = None
        self.global_config_tabs = []
        from src.gui.GeneralSettingsTab import GeneralSettingsTab
        from src.gui.AccountSettingsTab import AccountSettingsTab
        from src.gui.TaskHubTab import TaskHubTab
        from src.gui.ActivityHubTab import ActivityHubTab
        from src.gui.TestHubTab import TestHubTab

        self.general_settings_tab = GeneralSettingsTab(config, exit_event, executor, global_config)
        self.account_settings_tab = AccountSettingsTab()
        self.task_hub_tab = TaskHubTab()
        self.activity_hub_tab = ActivityHubTab()
        self.test_hub_tab = TestHubTab()
        self.start_tab = self.general_settings_tab.start_panel
        self.trigger_tab = self.general_settings_tab.trigger_panel
        self.onetime_tab = self.task_hub_tab.task_tab
        self.imported_tabs = {}
        for tab_obj in (self.general_settings_tab, self.account_settings_tab, self.task_hub_tab,
                        self.activity_hub_tab, self.test_hub_tab):
            tab_obj.executor = executor
            self.addSubInterface(tab_obj, tab_obj.icon, self.app.tr(tab_obj.name),
                                 position=NavigationItemPosition.SCROLL)
        if debug:
            from ok.gui.debug.DebugTab import DebugTab
            debug_tab = DebugTab(config, exit_event)
            self.addSubInterface(debug_tab, FluentIcon.DEVELOPER_TOOLS, self.tr('Debug'),
                                 position=NavigationItemPosition.BOTTOM)
            from ok.gui.debug.RunCodeTab import RunCodeTab
            run_code_tab = RunCodeTab(config, exit_event)
            self.addSubInterface(run_code_tab, FluentIcon.COMMAND_PROMPT, self.tr('Run Code'),
                                 position=NavigationItemPosition.BOTTOM)

        # 脚本/模板 tab 已隐藏（用户要求精简界面）
        # if og.task_manager.has_custom:
        #     from ok.gui.tasks.EditTaskTab import EditTaskTab
        #     self.edit_task_tab = EditTaskTab()
        #     self.addSubInterface(self.edit_task_tab, FluentIcon.EDIT, self.tr('Script'),
        #                          position=NavigationItemPosition.SCROLL)
        #
        # if og.task_manager.has_custom or debug:
        #     from ok.gui.tasks.TemplateTab import TemplateTab
        #     self.template_tab = TemplateTab(config=config)
        #     self.addSubInterface(self.template_tab, FluentIcon.PHOTO, self.tr('Templates'),
        #                          position=NavigationItemPosition.SCROLL)
        
        notification_tab = None

        # 一键重启（在通知/设置上方，方便修改配置后快速重启生效）
        try:
            self.navigationInterface.addItem(
                routeKey='restart_app',
                icon=FluentIcon.SYNC,
                text=self.tr('重启程序'),
                onClick=self.restart_app,
                position=NavigationItemPosition.BOTTOM,
                tooltip=self.tr('重启程序'),
            )
        except Exception as e:
            logger.error('add restart nav item failed', e)

        from ok.gui.settings.SettingTab import SettingTab
        self.setting_tab = SettingTab()
        self.addSubInterface(self.setting_tab, FluentIcon.SETTING, self.tr('程序设置'),
                             position=NavigationItemPosition.BOTTOM)

        from ok.gui.about.AboutTab import AboutTab
        self.about_tab = AboutTab(config)
        self.addSubInterface(self.about_tab, FluentIcon.QUESTION, self.tr('About'),
                             position=NavigationItemPosition.BOTTOM)

        dev = self.tr('Debug')
        profile = config.get('profile', "")
        self.setWindowTitle(f'{title} {version} {profile} {dev if debug else ""}')

        # 配置自动备份：每天首次启动备份一次（备份位置在设置 → 数据设置 中配置）
        try:
            self.auto_backup_config()
        except Exception as e:
            logger.error('auto backup config failed', e)
        self._start_backup_cleanup_timer()

        communicate.executor_paused.connect(self.executor_paused)
        communicate.tab.connect(self.navigate_tab)
        menu = QMenu()
        exit_action = menu.addAction(self.tr("Exit"))
        exit_action.triggered.connect(self.tray_quit)

        self.tray = QSystemTrayIcon(icon, parent=self)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_icon_activated)
        self.tray.show()
        self.tray.setToolTip(title)

        self.navigationInterface.displayModeChanged.connect(self._save_navigation_state)

        communicate.capture_error.connect(self.capture_error)
        communicate.notification.connect(self.show_notification)
        communicate.config_validation.connect(self.config_validation)
        communicate.starting_emulator.connect(self.starting_emulator)
        communicate.global_config.connect(self.goto_global_config)

        logger.info('main window __init__ done')

    @staticmethod
    def _get_dwm_accent_color():
        """Return the DWM accent color as a compatibility fallback."""
        try:
            import ctypes
            from ctypes import wintypes

            colorization_color = wintypes.DWORD()
            opaque_blend = wintypes.BOOL()
            result = ctypes.windll.dwmapi.DwmGetColorizationColor(
                ctypes.byref(colorization_color), ctypes.byref(opaque_blend)
            )
            if result != 0:
                return None

            argb = colorization_color.value
            return QColor((argb >> 16) & 0xff, (argb >> 8) & 0xff, argb & 0xff)
        except (AttributeError, OSError):
            logger.exception('Failed to read the Windows system accent color')
            return None

    def get_system_accent_color(self):
        """Return the base Windows accent color (legacy helper)."""
        return self._get_dwm_accent_color()

    def get_system_primary_theme_color(self):
        """Return a qfluent source color matching the Windows primary fill."""
        dark = isDarkTheme()
        try:
            from ok.rotypes.Windows.UI.ViewManagement import UIColorType, get_color_value

            color_type = UIColorType.AccentLight2 if dark else UIColorType.AccentDark1
            system_color = get_color_value(color_type)
            red, green, blue = system_color.red, system_color.green, system_color.blue
        except (ImportError, OSError, TypeError):
            logger.exception('Failed to read the Windows accent color palette')
            fallback = self.get_system_accent_color()
            if fallback is None:
                return None
            red, green, blue = fallback.red(), fallback.green(), fallback.blue()

        red, green, blue = qfluent_theme_source_color(red, green, blue, dark)
        return QColor(red, green, blue)

    def _sync_system_accent_color(self, refresh=False):
        color = self.get_system_primary_theme_color()
        if color is None or color == qconfig.get(qconfig.themeColor):
            return False

        qconfig.set(qconfig.themeColor, color, save=False)
        if refresh:
            updateStyleSheet()
            logger.info(f'Refresh primary button color: {color.name()}')
        else:
            logger.info(f'Prepare primary button color: {color.name()}')
        return True

    def _on_theme_changed(self, _theme):
        # Keep legacy callers harmless while enforcing the fixed light shell.
        apply_codex_light_theme(QApplication.instance())

    def _apply_system_theme_change(self):
        """Ignore native theme notifications; the app is intentionally light."""
        try:
            apply_codex_light_theme(QApplication.instance())
            logger.info('System theme notification ignored; Codex light theme is fixed')
        finally:
            self._theme_cooldowns.discard('system-theme')

    def _refresh_mica(self):
        """Rebuild Mica after Windows finishes replacing the system backdrop."""
        if not self.isMicaEffectEnabled():
            return

        logger.info(f'Rebuild Mica effect: dark={isDarkTheme()}')
        self.setMicaEffectEnabled(False)
        self.setMicaEffectEnabled(True)
        self.update()

    def _schedule_system_theme_change(self):
        if not hasattr(self, '_theme_cooldowns'):
            self._theme_cooldowns = set()
        if 'system-theme' in self._theme_cooldowns:
            return
        self._theme_cooldowns.add('system-theme')
        QTimer.singleShot(250, self._apply_system_theme_change)

    def nativeEvent(self, event_type, message):
        try:
            import ctypes
            from ctypes import wintypes

            native_message = wintypes.MSG.from_address(int(message))
            if native_message.message == 0x0320:  # WM_DWMCOLORIZATIONCOLORCHANGED
                logger.info('System colorization colors changed')
                self._schedule_system_theme_change()
            elif (
                native_message.message == 0x001A  # WM_SETTINGCHANGE
                and native_message.lParam
                and ctypes.wstring_at(native_message.lParam) == "ImmersiveColorSet"
            ):
                logger.info('System theme changed')
                self._schedule_system_theme_change()
        except (OSError, TypeError, ValueError) as e:
            logger.error('Failed to process Windows theme change', e)

        return super().nativeEvent(event_type, message)

    def update_imported_tabs(self):
        """Update navigation tabs for imported scripts."""
        from ok import og
        from ok.gui.tasks.OneTimeTaskTab import OneTimeTaskTab
        
        imported_scripts = og.task_manager.imported_scripts
        
        # Remove tabs for scripts that no longer exist
        scripts_to_remove = [
            fn for fn in self.imported_tabs
            if fn not in imported_scripts or not any(
                getattr(task, 'visible', True) for task in imported_scripts[fn].get('tasks', [])
            )
        ]
        for fn in scripts_to_remove:
            tab = self.imported_tabs.pop(fn)
            # Remove from navigation. MSFluentWindow provides navigation object
            self.navigationInterface.removeWidget(tab.objectName())
            self.stackedWidget.removeWidget(tab)
            tab.deleteLater()
            
        # Add tabs for new scripts
        for file_name, imp in imported_scripts.items():
            if file_name not in self.imported_tabs:
                script_name = imp['script_name']
                tasks = [task for task in imp.get('tasks', []) if getattr(task, 'visible', True)]
                if tasks:
                    group_tab = OneTimeTaskTab(is_standalone=False, group_name=script_name)
                    group_icon = tasks[0].group_icon if hasattr(tasks[0], 'group_icon') else FluentIcon.APPLICATION
                    self.imported_tabs[file_name] = group_tab
                    
                    # Inserting after TemplateTab if it exists
                    if hasattr(self, 'template_tab'):
                        # Using our custom logic or standard addSubInterface
                        # qfluentwidgets typically appends to the current section
                        self.addSubInterface(group_tab, group_icon, self.app.tr(script_name),
                                             position=NavigationItemPosition.SCROLL)
                    else:
                        self.addSubInterface(group_tab, group_icon, self.app.tr(script_name),
                                             position=NavigationItemPosition.SCROLL)

        self.update_navigation_width()

    def restart_admin(self):
        w = MessageBox(QCoreApplication.translate("app", "Alert"),
                       QCoreApplication.translate("StartController",
                                                  "PC version requires admin privileges, Please restart this app with admin privileges!"),
                       self.window())
        if w.exec():
            logger.info('restart_admin Yes button is pressed')
            thread = threading.Thread(target=restart_as_admin)
            thread.start()
            self.app.quit()

    def auto_backup_config(self):
        """Create a verified whole-tree daily snapshot using the backup engine."""
        from datetime import datetime
        from pathlib import Path
        from src.config_backup import ConfigBackupService
        from ok import og

        backup_dir = ''
        try:
            from src.storage import get_warehouse_sub
            wh = get_warehouse_sub('配置备份')
            if wh:
                backup_dir = wh
        except Exception:
            pass
        if not backup_dir:
            try:
                global_config = og.executor.global_config.get_config('Config Backup')
                backup_dir = (global_config or {}).get('Config Backup Directory', '') or ''
            except Exception:
                pass
        if not backup_dir.strip():
            backup_dir = os.path.join(os.getcwd(), 'configs_backup')
        backup_dir = backup_dir.strip()
        config_src = Path(os.path.join(os.getcwd(), 'configs'))
        if not config_src.is_dir():
            return None
        # Never place a backup tree inside configs: that would make the next
        # full snapshot include its own previous snapshots.
        try:
            if Path(backup_dir).resolve() == config_src.resolve() or config_src.resolve() in Path(backup_dir).resolve().parents:
                backup_dir = os.path.join(os.getcwd(), 'configs_backup')
        except OSError:
            pass
        service = ConfigBackupService(config_src, backup_dir, app_version=str(self.version))
        if service.has_daily_snapshot_for_date(datetime.now().strftime('%Y-%m-%d')):
            return None
        try:
            snapshot = service.create_daily_snapshot()
            logger.info(f'config auto backup done: {snapshot.path}')
            return snapshot
        except Exception as e:
            logger.error('config auto backup failed', e)
            return None

    def _start_backup_cleanup_timer(self):
        """Run retention and failure-evidence cleanup off the GUI thread."""
        self._backup_cleanup_timer = QTimer(self)
        self._backup_cleanup_timer.setInterval(6 * 60 * 60 * 1000)
        self._backup_cleanup_timer.timeout.connect(self._cleanup_backup_artifacts)
        self._backup_cleanup_timer.start()
        self._cleanup_backup_artifacts()

    def _cleanup_backup_artifacts(self):
        def cleanup():
            try:
                from src.config_backup import ConfigBackupService
                from ok import og
                backup_dir = ''
                try:
                    from src.storage import get_warehouse_sub
                    backup_dir = get_warehouse_sub('配置备份') or ''
                except Exception:
                    pass
                if not backup_dir:
                    try:
                        global_config = og.executor.global_config.get_config('Config Backup')
                        backup_dir = (global_config or {}).get('Config Backup Directory', '') or ''
                    except Exception:
                        pass
                backup_dir = backup_dir.strip() or os.path.join(os.getcwd(), 'configs_backup')
                service = ConfigBackupService(
                    os.path.join(os.getcwd(), 'configs'),
                    backup_dir,
                    app_version=str(self.version))
                service.cleanup()
            except Exception as exc:
                logger.warning(f'config backup cleanup failed: {exc}')
            # Failure evidence is optional while the evidence implementation
            # lands; keep this import dynamic to avoid a startup dependency.
            try:
                import importlib
                module = importlib.import_module('src.account_switch_evidence')
                cleanup_fn = getattr(module, 'cleanup_account_switch_evidence', None)
                if callable(cleanup_fn):
                    cleanup_fn()
            except (ImportError, OSError, RuntimeError) as exc:
                logger.debug(f'failure evidence cleanup unavailable: {exc}')
        threading.Thread(target=cleanup, name='config-backup-cleanup', daemon=True).start()

    def restart_app(self):
        """一键重启：退出当前进程（正常保存配置）→ 由独立"重启器"进程延迟 2 秒后重新启动 okww。

        不能把重启逻辑放在当前进程的线程里：app.quit() 退出事件循环后进程结束，
        daemon 线程会被直接终止导致重启命令不执行。因此用 subprocess 启动一个
        独立的重启器（等旧进程退出、释放单实例锁后再拉起新实例）。
        """
        w = MessageBox(QCoreApplication.translate('app', 'Restart'),
                       QCoreApplication.translate('app', '确定要重启 okww 吗？修改的配置会在重启后生效。'),
                       self.window())
        w.yesButton.setText(QCoreApplication.translate('app', '重启'))
        w.cancelButton.setText(QCoreApplication.translate('app', '取消'))
        if not w.exec():
            return
        logger.info('restart app requested by user')

        import subprocess
        import sys
        import os
        try:
            base = os.getcwd()
            python = os.path.join(base, '.venv', 'Scripts', 'python.exe')
            main = os.path.join(base, 'main.py')
            if not os.path.exists(python):
                python = sys.executable
            # 重启器：独立进程，等 2 秒（旧进程退出+释放单实例锁）后启动 okww
            rel_code = (
                "import time,subprocess,os\n"
                "time.sleep(2)\n"
                "subprocess.Popen([{py!r}, {main!r}], cwd={base!r})\n"
            ).format(py=python, main=main, base=base)
            subprocess.Popen(
                [python, '-c', rel_code], cwd=base,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            logger.info(f'restart relayer launching: {python} {main}')
        except Exception as e:
            logger.error('restart relayer start failed', e)

        # 正常退出当前进程（配置自动保存），重启器稍后拉起新实例
        self.app.quit()

    def on_tray_icon_activated(self, reason):
        """Handles clicks on the system tray icon."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            logger.info('main window on_tray_icon_activated QSystemTrayIcon.ActivationReason.Trigger')
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            logger.info('main window on_tray_icon_activated QSystemTrayIcon.ActivationReason.MiddleClick')
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            logger.info(
                f'main window on_tray_icon_activated QSystemTrayIcon.ActivationReason.DoubleClick self.isVisible():{self.isVisible()}')
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def bring_to_front(self):
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        if self.windowHandle():
            self.windowHandle().requestActivate()
        if os.name == 'nt':
            try:
                import win32con
                import win32gui
                hwnd = int(self.winId())
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.BringWindowToTop(hwnd)
                win32gui.SetForegroundWindow(hwnd)
            except Exception as e:
                logger.debug(f'bring_to_front native activation failed: {e}')

    def goto_global_config(self, key):
        for config_tab in self.global_config_tabs:
            if config_tab.has_key(key):
                self.switchTo(config_tab)
                return
        self.switchTo(self.setting_tab)
        self.setting_tab.goto_config(key)

    def tray_quit(self):
        logger.info('main window tray_quit')
        self.app.quit()

    def show_update_copyright(self):
        title = self.tr('Info')
        content = self.tr(
            "This is a free software. If you purchased this anywhere, request a refund from the seller.")
        from qfluentwidgets import Dialog
        w = Dialog(title, content, self.window())
        w.cancelButton.setVisible(False)
        w.setContentCopyable(True)
        w.exec()
        self.switchTo(self.about_tab)

    def show_startup_version_change_notice(self):
        version_change = get_startup_version_change()
        if not version_change:
            return

        logger.info(f'show startup version change on about tab {version_change.title}')
        self.switchTo(self.about_tab)

    def showEvent(self, event):
        first_show = event.type() == QEvent.Show and not self.shown
        if first_show:
            self.shown = True
            # Complete the native show and launcher handshake first.  The
            # integrity review is intentionally deferred until the event loop
            # has returned, otherwise QMessageBox.question can leave the
            # launcher waiting while this window is still hidden.
            super().showEvent(event)
            self._handle_first_show()
            return
        super().showEvent(event)

    def _handle_first_show(self):
        """Perform readiness work, then enqueue the integrity-gated startup."""
        self._complete_window_readiness()
        QTimer.singleShot(0, self.bring_to_front)
        self._schedule_post_show_startup()

    def _complete_window_readiness(self):
        """Notify the launcher only after the main window has been shown."""
        self._startup_args = parse_arguments_to_map()
        pyappify.hide_pyappify()
        if update_pyappify := self.config.get("update_pyappify"):
            pyappify.upgrade(update_pyappify.get('to_version'), update_pyappify.get('sha256'),
                             [update_pyappify.get('zip_url')], self.exit_event)
        logger.info(f"Window has fully displayed {self._startup_args}")
        communicate.start_success.emit()
        if self.basic_global_config.get(KILL_LAUNCHER_AFTER_START):
            logger.info('MainWindow showEvent Kill Launcher After Start')
            pyappify.kill_pyappify()

    def _schedule_post_show_startup(self):
        """Run the blocking integrity review after launcher readiness."""
        if self._startup_post_show_scheduled:
            logger.debug('post-show startup review already scheduled')
            return False
        self._startup_post_show_scheduled = True
        QTimer.singleShot(150, self._run_post_show_startup)
        return True

    def _run_post_show_startup(self):
        """Review integrity, then allow command-line and automatic starts."""
        if self._startup_post_show_complete:
            logger.debug('post-show startup callback already completed')
            return False
        self._startup_post_show_complete = True

        if not self._review_account_integrity_before_start():
            self._integrity_review_blocked = True
            # A failed review is a safe-mode outcome.  Keep the visible window
            # available for the user to inspect and resolve the incident.
            self.bring_to_front()
            return False

        self._integrity_review_blocked = False
        startup_version_change = get_startup_version_change()
        if self.version != self.main_window_config.get('last_version'):
            self.main_window_config['last_version'] = self.version
            if not self.config.get('auth') and not startup_version_change:
                logger.info('update success, show copyright')
                self.handler.post(lambda: communicate.copyright.emit(), delay=1)
            elif startup_version_change:
                logger.info('skip copyright dialog because startup version change is shown on about tab')
        args = self._startup_args
        if args.get('task', 0) > 0:
            task_index = args.get('task') - 1
            logger.info(f'start with params {task_index} {args.get("exit")}')
            self.app.start_controller.start(task_index, exit_after=args.get('exit'))
        elif self.basic_global_config.get('Auto Start Game When App Starts'):
            self.app.start_controller.start()
        # Check for .okscript file in command line arguments only after the
        # integrity gate has completed.
        self._check_okscript_args()
        QTimer.singleShot(250, self.show_startup_version_change_notice)
        return True

    def _review_account_integrity_before_start(self):
        """Show the blocking review UI before command-line/auto-start actions."""
        service = getattr(self, 'integrity_service', None)
        if service is None:
            return True
        result = service.last_result or service.check()
        if result.ok:
            return self._review_missing_sequences_before_start(service)
        try:
            from src.gui.ConfigIntegrityDialog import ConfigIntegrityDialogController, ConfigIntegrityDialog
            if ConfigIntegrityDialog is None:
                return False
            controller = ConfigIntegrityDialogController(service)
            dialog = ConfigIntegrityDialog(controller, self)
            dialog.exec()
            return controller.can_run
        except Exception as exc:
            logger.error(f'account integrity review unavailable: {exc}')
            return False

    def _review_missing_sequences_before_start(self, service):
        """Offer one-time recovery when a trusted master has empty sequences."""
        detector = getattr(service, 'detect_missing_sequences', None)
        repair = getattr(service, 'repair_missing_sequences', None)
        if not callable(detector) or not callable(repair):
            return True
        try:
            detection = detector()
        except Exception as exc:
            logger.warning(f'legacy sequence detection unavailable: {exc}')
            return True
        if not isinstance(detection, dict) or not detection.get('eligible'):
            return True
        if not self._confirm_missing_sequences(detection):
            # A rejection is a deliberate choice; the settings page remains
            # available for a later repair attempt.
            return True
        try:
            snapshot = self._create_sequence_repair_snapshot()
            logger.info(f'legacy sequence repair transaction snapshot: {snapshot.path}')
            repair(confirm=True)
            checked = service.check(record_incident=False, resolve_incidents=False)
            if not checked.ok:
                logger.error('legacy sequence repair failed post-check')
                return False
            logger.info('legacy missing sequences repaired before startup')
            return True
        except Exception as exc:
            logger.error(f'legacy sequence repair failed: {exc}')
            return False

    def _create_sequence_repair_snapshot(self):
        """Create the required whole-config rollback point before migration."""
        from pathlib import Path
        from src.config_backup import ConfigBackupService

        backup_dir = ''
        try:
            from src.storage import get_warehouse_sub
            backup_dir = get_warehouse_sub('配置备份') or ''
        except Exception:
            pass
        if not backup_dir:
            try:
                from ok import og
                global_config = og.executor.global_config.get_config('Config Backup')
                backup_dir = (global_config or {}).get('Config Backup Directory', '') or ''
            except Exception:
                pass
        backup_dir = backup_dir.strip() or os.path.join(os.getcwd(), 'configs_backup')
        config_dir = Path(os.path.join(os.getcwd(), 'configs'))
        try:
            resolved_backup = Path(backup_dir).resolve()
            resolved_config = config_dir.resolve()
            if resolved_backup == resolved_config or resolved_config in resolved_backup.parents:
                backup_dir = os.path.join(os.getcwd(), 'configs_backup')
        except OSError:
            pass
        return ConfigBackupService(
            config_dir, backup_dir, app_version=str(self.version)).create_transaction_snapshot()

    def _confirm_missing_sequences(self, detection):
        """UI boundary kept separate so startup recovery can be unit tested."""
        try:
            from PySide6.QtWidgets import QMessageBox
            answer = QMessageBox.question(
                self, '恢复旧版遗漏序列',
                f"发现 {detection.get('sequence_count', 0)} 个序列、"
                f"{detection.get('account_count', 0)} 个账号（来源：{detection.get('source', '未知')}）。\n"
                '确认恢复后再启动任务？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            return answer == QMessageBox.Yes
        except Exception as exc:
            logger.error(f'missing sequence confirmation unavailable: {exc}')
            return False

    def review_account_integrity(self):
        """Reopen the review dialog after safe-mode dismissal."""
        service = getattr(self, 'integrity_service', None)
        if service is None:
            return True
        try:
            from src.gui.ConfigIntegrityDialog import ConfigIntegrityDialogController, ConfigIntegrityDialog
            controller = ConfigIntegrityDialogController(service)
            if ConfigIntegrityDialog is None:
                return False
            dialog = ConfigIntegrityDialog(controller, self)
            dialog.exec()
            self._integrity_review_blocked = not controller.can_run
            return controller.can_run
        except Exception as exc:
            logger.error(f'account integrity review failed: {exc}')
            self._integrity_review_blocked = True
            return False

    def set_window_size(self, width, height, min_width, min_height):
        screen = QScreen.availableGeometry(self.screen())
        if (self.ok_config['window_width'] > 0 and self.ok_config['window_height'] > 0 and
                self.ok_config['window_y'] > 0 and self.ok_config['window_x'] > 0):
            x, y, width, height = (self.ok_config['window_x'], self.ok_config['window_y'],
                                   self.ok_config['window_width'], self.ok_config['window_height'])
            if self.ok_config['window_maximized']:
                self.setWindowState(Qt.WindowMaximized)
            else:
                self.setGeometry(x, y, width, height)
        else:
            x = int((screen.width() - width) / 2)
            y = int((screen.height() - height) / 2)
            self.setGeometry(x, y, width, height)

        self.setMinimumSize(QSize(min_width, min_height))
        self.apply_navigation_state()

    def apply_navigation_state(self):
        self.update_navigation_width()
        if self.ok_config.get('navigation_expanded', True):
            self._expand_navigation_without_animation()

    def _expand_navigation_without_animation(self):
        self.navigationInterface.expand(False)

        # NavigationInterface normally mirrors the panel width from its resize
        # event.  While the window is hidden, Qt defers that event until the
        # first show, leaving the interface at its compact width for one frame.
        panel = self.navigationInterface.panel
        if panel.displayMode == NavigationDisplayMode.EXPAND:
            self.navigationInterface.setFixedWidth(panel.width())

    def update_navigation_width(self):
        panel = self.navigationInterface.panel
        item_widths = []
        for item in panel.items.values():
            widget = item.widget
            if hasattr(widget, 'suitableWidth'):
                item_widths.append(widget.suitableWidth() + NAVIGATION_EXPAND_FIT_PADDING)

        if not item_widths:
            return

        width = min(max(item_widths), NAVIGATION_EXPAND_MAX_WIDTH)
        self.navigationInterface.setExpandWidth(width)

        if panel.displayMode in (NavigationDisplayMode.EXPAND, NavigationDisplayMode.MENU):
            self._expand_navigation_without_animation()

    def _save_navigation_state(self, display_mode):
        self.ok_config['navigation_expanded'] = display_mode in (
            NavigationDisplayMode.EXPAND,
            NavigationDisplayMode.MENU,
        )

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize or event.type() == QEvent.Move:
            self.handler.post(self.update_ok_config, remove_existing=True, skip_if_running=True, delay=1)
        return super().eventFilter(obj, event)

    def update_ok_config(self):
        if self.isMaximized():
            self.ok_config['window_maximized'] = True
        else:
            self.ok_config['window_maximized'] = False
            geometry = self.geometry()
            self.ok_config['window_x'] = geometry.x()
            self.ok_config['window_y'] = geometry.y()
            self.ok_config['window_width'] = geometry.width()
            self.ok_config['window_height'] = geometry.height()
        logger.info(f'Window geometry updated in ok_config {self.ok_config}')

    def starting_emulator(self, done, error, seconds_left):
        if error:
            self.switchTo(self.start_tab)
            alert_error(error, True)
        if done:
            if self.emulator_starting_dialog:
                self.emulator_starting_dialog.close()
        else:
            if self.emulator_starting_dialog is None:
                self.emulator_starting_dialog = StartLoadingDialog(seconds_left,
                                                                   self)
            else:
                self.emulator_starting_dialog.restart_countdown(seconds_left)
            self.emulator_starting_dialog.show()

    def config_validation(self, message):
        title = self.tr('Error')
        InfoBar.error(
            title=title,
            content=message,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self.window()
        )
        self.tray.showMessage(title, message)

    def show_notification(self, message, title=None, error=False, tray=False, show_tab=None, params=None, images=None):
        from ok import og
        from ok.gui.util.app import show_info_bar
        translated_message = QCoreApplication.translate("app", message)
        if params:
            translated_message = translated_message.format(**params)
        translated_title = og.app.tr(title) if title else ""
        show_info_bar(self.window(), translated_message, translated_title, error)
        notification_manager = getattr(self, 'notification_manager', None)
        if tray and (notification_manager is None or notification_manager.system_enabled):
            self.tray.showMessage(translated_title, translated_message,
                                  QSystemTrayIcon.Critical if error else QSystemTrayIcon.Information,
                                  5000)
        if notification_manager is not None:
            notification_manager.submit(translated_title, translated_message, images)
        self.navigate_tab(show_tab)

    def capture_error(self):
        self.show_notification(self.tr('Please check whether the game window is selected correctly!'),
                               self.tr('Capture Error'), error=True)

    def navigate_tab(self, index):
        logger.debug(f'navigate_tab {index}')
        if index == "start":
            self.switchTo(self.start_tab)
        elif index == "onetime" and self.onetime_tab is not None:
            self.switchTo(self.onetime_tab)
        elif index == "trigger" and self.trigger_tab is not None:
            self.switchTo(self.trigger_tab)
        elif index == "schedule" and self.schedule_tab is not None:
            self.switchTo(self.schedule_tab)
        elif index == "about" and self.about_tab is not None:
            self.switchTo(self.about_tab)

    def startup_task_tab(self):
        """Return the first one-time task tab, falling back to triggers."""
        if self.onetime_tab is not None:
            return self.onetime_tab
        if self.grouped_task_tabs:
            return self.grouped_task_tabs[0]
        if self.imported_tabs:
            return next(iter(self.imported_tabs.values()))
        return self.trigger_tab

    def executor_paused(self, paused):
        task_tab = self.startup_task_tab()
        if not paused and self.stackedWidget.currentIndex() == 0 and task_tab:
            self.switchTo(task_tab)
        self.show_notification(self.tr("Start Success.") if not paused else self.tr("Pause Success."), tray=False)

    def _check_okscript_args(self):
        """Check sys.argv for .okscript files and import them.

        安全：启动参数里的 .okscript 可能来自文件关联/被诱导的快捷方式，属于
        不可信来源。仅接受位于本项目目录内的 .okscript，项目外的一律拒绝导入。
        """
        import sys
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        for arg in sys.argv[1:]:
            if not arg.lower().endswith('.okscript') or not os.path.exists(arg):
                continue
            abs_arg = os.path.abspath(arg)
            if not (abs_arg == project_root or abs_arg.startswith(project_root + os.sep)):
                logger.warning(f'拒绝导入项目目录外的 .okscript: {arg}')
                continue
            logger.info(f'Found .okscript file in args: {arg}')
            try:
                if hasattr(self, 'edit_task_tab'):
                    self.edit_task_tab._do_import(arg)
                else:
                    from ok.gui.tasks.ScriptPackager import import_script
                    success, message, import_folder = import_script(arg)
                    if success:
                        from ok import og
                        og.task_manager.load_import_folder(import_folder)
                        from ok.gui.util.app import show_info_bar
                        show_info_bar(self.window(), message, title=self.tr('Success'))
                    else:
                        from ok.gui.util.Alert import alert_error
                        alert_error(f"Import failed: {message}")
            except Exception as e:
                logger.error(f'Error importing .okscript file: {e}')

    def closeEvent(self, event):
        if self.app.exit_event.is_set():
            logger.info("Window closed exit_event.is_set")
            event.accept()
            return
        else:
            logger.info(f"Window closed exit_event.is not set {self.do_not_quit}")
            to_tray = self.basic_global_config.get('Minimize Window to System Tray when Closing')
            if to_tray:
                event.ignore()
                self.hide()
                return
            if not self.do_not_quit:
                self.exit_event.set()
                self.executor.destroy()
            event.accept()
            if not self.do_not_quit:
                pyappify.kill_pyappify()
                # 强制退出应用：防止窗口关闭后 python 进程残留（okww 修改版修复）
                try:
                    self.app.quit()
                except Exception:
                    pass
                QApplication.instance().exit()
