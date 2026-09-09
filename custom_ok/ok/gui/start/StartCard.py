from ctypes import windll, wintypes
import threading
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QWidget, QVBoxLayout, QHBoxLayout
from _ctypes import byref
from qfluentwidgets import FluentIcon, PrimaryPushButton, SettingCard, PushButton

from ok import Handler
from ok import Logger
from ok import og
from ok.gui.Communicate import communicate
from ok.gui.widget.StatusBar import StatusBar

logger = Logger.get_logger(__name__)


class StartCard(QWidget):
    show_choose_hwnd = Signal()
    hotkey_changed = Signal()
    hotkey_status_changed = Signal(str)

    def __init__(self, exit_event):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel('运行控制', self)
        heading.setProperty('role', 'sectionTitle')
        layout.addWidget(heading)
        self.iconLabel = QLabel(self)
        self.iconLabel.hide()
        self.hBoxLayout = QHBoxLayout()
        layout.addLayout(self.hBoxLayout)
        self.basic_options = og.executor.basic_options
        self.current_hotkey = None
        self._desired_hotkey = 'UNINIT'
        self._retry_after = 0
        self._hotkey_stop = threading.Event()
        stop = self._hotkey_stop
        self.destroyed.connect(lambda *_: stop.set())

        self.iconLabel.setFixedSize(30, 30)
        self.hBoxLayout.setAlignment(Qt.AlignVCenter)
        self.status_bar = StatusBar("test")
        self.status_bar.clicked.connect(self.status_clicked)
        self.hBoxLayout.addWidget(self.status_bar, 0, Qt.AlignLeft)
        self.hBoxLayout.addSpacing(6)

        self.capture_button = PushButton(FluentIcon.ZOOM, self.tr("Capture"), self)
        self.hBoxLayout.addWidget(self.capture_button, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(6)

        self.refresh_button = PushButton(FluentIcon.SYNC, self.tr("Refresh"), self)
        self.hBoxLayout.addWidget(self.refresh_button, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(6)

        self.start_button = PrimaryPushButton(FluentIcon.PLAY, self.tr("Start"), self)
        self.hBoxLayout.addWidget(self.start_button, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(20)

        self.hotkey_warning = QLabel(self)
        self.hotkey_warning.setWordWrap(True)
        self.hotkey_warning.setMaximumWidth(260)
        self.hotkey_warning.hide()
        self.hBoxLayout.addWidget(self.hotkey_warning)
        self.hotkey_status_changed.connect(self._show_hotkey_status)

        self.hotkey_changed.connect(self.update_status)
        self.update_status()
        self.start_button.clicked.connect(self.clicked)
        communicate.executor_paused.connect(self.update_status)
        communicate.window.connect(self.update_status)
        communicate.task.connect(self.update_task)

        self.handler = Handler(exit_event, "StartCard")
        self.handler.post(self.check_hotkey, 0.1)
        logger.debug('basic_options.start/stop: {}'.format(self.basic_options.get('Start/Stop')))

    def status_clicked(self):
        if not og.executor.paused:
            if og.executor.current_task:
                communicate.tab.emit("onetime")
            elif og.executor.active_trigger_task_count():
                communicate.tab.emit("trigger")
            else:
                communicate.tab.emit("start")
            self.status_bar.show()

    @staticmethod
    def clicked():
        if not og.executor.paused:
            og.executor.pause()
        else:
            og.app.start_controller.start()

    def update_task(self, task):
        self.update_status()

    def update_status(self):
        if header := getattr(self, 'disclosure_header', None):
            device = og.device_manager.get_preferred_device() or {}
            device_name = device.get('nick') or device.get('title') or device.get('name') or '游戏窗口'
            state = '已连接' if device.get('connected') else '未连接'
            warning = self.hotkey_warning.text()
            header.set_summary(f'{device_name} · {state}' + (f'；{warning}' if warning else ''))
        hotkey = self.current_hotkey
        suffix = f'({hotkey})' if hotkey and hotkey != 'None' else ''

        if og.executor.paused:
            device = og.device_manager.get_preferred_device()
            if device and not device['connected'] and device.get('full_path'):
                self.start_button.setText(self.tr("Start Game") + suffix)
            else:
                self.start_button.setText(self.tr("Start") + suffix)
            self.start_button.setIcon(FluentIcon.PLAY)
            self.status_bar.hide()
        else:
            self.start_button.setText(self.tr("Pause") + suffix)
            self.start_button.setIcon(FluentIcon.PAUSE)
            if not og.executor.connected():
                self.status_bar.setTitle(self.tr("Game Window Disconnected"))
                self.status_bar.setState(True)
            elif active_trigger_task_count := og.executor.active_trigger_task_count():
                if not og.executor.can_capture():
                    self.status_bar.setTitle(self.tr('Paused: PC Game Window Must Be in Front!'))
                    self.status_bar.setState(True)
                else:
                    self.status_bar.setTitle(
                        self.tr("Running") + ": " + str(active_trigger_task_count) + ' ' + self.tr("Trigger Tasks"))
                    self.status_bar.setState(False)
            elif task := og.executor.current_task:
                if not og.executor.can_capture():
                    self.status_bar.setTitle(self.tr('Paused: PC Game Window Must Be in Front!'))
                    self.status_bar.setState(True)
                elif task.enabled:
                    self.status_bar.setTitle(self.tr("Running") + ": " + task.name)
                    self.status_bar.setState(False)
                else:
                    self.status_bar.setTitle(self.tr("Waiting for task to be enabled"))
                    self.status_bar.setState(False)
            else:
                self.status_bar.setTitle(self.tr("Waiting for task to be enabled"))
                self.status_bar.setState(False)
            self.status_bar.show()

    def check_hotkey(self):
        if self._hotkey_stop.is_set():
            windll.user32.UnregisterHotKey(None, 999)
            return
        new_hotkey = self.basic_options.get('Start/Stop')
        if new_hotkey != self._desired_hotkey:
            self._desired_hotkey = new_hotkey
            self._retry_after = 0
        if new_hotkey != self.current_hotkey and time.monotonic() >= self._retry_after:
            if self.rebind_hotkey(new_hotkey):
                self.current_hotkey = new_hotkey
                self._retry_after = 0
                self.hotkey_status_changed.emit('')
            else:
                self.current_hotkey = None
                self._retry_after = time.monotonic() + 5
            self.hotkey_changed.emit()

        msg = wintypes.MSG()
        if windll.user32.PeekMessageW(byref(msg), None, 0, 0, 1):
            if msg.message == 0x0312:  # WM_HOTKEY
                logger.debug(f'hotkey pressed {msg}')
                if msg.wParam == 999:
                    self.clicked()

        self.handler.post(self.check_hotkey, 0.1)

    def _show_hotkey_status(self, text):
        self.hotkey_warning.setText(text)
        self.hotkey_warning.setVisible(bool(text))
        self.update_status()

    def rebind_hotkey(self, hotkey):
        windll.user32.UnregisterHotKey(None, 999)
        vk_map = {'F9': 0x78, 'F10': 0x79, 'F11': 0x7A, 'F12': 0x7B}

        if hotkey and hotkey != 'None' and hotkey in vk_map:
            if not windll.user32.RegisterHotKey(None, 999, 0, vk_map[hotkey]):
                code = windll.kernel32.GetLastError()
                logger.error(f"Failed to register hotkey {hotkey}; win32_error={code}")
                self.hotkey_status_changed.emit(self.tr(
                    'Hotkey {key} unavailable (error {code}). Use the button or select another key.'
                ).format(key=hotkey, code=code))
                return False
            return True
        else:
            logger.debug(f"Hotkey disabled or invalid: {hotkey}")
            return not hotkey or hotkey == 'None'
