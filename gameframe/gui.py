"""Small desktop launcher; package selection reads manifest metadata only."""

from __future__ import annotations

import json
import getpass
import hashlib
import queue
import threading
import zipfile
import uuid
from pathlib import Path

from PySide6.QtCore import QByteArray, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QMenu, QPlainTextEdit, QPushButton, QStyle,
                               QScrollArea, QSystemTrayIcon, QVBoxLayout, QWidget)

from gameframe.controller import Controller
from gameframe.packages import discover, install_archive
from gameframe.launcher_options import load_options, save_options
from gameframe.package_updates import apply_update, prepare_update, recover_updates
from gameframe.desktop_controls import HOTKEYS, HotkeyTransition, desktop_preferences
from gameframe.device_editor import DeviceEditor
from gameframe.launcher_context import load_context, local_root, save_context
from gameframe.ui_strings import apply_labels


class GameFrameWindow(QWidget):
    def __init__(self, packages_dir: Path | str, data_dir: Path | str, *, controller=None,
                 key_state=None, managed_root=None, login_argv=None, installation_root=None):
        super().__init__()
        self.setWindowTitle("GameFrame")
        self.resize(980, 800)
        self.managed_root = Path(managed_root).resolve() if managed_root is not None else None
        self.packages_dir = Path(packages_dir)
        self._context_path = Path(data_dir) / 'launcher-context.json'
        self._launcher_context = load_context(self._context_path)
        self.data_dir = local_root(self._launcher_context.get('data_root', Path(data_dir).resolve()))
        self.controller = controller if controller is not None else Controller()
        self.management_controller = Controller()
        self.overview_controller = Controller()
        self.configuration_controller = Controller()
        self._configuration_querying = False
        self._configuration_thread = None
        self._restore_pending = False
        self._account_context = None
        self._foreground_requested = False
        self._overview_thread = None
        self._overview_starting = False
        recover_updates(self.packages_dir, ensure_idle=self._assert_owners_idle)
        self.packages = discover(self.packages_dir)
        self._management_thread = None
        self._management_process = None
        self._managing = False
        self.process = None
        self._events = queue.Queue()
        self._reader = None
        self._start_thread = None
        self._install_thread = None
        self._starting = False
        self._installing = False
        self._updating = False
        self._update_thread = None
        self._pending_update = None
        self._update_management_error = None
        self._stopping = False
        self._closing = False
        self._overlay = None
        self._cleanup_done = False
        self._paused = False
        self._exit_requested = False
        self._live_routes = {}
        self._reserved_hotkeys = []
        self._hotkey = HotkeyTransition() if key_state is None else HotkeyTransition(key_state)
        self._force_close = False

        self.package_select = QComboBox()
        for manifest in self.packages:
            self.package_select.addItem(f"{manifest.title}  {manifest.version}")
        selected = self._launcher_context['selected_package']
        self.package_select.setCurrentIndex(next((i for i, item in enumerate(self.packages)
                                                 if item.id == selected), 0))
        self.task_list = QListWidget()
        self.task_list.setMaximumHeight(130)
        self.category_select = QComboBox()
        self._all_tasks = ()
        self._task_titles = {}
        self._launcher_labels = {}
        self.sequence_select = QComboBox()
        self.account_select = QComboBox()
        self.account_context_label = QLabel('请刷新账号上下文或打开游戏包管理')
        self.account_context_label.setWordWrap(True)
        self.context_refresh_button = QPushButton('刷新账号上下文')
        self._visible_tasks = ()
        self.mode_label = QLabel()
        self.config_edit = QPlainTextEdit()
        self.config_edit.setMaximumHeight(100)
        self.config_label = QLabel('Task config JSON')
        self.device_edit = QPlainTextEdit()
        self.device_edit.setPlainText('{"type": "replay", "frames": []}')
        self.device_editor = DeviceEditor()
        self.device_edit.setMaximumHeight(90)
        self.compatibility_label = QLabel()
        self.compatibility_label.setWordWrap(True)
        self.pause_hotkey = QComboBox()
        self.pause_hotkey.addItems(HOTKEYS)
        self.tray_notifications = QCheckBox('系统托盘通知')
        self.close_to_tray = QCheckBox('关闭窗口时最小化到托盘')
        self.notification_label = QLabel()
        self.notification_label.setWordWrap(True)
        self.screenshot_button = QPushButton('保存截图')
        self.ocr_button = QPushButton('截图并识别文字')
        self.paths_button = QPushButton('打开资料目录')
        self.change_root_button = QPushButton('选择本地资料根')
        self.user_context_label = QLabel()
        self.user_context_label.setWordWrap(True)
        self.restore_services = QCheckBox('打开应用时恢复已保存辅助服务')
        self.restore_services.setChecked(self._launcher_context['restore_services'])
        self._preferences_loading = False
        self.tray = QSystemTrayIcon(self.style().standardIcon(QStyle.SP_ComputerIcon), self)
        menu = QMenu(self)
        menu.addAction('显示窗口', self.showNormal)
        menu.addAction('暂停 / 恢复', self.toggle_pause)
        menu.addAction('退出', self._exit_from_tray)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.showNormal()
            if reason == QSystemTrayIcon.DoubleClick else None)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumHeight(140)
        self.status_label = QLabel("Ready")
        self.start_button = QPushButton("Start")
        self.session_button = QPushButton('仅启动会话')
        self.stop_button = QPushButton("Stop")
        self.pause_button = QPushButton("Pause")
        self.install_button = QPushButton("Install gamepack")
        self.update_button = QPushButton('Update gamepack')
        self.disable_button = QPushButton('Disable selected service')
        self.disable_button.setEnabled(False)
        self.manage_button = QPushButton('Manage gamepack')
        self.overview_button = QPushButton('Read-only overview')
        self.refresh_tasks_button = QPushButton('Refresh tasks')
        self.reload_tasks_button = QPushButton('Apply user task reload')
        self.reload_tasks_button.setEnabled(False)
        self.reload_characters_button = QPushButton('Apply character code reload')
        self.reload_characters_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.pause_button.setEnabled(False)

        form = QFormLayout()
        form.addRow("Package", self.package_select)
        form.addRow(self.user_context_label, self.change_root_button)
        form.addRow(self.restore_services)
        form.addRow("Execution mode", self.mode_label)
        form.addRow('任务分类', self.category_select)
        form.addRow('当前序列', self.sequence_select)
        form.addRow('当前账号', self.account_select)
        form.addRow(self.account_context_label, self.context_refresh_button)
        form.addRow("Tasks", self.task_list)
        form.addRow(self.config_label, self.config_edit)
        form.addRow('设备', self.device_editor)
        form.addRow('高级设备 JSON', self.device_edit)
        form.addRow('能力匹配', self.compatibility_label)
        form.addRow('启动 / 暂停 / 恢复热键', self.pause_hotkey)
        form.addRow(self.tray_notifications, self.close_to_tray)
        from gameframe.update_controls import attach_update_controls
        attach_update_controls(self, form, managed_root=self.managed_root)
        from gameframe.login_start_controls import attach_login_start
        attach_login_start(self, form, launch_argv=login_argv,
                           installation_root=installation_root, managed_root=self.managed_root)
        buttons = QGridLayout()
        for index, button in enumerate((self.start_button, self.session_button, self.stop_button, self.pause_button,
                self.disable_button, self.manage_button, self.overview_button, self.install_button,
                self.update_button, self.refresh_tasks_button, self.reload_tasks_button,
                self.reload_characters_button)):
            buttons.addWidget(button, index // 4, index % 4)
        layout = QVBoxLayout(self)
        form_body = QWidget(self)
        form_body.setLayout(form)
        form_scroll = QScrollArea(self)
        form_scroll.setWidgetResizable(True)
        form_scroll.setWidget(form_body)
        layout.addWidget(form_scroll, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.status_label)
        tools = QHBoxLayout()
        for button in (self.screenshot_button, self.ocr_button, self.paths_button):
            tools.addWidget(button)
        layout.addLayout(tools)
        layout.addWidget(self.notification_label)
        layout.addWidget(QLabel("Worker output"))
        layout.addWidget(self.output)

        self.package_select.currentIndexChanged.connect(self._select_package)
        self.task_list.currentRowChanged.connect(self._select_task)
        self.category_select.currentIndexChanged.connect(self._fill_tasks)
        self.sequence_select.currentIndexChanged.connect(lambda: self._change_account_context('sequence'))
        self.account_select.currentIndexChanged.connect(lambda: self._change_account_context('account'))
        self.context_refresh_button.clicked.connect(self.refresh_account_context)
        self.start_button.clicked.connect(self.start_selected)
        self.session_button.clicked.connect(self.start_session)
        self.restore_services.toggled.connect(self._save_launcher_context)
        self.change_root_button.clicked.connect(self.choose_data_root)
        self.stop_button.clicked.connect(self.stop_selected)
        self.pause_button.clicked.connect(self.toggle_pause)
        self.install_button.clicked.connect(self.install_selected)
        self.update_button.clicked.connect(self.update_selected)
        self.disable_button.clicked.connect(self.disable_selected)
        self.manage_button.clicked.connect(self.manage_selected)
        self.overview_button.clicked.connect(self.overview_selected)
        self.refresh_tasks_button.clicked.connect(self.refresh_tasks)
        self.reload_tasks_button.clicked.connect(self.reload_user_tasks)
        self.reload_characters_button.clicked.connect(self.reload_character_code)
        self.device_editor.options_changed.connect(self._device_fields_changed)
        self.device_edit.textChanged.connect(self._device_json_changed)
        self.pause_hotkey.currentTextChanged.connect(self._desktop_changed)
        self.tray_notifications.toggled.connect(self._desktop_changed)
        self.close_to_tray.toggled.connect(self._desktop_changed)
        self.screenshot_button.clicked.connect(lambda: self.inspect_frame(False))
        self.ocr_button.clicked.connect(lambda: self.inspect_frame(True))
        self.paths_button.clicked.connect(self.open_data_directory)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._drain_events)
        self.timer.start(50)
        if 'window_geometry' in self._launcher_context:
            if not self.restoreGeometry(QByteArray(bytes.fromhex(self._launcher_context['window_geometry']))):
                raise ValueError('Invalid window geometry')
        self._select_package(self.package_select.currentIndex())
        QTimer.singleShot(0, self.managed_update_bindings.startup)
        QTimer.singleShot(0, self._restore_saved_session)

    def _save_launcher_context(self, *_):
        manifest = self._manifest()
        self._launcher_context.update(selected_package=manifest.id if manifest else None,
            restore_services=self.restore_services.isChecked(), data_root=str(self.data_dir),
            window_geometry=bytes(self.saveGeometry().toHex()).decode('ascii'))
        save_context(self._context_path, self._launcher_context)

    def choose_data_root(self):
        try:
            self._assert_update_idle()
            chosen = QFileDialog.getExistingDirectory(self, '选择当前 Windows 用户的本地资料根', str(self.data_dir))
            if not chosen:
                return
            self.data_dir = local_root(chosen)
            self._select_package(self.package_select.currentIndex())
        except (OSError, ValueError, RuntimeError) as error:
            self._error(error)

    def _restore_saved_session(self):
        manifest = self._manifest()
        if not self.restore_services.isChecked() or manifest is None or not manifest.supports_session:
            return
        path = self.data_dir / manifest.id / 'launcher.json'
        if not path.is_file():
            self.status_label.setText('请配置设备并启动会话；辅助服务开关保留在游戏包资料中。')
            return
        if manifest.configuration:
            self._restore_pending = True
            self.refresh_account_context()
            return
        self.start_session()

    def refresh_account_context(self):
        return self._query_account_context('get-context')

    def _change_account_context(self, field):
        control = self.sequence_select if field == 'sequence' else self.account_select
        if self._account_context is not None and control.currentIndex() >= 0:
            self._query_account_context('set-context', **{field: control.currentData()})

    def _query_account_context(self, command, **values):
        manifest = self._manifest()
        if (manifest is None or not manifest.configuration or self._configuration_querying
                or self._foreground_requested or self._closing or self._updating or self._starting):
            return False
        if self.process is not None:
            request_id = str(uuid.uuid4())
            try:
                self.controller.request_live(command, request_id, **values)
            except Exception as error:
                self._error(error)
                return False
            else:
                self._live_routes[request_id] = 'account-context'
            return True
        self._configuration_querying = True
        self.package_select.setEnabled(False)
        self._configuration_thread = threading.Thread(target=self._query_context_worker,
            args=(manifest, self.data_dir / manifest.id, command, values), daemon=True)
        self._configuration_thread.start()
        return True

    def _query_context_worker(self, manifest, data_dir, command, values):
        try:
            process = self.configuration_controller.start_configuration(manifest, data_dir=data_dir)
            output, _ = process.communicate(json.dumps({'command': command, **values}) + '\n', timeout=30)
            responses = [json.loads(line) for line in output.splitlines() if line.startswith('{')]
            response = next((item for item in reversed(responses) if item.get('event') == 'configuration-response'), None)
            if response is None:
                failure = next((item for item in responses if item.get('event') == 'configuration-failed'), None)
                raise RuntimeError(failure['error']['message'] if failure else
                                   f'Configuration process exited without a response ({process.returncode})')
            if process.returncode != 0:
                raise RuntimeError(f'Configuration process exited with code {process.returncode}')
            outcome = ('account-context', response)
        except Exception as error:
            outcome = ('context-error', error)
        finally:
            try:
                self.configuration_controller.close()
            except Exception as error:
                outcome = ('context-error', error)
        self._events.put(outcome)

    def _apply_account_context(self, event):
        if not event['ok']:
            self._restore_pending = False
            self.account_context_label.setText(event['error']['message'])
            return
        schema = event.get('schema', {})
        self._launcher_labels = schema.get('launcher_labels', {})
        apply_labels(self, self._launcher_labels)
        self.device_editor.apply_labels(self._launcher_labels)
        self.managed_update_bindings.localize(self._launcher_labels)
        help_text = '启动会话 / 暂停 / 恢复，保留服务启用设置。'
        self.pause_hotkey.setToolTip(self._launcher_labels.get(help_text, help_text))
        self._task_titles = {task['id']: task['name'] for task in schema.get('tasks', ())}
        by_id = {task['id']: task for task in schema.get('tasks', ())}
        category_labels = {task.category: by_id[task.id]['category'] for task in self._all_tasks
                           if task.id in by_id and 'category' in by_id[task.id]}
        for index in range(self.category_select.count()):
            category = self.category_select.itemData(index)
            self.category_select.setItemText(index, category_labels.get(category, category) if category else
                self._launcher_labels.get('全部任务', '全部任务'))
        template = 'Windows 用户：{user}\n资料根：{root}\n游戏包资料：{package_root}'
        self.user_context_label.setText(self._launcher_labels.get(template, template).format(
            user=getpass.getuser(), root=self.data_dir, package_root=self.data_dir / self._manifest().id))
        context = event.get('result', schema.get('account_context'))
        self._account_context = context
        for control, options, current in ((self.sequence_select, context['sequences'], context['sequence']),
                                          (self.account_select, context['accounts'], context['account'])):
            control.blockSignals(True)
            try:
                control.clear()
                for option in options:
                    control.addItem(option['label'], option['value'])
                control.setCurrentIndex(control.findData(current))
            finally:
                control.blockSignals(False)
        verified = context['verified_account']
        verified_template = '已核验运行账号：{account}'
        self.account_context_label.setText(context['summary'] + ('\n' + self._launcher_labels.get(
            verified_template, verified_template).format(account=verified['label']) if verified else '')
                                          + (f"\n{context['reason']}" if context['reason'] else ''))
        self._fill_tasks()
        if self._restore_pending:
            self._restore_pending = False
            self.start_session()

    def _set_label(self, control, text):
        control.setProperty('launcher_label', text)
        control.setText(self._launcher_labels.get(text, text))

    def start_session(self):
        manifest = self._manifest()
        if (manifest is None or not manifest.supports_session or self.process is not None
                or self._starting or self._configuration_querying or self._installing or self._closing or self._updating):
            return
        try:
            _, device = self._native_options(task_config=False)
            missing = manifest.session_required_capabilities - self.device_editor.capabilities()
            if missing:
                raise ValueError('设备缺少会话所需能力：' + ', '.join(sorted(missing)))
            options = load_options(self.data_dir / manifest.id / 'launcher.json')
            options['device'] = device
            save_options(self.data_dir / manifest.id / 'launcher.json', options)
            self._save_launcher_context()
        except (OSError, ValueError) as error:
            self._error(error)
            return
        self._begin_start(manifest, None, {}, device)

    def _exit_from_tray(self):
        self._force_close = True
        self.close()

    def _device_fields_changed(self, options):
        self.device_edit.blockSignals(True)
        self.device_edit.setPlainText(json.dumps(options, ensure_ascii=False, indent=2))
        self.device_edit.blockSignals(False)
        self._device_compatibility()

    def _device_json_changed(self):
        try:
            self.device_editor.set_options(json.loads(self.device_edit.toPlainText()))
        except (TypeError, ValueError) as error:
            self.compatibility_label.setText('设备配置无效：' + str(error))
        else:
            self._device_compatibility()

    def _device_compatibility(self):
        row = self.task_list.currentRow()
        if not 0 <= row < len(self._visible_tasks):
            self.compatibility_label.clear()
            return
        required = self._visible_tasks[row].required_capabilities
        missing = set(required) - self.device_editor.capabilities()
        self.compatibility_label.setText('设备缺少：' + ', '.join(sorted(missing)) if missing else
            '设备能力匹配；实际连接与游戏运行尚需验证。')

    def _desktop_changed(self, *_):
        if self._preferences_loading:
            return
        manifest = self._manifest()
        if manifest is None or manifest.execution != 'native':
            return
        try:
            path = self.data_dir / manifest.id / 'launcher.json'
            options = load_options(path)
            options.update(pause_hotkey=self.pause_hotkey.currentText(),
                tray_notifications=self.tray_notifications.isChecked(), close_to_tray=self.close_to_tray.isChecked())
            save_options(path, options)
            self._hotkey.set_key(options['pause_hotkey'])
            self._hotkey_conflict()
        except (OSError, ValueError) as error:
            self._error(error)

    def _hotkey_conflict(self):
        key = self.pause_hotkey.currentText()
        conflict = key != 'None' and key.casefold() in {str(value).casefold() for value in self._reserved_hotkeys}
        self.pause_hotkey.setToolTip('与游戏技能键冲突，请选择其他热键。' if conflict else
                                    '启动会话 / 暂停 / 恢复，保留服务启用设置。')
        self._hotkey.set_key('None' if conflict else key)

    def open_data_directory(self):
        manifest = self._manifest()
        if manifest is not None:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            path = (self.data_dir / manifest.id).resolve()
            path.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def inspect_frame(self, ocr=False):
        request_id = str(uuid.uuid4())
        try:
            self.controller.request_live('inspect-frame', request_id, ocr=ocr)
        except Exception as error:
            self._error(error)
        else:
            self._live_routes[request_id] = 'inspection'
            self.status_label.setText('已请求运行进程采集；等待安全任务边界。')

    def _notify(self, event):
        name = event.get('event')
        if name == 'combat-notification' or (name == 'task-log' and event.get('notify')):
            title = event.get('title') or 'GameFrame'
            message = str(event.get('message', ''))
            failure = event.get('error') or event.get('level') == 'error'
        elif name in {'session-task-finished', 'session-task-failed'}:
            title = str(event['task_id'])
            failure = name == 'session-task-failed'
            message = str(event['error']) if failure else '任务已完成。'
        else:
            return
        self.notification_label.setText(str(title) + '：' + message)
        if self.tray_notifications.isChecked() and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
            self.tray.showMessage(str(title), message,
                QSystemTrayIcon.Critical if failure else QSystemTrayIcon.Information)

    def _management_live_request(self, line):
        try:
            event = json.loads(line)
        except ValueError:
            return False
        if not isinstance(event, dict) or event.get('event') != 'live-request':
            return False
        request = {key: value for key, value in event.items() if key != 'event'}
        request_id = request.get('request_id')
        try:
            if not isinstance(request_id, str) or not request_id or request_id in self._live_routes:
                raise ValueError('A live request needs a unique string request_id')
            request.pop('request_id')
            command = request.pop('command')
            if self._stopping or self._closing:
                raise RuntimeError('The execution owner is stopping')
            self.controller.request_live(command, request_id, **request)
        except Exception as error:
            self._deliver_management({'event': 'live-response', 'request_id': request_id, 'ok': False,
                'error': {'type': type(error).__name__, 'message': str(error)}})
        else:
            self._live_routes[request_id] = 'management'
        return True

    def _deliver_management(self, event):
        try:
            self.management_controller.deliver_live_response(event)
        except Exception as error:
            self._error(error)

    def _live_response(self, event):
        if event.get('event') not in {'configuration-response', 'live-response'}:
            return False
        destination = self._live_routes.pop(event.get('request_id'), None)
        if destination == 'management':
            self._deliver_management(event)
        elif destination == 'hotkeys':
            if event['ok']:
                self._reserved_hotkeys = event['schema'].get('reserved_hotkeys', [])
                self._hotkey_conflict()
                if 'account_context' in event['schema']:
                    self._apply_account_context(event)
            else:
                self._error(RuntimeError(event['error']['message']))
        elif destination == 'inspection':
            if event['ok']:
                result = event['result']
                self.status_label.setText('截图已保存：' + result['path'])
                if result.get('text'):
                    self.output.appendPlainText(result['text'])
            else:
                self._error(RuntimeError(event['error']['message']))
        elif destination == 'account-context':
            self._apply_account_context(event)
        return True

    def _manifest(self):
        index = self.package_select.currentIndex()
        return self.packages[index] if index >= 0 else None

    def _select_package(self, index):
        self.managed_update_bindings.refresh()
        self.managed_update_bindings.localize({})
        manifest = self._manifest()
        self.user_context_label.setText(f'Windows 用户：{getpass.getuser()}\n资料根：{self.data_dir}'
                                       + (f'\n游戏包资料：{self.data_dir / manifest.id}' if manifest else ''))
        self.overview_button.setEnabled(manifest is not None and manifest.overview
                                        and not self._closing and not self._updating
                                        and not self._installing and not self._overview_starting
                                        and (self.overview_controller.process is None
                                             or self.overview_controller.process.poll() is not None))
        self._visible_tasks = ()
        self._all_tasks = ()
        self._account_context = None
        self._task_titles = {}
        self._launcher_labels = {}
        apply_labels(self, {})
        self.device_editor.apply_labels({})
        self.sequence_select.clear()
        self.account_select.clear()
        self.task_list.clear()
        if manifest is None:
            self.mode_label.setText("No installed packages")
            self.start_button.setEnabled(False)
            self.manage_button.setEnabled(False)
            self.update_button.setEnabled(False)
            return
        try:
            self._all_tasks = tuple(sorted((task for task in manifest.available_tasks(self.data_dir / manifest.id)
                                            if task.visible), key=lambda task: task.order))
        except (OSError, ValueError) as error:
            self.start_button.setEnabled(False)
            self.disable_button.setEnabled(False)
            self.config_edit.clear()
            self._error(error)
            return
        legacy = manifest.execution == "legacy-application"
        self.manage_button.setEnabled(manifest.management and (self.process is None or manifest.supports_session) and not self._managing
                                      and not self._starting and not self._installing and not self._closing
                                      and not self._updating)
        self.update_button.setEnabled(self.process is None and not self._managing and not self._starting
                                      and not self._stopping and not self._installing and not self._closing
                                      and not self._updating and self._is_installed(manifest))
        self.mode_label.setText(
            "Compatibility: original application, dependencies and production configuration"
            if legacy else "Native GameFrame worker")
        self.config_edit.setEnabled(not legacy)
        self.config_label.setText('本次运行覆盖配置（长期设置在管理窗口保存）'
                                  if self._managed_config(manifest) else 'Task config JSON')
        self.device_edit.setEnabled(not legacy)
        self.device_editor.setEnabled(not legacy)
        for control in (self.pause_hotkey, self.tray_notifications, self.close_to_tray):
            control.setEnabled(not legacy)
        if legacy:
            self.config_edit.setPlainText("Production application configuration is used; this editor does not apply.")
            self.device_edit.setPlainText("Production application device selection is used; this editor does not apply.")
        else:
            options = load_options(self.data_dir / manifest.id / 'launcher.json')
            self.device_edit.setPlainText(json.dumps(options['device'], ensure_ascii=False, indent=2))
            preferences = desktop_preferences(self.data_dir / manifest.id, options)
            self._preferences_loading = True
            try:
                self.pause_hotkey.setCurrentText(preferences['pause_hotkey'])
                self.tray_notifications.setChecked(preferences['tray_notifications'])
                self.close_to_tray.setChecked(preferences['close_to_tray'])
            finally:
                self._preferences_loading = False
            self._reserved_hotkeys = []
            self._hotkey.set_key(preferences['pause_hotkey'])
        self.category_select.blockSignals(True)
        try:
            self.category_select.clear()
            self.category_select.addItem('全部任务', '')
            for category in dict.fromkeys(task.category for task in self._all_tasks if task.category):
                self.category_select.addItem(category, category)
        finally:
            self.category_select.blockSignals(False)
        self._fill_tasks()
        if self._visible_tasks:
            row = next((i for i, task in enumerate(self._visible_tasks)
                        if not legacy and task.id == options.get('selected_task')), 0)
            self.task_list.setCurrentRow(row)
        self.start_button.setEnabled(bool(self._visible_tasks) and self.process is None
                                     and not self._starting and not self._installing and not self._closing
                                     and (not self._managing or manifest.supports_session) and not self._updating)
        self._save_launcher_context()

    def _fill_tasks(self, *_):
        selected = (self._visible_tasks[self.task_list.currentRow()].id
                    if 0 <= self.task_list.currentRow() < len(self._visible_tasks) else None)
        category = self.category_select.currentData() or ''
        self._visible_tasks = tuple(task for task in self._all_tasks if not category or task.category == category)
        self.task_list.clear()
        for task in self._visible_tasks:
            self.task_list.addItem(f'{self._task_titles.get(task.id, task.title)}  [{task.kind}]  ({task.id})')
        if self._visible_tasks:
            self.task_list.setCurrentRow(next((i for i, task in enumerate(self._visible_tasks) if task.id == selected), 0))

    def refresh_tasks(self):
        manifest = self._manifest()
        if manifest is None:
            return
        row = self.task_list.currentRow()
        selected = self._visible_tasks[row].id if 0 <= row < len(self._visible_tasks) else None
        try:
            tasks = tuple(task for task in manifest.available_tasks(self.data_dir / manifest.id) if task.visible)
        except Exception as error:
            self._error(error)
            return
        self._all_tasks = tuple(sorted(tasks, key=lambda task: task.order))
        self._fill_tasks()
        if self._visible_tasks:
            self.task_list.setCurrentRow(next((index for index, task in enumerate(self._visible_tasks) if task.id == selected), 0))

    def reload_user_tasks(self):
        if self.process is None or self._stopping or self._closing or self._updating:
            return
        try:
            self.controller.request_user_task_reload()
        except Exception as error:
            self._error(error)
        else:
            self.status_label.setText('User task reload requested; waiting for the execution owner')

    def reload_character_code(self):
        if self.process is None or self._stopping or self._closing or self._updating:
            return
        try:
            self.controller.request_character_reload()
        except Exception as error:
            self._error(error)
        else:
            self.status_label.setText('Character reload requested; waiting for the execution owner')

    def _select_task(self, row):
        manifest = self._manifest()
        if manifest is not None and 0 <= row < len(self._visible_tasks) and manifest.execution == "native":
            task = self._visible_tasks[row]
            options = load_options(self.data_dir / manifest.id / 'launcher.json')
            config = {} if self._managed_config(manifest) else options['tasks'].get(task.id, task.default_config)
            self.config_edit.setPlainText(json.dumps(config,
                                                      ensure_ascii=False, indent=2))
            self.disable_button.setEnabled(self.process is not None and manifest.supports_session
                                           and task.kind == 'service' and not self._stopping)
            self._device_compatibility()

    def _managed_config(self, manifest):
        return manifest.execution == 'native' and manifest.supports_session and manifest.management

    def _native_options(self, *, task_config=True):
        config = json.loads(self.config_edit.toPlainText()) if task_config else {}
        device = json.loads(self.device_edit.toPlainText())
        if not isinstance(config, dict) or not isinstance(device, dict) or "type" not in device:
            raise ValueError("Native config and device must be JSON objects; device needs a type")
        self.device_editor.options()  # Invalid unfinished fields must not launch the last valid JSON.
        self.device_editor.set_options(device)  # A rejected advanced backend must not use stale form state.
        return config, device

    def _error(self, error):
        message = f"{type(error).__name__}: {error}"
        self.status_label.setText(message)
        self.output.appendPlainText(message)

    def start_selected(self):
        manifest = self._manifest()
        row = self.task_list.currentRow()
        if (manifest is None or row < 0
                or self._starting or self._configuration_querying or self._installing or self._closing or (self._managing and not manifest.supports_session) or self._updating
                or (self.process is not None and not manifest.supports_session)):
            return
        task = self._visible_tasks[row]
        try:
            config, device = self._native_options() if manifest.execution == "native" else (None, None)
            if manifest.execution == 'native':
                missing = task.required_capabilities - self.device_editor.capabilities()
                if missing:
                    raise ValueError('设备缺少任务所需能力：' + ', '.join(sorted(missing)))
                path = self.data_dir / manifest.id / 'launcher.json'
                options = load_options(path)
                if self._managed_config(manifest):
                    options['tasks'] = {}
                else:
                    options['tasks'][task.id] = config
                options['device'] = device
                options['selected_task'] = task.id
                save_options(path, options)
            if self.process is not None:
                if not manifest.supports_session or self._stopping:
                    return
                if task.kind == 'service':
                    self.controller.set_service(task.id, True, config)
                else:
                    self.controller.request_task(task.id, config)
                    self._foreground_requested = True
                self.status_label.setText(f'Requested {task.title}')
                return
        except Exception as error:
            self._error(error)
            return
        self._begin_start(manifest, task.id, config, device)

    def _begin_start(self, manifest, task_id, config, device):
        self.output.clear()
        self._foreground_requested = task_id is not None and manifest.task(task_id, self.data_dir / manifest.id).kind != 'service'
        self._exit_requested = False
        self._starting = True
        self.device_edit.setEnabled(False)
        self.device_editor.setEnabled(False)
        self.package_select.setEnabled(False)
        self.status_label.setText(f"Starting {manifest.id}/{task_id or 'session'} ({manifest.execution})")
        self.start_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.manage_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self._start_thread = threading.Thread(target=self._start_worker,
                                              args=(manifest, task_id, config, device), daemon=True)
        self._start_thread.start()

    def _start_worker(self, manifest, task_id, config, device):
        try:
            process = self.controller.start(manifest, task_id, data_dir=self.data_dir / manifest.id,
                                            config=config, device=device,
                                            session=manifest.supports_session)
        except Exception as error:
            self._events.put(("start-error", error))
        else:
            self._events.put(("started", (manifest, task_id, process)))

    def _read_output(self, process):
        try:
            for line in process.stdout:
                self._events.put(("line", line.rstrip("\r\n")))
            self._events.put(("exit", process.wait()))
        except Exception as error:
            self._events.put(("error", error))

    def install_selected(self):
        if (self.process is not None or self._starting or self._installing or self._closing
                or self._managing or self._stopping or self._updating):
            return
        filename, _filter = QFileDialog.getOpenFileName(
            self, "Install gamepack", "", "Gamepack ZIP (*.zip)")
        if not filename:
            return
        self._installing = True
        self.start_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.manage_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.status_label.setText("Installing gamepack…")
        self._install_thread = threading.Thread(target=self._install_worker,
                                                args=(filename,), daemon=True)
        self._install_thread.start()

    def _install_worker(self, filename):
        try:
            manifest = install_archive(filename, self.packages_dir)
        except Exception as error:
            self._events.put(("install-error", error))
        else:
            self._events.put(("install-done", manifest.id))

    def _assert_owners_idle(self):
        self.controller.assert_idle()
        self.management_controller.assert_idle()
        self.overview_controller.assert_idle()
        self.configuration_controller.assert_idle()

    def _assert_update_idle(self):
        if self._starting or self._configuration_querying or self._stopping or self._managing or self._installing:
            raise RuntimeError('A package owner or installation is still active')
        self._assert_owners_idle()

    def _is_installed(self, manifest):
        return (manifest.root == self.packages_dir.resolve() / manifest.id
                and (manifest.root / 'files.json').is_file())

    def update_selected(self):
        if (self.process is not None or self._starting or self._stopping or self._managing
                or self._installing or self._updating or self._closing):
            return
        manifest = self._manifest()
        if manifest is None:
            return
        if not self._is_installed(manifest):
            self._error(ValueError('Only installed indexed gamepacks can be updated; source checkouts are excluded'))
            return
        filename, _filter = QFileDialog.getOpenFileName(self, 'Update gamepack', '', 'Gamepack ZIP (*.zip)')
        if filename:
            self._start_update_prepare({'archive': str(Path(filename).resolve()), 'package_id': manifest.id,
                                        'current_version': manifest.version})

    def _start_update_prepare(self, request):
        manifest = self._manifest()
        if self._updating or self._closing:
            raise RuntimeError('A package update or application close is already in progress')
        if manifest is None or not self._is_installed(manifest):
            raise ValueError('Only installed indexed gamepacks can be updated; source checkouts are excluded')
        if request['package_id'] != manifest.id or request['current_version'] != manifest.version:
            raise ValueError('Update request does not match the selected installed package')
        self._updating = True
        self.overview_button.setEnabled(False)
        self._update_management_error = None
        self.package_select.setEnabled(False)
        self.start_button.setEnabled(False)
        self.manage_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.status_label.setText('Verifying gamepack update…')
        self._update_thread = threading.Thread(target=self._prepare_update_worker, args=(request,), daemon=True)
        self._update_thread.start()

    def _prepare_update_worker(self, request):
        try:
            if self._overview_thread is not None:
                self._overview_thread.join()
            self.overview_controller.close()
            self.overview_controller.assert_idle()
            archive = Path(request['archive'])
            if not archive.is_absolute():
                raise ValueError('Update archive must be an absolute path')
            if 'sha256' in request:
                with archive.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                if archive.stat().st_size != request['size'] or digest != request['sha256']:
                    raise ValueError('Update archive does not match its published SHA256/size')
            target = request.get('target_version')
            if target is None:
                with zipfile.ZipFile(archive) as bundle:
                    names = [name for name in bundle.namelist()
                             if len(name.split('/')) == 2 and name.endswith('/manifest.json')]
                    if len(names) != 1:
                        raise ValueError('A gamepack ZIP must contain one package manifest')
                    target = json.loads(bundle.read(names[0]))['version']
            plan = prepare_update(archive, self.packages_dir, package_id=request['package_id'],
                                  current_version=request['current_version'], target_version=target)
        except Exception as error:
            self._events.put(('update-error', error))
        else:
            self._events.put(('update-prepared', plan))

    def overview_selected(self):
        manifest = self._manifest()
        if (manifest is None or not manifest.overview or self._closing or self._updating
                or self._installing or self._overview_starting):
            return
        self._overview_starting = True
        self.overview_button.setEnabled(False)
        self._overview_thread = threading.Thread(target=self._overview_worker, args=(manifest,), daemon=True)
        self._overview_thread.start()

    def _overview_worker(self, manifest):
        try:
            process = self.overview_controller.start_overview(manifest, data_dir=self.data_dir / manifest.id)
        except Exception as error:
            self._events.put(('overview-error', error))
        else:
            self._events.put(('overview-started', process))
            threading.Thread(target=self._read_overview_output, args=(process,), daemon=True).start()

    def _read_overview_output(self, process):
        try:
            for line in process.stdout:
                self._events.put(('overview-line', line.rstrip()))
            self._events.put(('overview-exit', process.wait()))
        except Exception as error:
            self._events.put(('overview-error', error))

    def _management_update_status(self, line):
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            return
        if isinstance(request, dict) and request.get('event') == 'gamepack-update-ready':
            try:
                # A management request always includes the verified release envelope.
                for field in ('archive', 'package_id', 'current_version', 'target_version', 'sha256', 'size'):
                    request[field]
                self._start_update_prepare(request)
            except Exception as error:
                self._error(error)

    def _apply_pending_update(self):
        if (self._pending_update is None or self._closing or self._managing
                or self._starting or self._stopping or self._installing):
            return
        if self._update_management_error is not None:
            self._finish_update(error=self._update_management_error)
            return
        try:
            self._assert_update_idle()
        except Exception as error:
            self._finish_update(error=error)
            return
        self.status_label.setText('Applying gamepack update…')
        plan = self._pending_update
        self._pending_update = None
        self._update_thread = threading.Thread(target=self._apply_update_worker, args=(plan,), daemon=True)
        self._update_thread.start()

    def _apply_update_worker(self, plan):
        try:
            manifest = apply_update(plan, ensure_idle=self._assert_update_idle)
        except Exception as error:
            self._events.put(('update-error', error))
        else:
            self._events.put(('update-done', manifest.id))

    def _finish_update(self, *, package_id=None, error=None):
        self._updating = False
        self._pending_update = None
        self.package_select.setEnabled(not self._closing and not self._managing)
        if package_id is not None:
            self._reload_packages(package_id)
            self.status_label.setText(f'Updated {package_id}')
        else:
            self._select_package(self.package_select.currentIndex())
            self._error(error)
        self.install_button.setEnabled(not self._closing and not self._managing and self.process is None)

    def _reload_packages(self, selected_id):
        self.packages = discover(self.packages_dir)
        self.package_select.blockSignals(True)
        try:
            self.package_select.clear()
            for manifest in self.packages:
                self.package_select.addItem(f"{manifest.title}  {manifest.version}")
            index = next(i for i, manifest in enumerate(self.packages) if manifest.id == selected_id)
            self.package_select.setCurrentIndex(index)
        finally:
            self.package_select.blockSignals(False)
        self._select_package(index)

    def manage_selected(self):
        manifest = self._manifest()
        if (manifest is None or not manifest.management or (self.process is not None and not manifest.supports_session)
                or self._starting or self._installing or self._closing or self._managing or self._updating):
            return
        self._managing = True
        self.start_button.setEnabled(False)
        self.manage_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.package_select.setEnabled(False)
        self._management_thread = threading.Thread(target=self._manage_worker,
                                                   args=(manifest,), daemon=True)
        self._management_thread.start()

    def _manage_worker(self, manifest):
        try:
            process = self.management_controller.start_management(
                manifest, data_dir=self.data_dir / manifest.id)
        except Exception as error:
            self._events.put(('management-error', error))
        else:
            self._events.put(('management-started', process))

    def _read_management_output(self, process):
        try:
            for line in process.stdout:
                self._events.put(('management-line', line.rstrip('\r\n')))
            self._events.put(('management-exit', process.wait()))
        except Exception as error:
            self._events.put(('management-error', error))

    def stop_selected(self):
        if self.process is None or self._stopping:
            return
        self._clear_overlay()
        self._stopping = True
        self.stop_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.disable_button.setEnabled(False)
        self.status_label.setText("Stopping worker…")
        threading.Thread(target=self._stop_worker, daemon=True).start()

    def disable_selected(self):
        manifest = self._manifest()
        row = self.task_list.currentRow()
        if self.process is None or self._stopping or self._closing or row < 0:
            return
        task = self._visible_tasks[row]
        if manifest.supports_session and task.kind == 'service':
            try:
                self.controller.set_service(task.id, False)
            except Exception as error:
                self._error(error)
            else:
                self.status_label.setText(f'Disable requested: {task.title}')

    def toggle_pause(self):
        if self.process is None or self._stopping or self._closing:
            return
        try:
            if self._paused:
                self.controller.resume()
            else:
                self.controller.pause()
        except Exception as error:
            self._error(error)
        else:
            self.pause_button.setEnabled(False)
            self.status_label.setText('Resume requested' if self._paused else 'Pause requested')

    def _clear_overlay(self):
        if self._overlay is not None:
            self._overlay.clear()

    def _overlay_event(self, event):
        if event.get('event') not in {'overlay-update', 'overlay-clear'}:
            return False
        try:
            if event['event'] == 'overlay-update' and not self._closing and not self._stopping:
                if self._overlay is None:
                    from gameframe.overlay import PatchOverlay
                    self._overlay = PatchOverlay()
                self._overlay.apply_event(event)
            elif event['event'] == 'overlay-clear' and self._overlay is not None:
                self._overlay.apply_event(event)
        except Exception as error:
            self._clear_overlay()
            self._error(error)
        return True

    def _pause_status(self, line):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return False  # Worker output also includes human-readable dependency logs.
        if not isinstance(event, dict):
            return False
        if self._live_response(event):
            return True  # Private results go only to their requesting UI.
        if self._overlay_event(event):
            return True
        self._notify(event)
        if isinstance(event, dict) and event.get('event') == 'task-paused':
            self._paused = event['paused']
            self._set_label(self.pause_button, 'Resume' if self._paused else 'Pause')
            self.pause_button.setEnabled(self.process is not None and not self._stopping and not self._closing)
            if self._paused:
                self._clear_overlay()
            self.status_label.setText('Paused' if self._paused else 'Running')
        elif isinstance(event, dict) and event.get('event') == 'finished':
            self._clear_overlay()
            result = event.get('result', {})
            self._exit_requested = bool(result.get('exit_requested')
                                        or result.get('business_result', {}).get('exit_requested'))
        elif isinstance(event, dict) and event.get('event') == 'session-task-finished':
            self._foreground_requested = False
            self.refresh_account_context()
            self.status_label.setText(f'Finished {event["task_id"]}')
        elif isinstance(event, dict) and event.get('event') == 'session-task-failed':
            if self._foreground_requested:
                self._foreground_requested = False
                self.refresh_account_context()
            self.status_label.setText(f'{event.get("task_id")}: {event["error"]}')
        elif isinstance(event, dict) and event.get('event') == 'user-tasks-reloaded':
            self.refresh_tasks()
            self.status_label.setText('User tasks applied: ' + str(event['applied_revision']))
        elif isinstance(event, dict) and event.get('event') == 'character-code-reloaded':
            self.status_label.setText('Character code applied: ' + str(event['applied_character_revision']))
        elif isinstance(event, dict) and event.get('event') in ('character-code-reload-failed', 'user-tasks-reload-failed'):
            self._error(RuntimeError(event['error']))
        return False

    def _stop_worker(self):
        try:
            self.controller.stop()
        except Exception as error:
            self._events.put(("error", error))
        finally:
            self._events.put(("stop-done", None))

    def _drain_events(self):
        while True:
            try:
                kind, value = self._events.get_nowait()
            except queue.Empty:
                break
            if self.managed_update_bindings.handle(kind, value):
                continue
            if kind == 'overview-started':
                self._overview_starting = False
            elif kind == 'account-context':
                self._configuration_querying = False
                self.package_select.setEnabled(self.process is None and not self._closing and not self._managing)
                self._apply_account_context(value)
            elif kind == 'context-error':
                self._configuration_querying = False
                self._restore_pending = False
                self.package_select.setEnabled(self.process is None and not self._closing and not self._managing)
                self.account_context_label.setText(str(value))
                self._error(value)
            elif kind == 'overview-line':
                self.output.appendPlainText(value)
            elif kind in ('overview-exit', 'overview-error'):
                self._overview_starting = False
                manifest = self._manifest()
                self.overview_button.setEnabled(manifest is not None and manifest.overview
                                                and not self._closing and not self._updating and not self._installing)
                if kind == 'overview-error':
                    self._error(value)
                elif value != 0:
                    self._error(RuntimeError(f'Read-only overview exited with code {value}'))
            elif kind == "line":
                if not self._pause_status(value):
                    self.output.appendPlainText(value)
            elif kind == 'management-line':
                if not self._management_live_request(value):
                    self.output.appendPlainText(value)
                    self._management_update_status(value)
            elif kind == 'management-started':
                self._management_process = value
                self.status_label.setText('Management running')
                manifest = self._manifest()
                self.start_button.setEnabled(manifest.supports_session and self.task_list.currentRow() >= 0
                                             and not self._closing and not self._stopping)
                threading.Thread(target=self._read_management_output,
                                 args=(value,), daemon=True).start()
            elif kind in {'management-exit', 'management-error'}:
                self._managing = False
                self._management_process = None
                self._live_routes = {key: value for key, value in self._live_routes.items() if value != 'management'}
                self.package_select.setEnabled(self.process is None and not self._closing and not self._updating)
                if self.process is None:
                    self._select_package(self.package_select.currentIndex())
                else:
                    self.refresh_tasks()
                    self.manage_button.setEnabled(self._manifest().management and not self._closing and not self._updating)
                self.install_button.setEnabled(self.process is None and not self._closing and not self._updating)
                if kind == 'management-error':
                    if self._updating:
                        self._update_management_error = value
                        self._apply_pending_update()
                    self._error(value)
                else:
                    self.status_label.setText(f'Management exited with code {value}')
                    if value == 0 and not self._updating and not self._closing and self._manifest().configuration:
                        if not self.refresh_account_context():
                            self._set_label(self.account_context_label, '账号配置已更新；当前操作结束后请刷新账号上下文。')
                    if self._updating:
                        if value == 0:
                            self._apply_pending_update()
                        else:
                            self._update_management_error = RuntimeError('Management did not exit successfully before update')
                            self._apply_pending_update()
            elif kind == "started":
                manifest, task_id, process = value
                self._starting = False
                self.process = process
                self.package_select.setEnabled(False)
                self.device_edit.setEnabled(False)
                self.device_editor.setEnabled(False)
                self.manage_button.setEnabled(manifest.management and manifest.supports_session
                                              and not self._managing and not self._closing)
                self.status_label.setText(f"Running {manifest.id}/{task_id or 'session'} ({manifest.execution})")
                self.stop_button.setEnabled(not self._closing)
                self._paused = False
                self._set_label(self.pause_button, 'Pause')
                self.pause_button.setEnabled(manifest.execution == 'native' and not self._closing)
                self.install_button.setEnabled(False)
                self.update_button.setEnabled(False)
                self.start_button.setEnabled(manifest.supports_session and not self._closing)
                self._set_label(self.start_button, 'Run / enable task' if manifest.supports_session else 'Start')
                self.disable_button.setEnabled(manifest.supports_session
                                               and task_id is not None and manifest.task(task_id, self.data_dir / manifest.id).kind == 'service'
                                               and not self._closing)
                self._reader = threading.Thread(target=self._read_output, args=(process,), daemon=True)
                self._reader.start()
                if manifest.supports_session:
                    request_id = str(uuid.uuid4())
                    try:
                        self.controller.request_live('get-schema', request_id)
                    except Exception as error:
                        self._error(error)
                    else:
                        self._live_routes[request_id] = 'hotkeys'
            elif kind == "start-error":
                self._starting = False
                self._foreground_requested = False
                self.package_select.setEnabled(not self._closing and not self._managing)
                self.device_edit.setEnabled(not self._closing)
                self.device_editor.setEnabled(not self._closing)
                self._error(value)
                self.start_button.setEnabled(not self._closing and self.task_list.currentRow() >= 0)
                self.install_button.setEnabled(not self._closing)
                self.manage_button.setEnabled(self._manifest().management and not self._closing)
                self.update_button.setEnabled(not self._closing and self._is_installed(self._manifest()))
            elif kind == "exit":
                self._clear_overlay()
                for request_id, destination in list(self._live_routes.items()):
                    self._live_response({'event': 'live-response', 'request_id': request_id,
                        'ok': False, 'error': {'type': 'RuntimeError', 'message': '执行会话已退出，请启动会话后再试。'}})
                self.status_label.setText(f"Worker exited with code {value}")
                self.process = None
                self._foreground_requested = False
                self.package_select.setEnabled(not self._managing and not self._closing and not self._updating)
                self.device_edit.setEnabled(self._manifest().execution == 'native' and not self._closing)
                self.device_editor.setEnabled(self._manifest().execution == 'native' and not self._closing)
                self._set_label(self.start_button, 'Start')
                self.disable_button.setEnabled(False)
                self.start_button.setEnabled(not self._closing and not self._starting and not self._updating
                                             and self.task_list.currentRow() >= 0)
                self.stop_button.setEnabled(False)
                self.pause_button.setEnabled(False)
                self.install_button.setEnabled(not self._closing and not self._installing and not self._updating)
                self.manage_button.setEnabled(self._manifest().management and not self._closing and not self._updating)
                self.update_button.setEnabled(not self._closing and not self._updating
                                              and self._is_installed(self._manifest()))
                if value == 0 and self._exit_requested:
                    self._force_close = True
                    self.close()
            elif kind == "install-done":
                self._installing = False
                self._reload_packages(value)
                self.status_label.setText(f"Installed {value}")
                self.install_button.setEnabled(not self._closing)
            elif kind == "install-error":
                self._installing = False
                self._error(value)
                self.start_button.setEnabled(not self._closing and self.task_list.currentRow() >= 0)
                self.install_button.setEnabled(not self._closing)
                self.manage_button.setEnabled(self._manifest().management and not self._closing)
                self.update_button.setEnabled(not self._closing and self._is_installed(self._manifest()))
            elif kind == 'update-prepared':
                if self._updating:
                    self._pending_update = value
                    self.status_label.setText('Gamepack verified; waiting for owned processes to exit')
                    self._apply_pending_update()
            elif kind == 'update-done':
                self._finish_update(package_id=value)
            elif kind == 'update-error':
                self._finish_update(error=value)
            elif kind == "stop-done":
                self._stopping = False
                self.stop_button.setEnabled(self.process is not None and not self._closing)
            elif kind == "cleanup-done":
                self._cleanup_done = True
                self.close()
            elif kind == "cleanup-error":
                self._closing = False
                self.start_button.setEnabled(self.process is None and self.task_list.currentRow() >= 0)
                self.stop_button.setEnabled(self.process is not None)
                self.install_button.setEnabled(self.process is None and not self._installing)
                self._error(value)
            elif kind == "error":
                self._error(value)
        manifest = self._manifest()
        self.reload_tasks_button.setEnabled(manifest is not None and manifest.task_catalog is not None
                                            and self.process is not None and self.controller.session
                                            and not self._stopping and not self._closing and not self._updating)
        self.reload_characters_button.setEnabled(self.process is not None and self.controller.session
                                                and not self._stopping and not self._closing and not self._updating)
        live = self.process is not None and self.controller.session and not self._stopping and not self._closing
        manifest = self._manifest()
        editable = manifest is not None and manifest.execution == 'native' and self.process is None
        editable = editable and not self._starting and not self._closing and not self._updating
        self.device_editor.setEnabled(editable)
        self.device_edit.setEnabled(editable)
        self.change_root_button.setEnabled(not self._starting and not self._closing and not self._managing
            and not self._configuration_querying
            and not self._overview_starting and not self._installing and not self._updating and self.process is None
            and (self.overview_controller.process is None or self.overview_controller.process.poll() is not None))
        self.session_button.setEnabled(editable and manifest.supports_session and not self._installing
                                      and not self._configuration_querying)
        context_busy = self._configuration_querying or any(value == 'account-context' for value in self._live_routes.values())
        context_editable = (self._account_context is not None and self._account_context['available']
                            and not self._account_context['readonly'] and not self._foreground_requested
                            and not self._starting and not self._stopping and not self._closing and not context_busy)
        self.sequence_select.setEnabled(context_editable)
        self.account_select.setEnabled(context_editable)
        self.context_refresh_button.setEnabled(manifest is not None and manifest.configuration
            and not self._starting and not self._stopping and not self._closing and not self._foreground_requested
            and not self._updating and not context_busy)
        self.screenshot_button.setEnabled(live)
        self.ocr_button.setEnabled(live)
        if not self._stopping and not self._closing and self._hotkey.poll():
            if self.process is not None and self.pause_button.isEnabled():
                self.toggle_pause()
            elif self.process is None and editable and manifest.supports_session and not self._managing:
                self.start_session()
    def closeEvent(self, event):
        self._clear_overlay()
        if not self._closing:
            self._save_launcher_context()
        if not self._force_close and not self._closing and self.close_to_tray.isChecked():
            if QSystemTrayIcon.isSystemTrayAvailable():
                self.tray.show()
                self.hide()
                event.ignore()
                return
        if self._cleanup_done:
            self.tray.hide()
            event.accept()
            return
        event.ignore()
        if self._closing:
            return
        self._closing = True
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.disable_button.setEnabled(False)
        self.manage_button.setEnabled(False)
        self.status_label.setText("Closing worker…")
        self.overview_button.setEnabled(False)
        threading.Thread(target=self._close_worker, daemon=True).start()

    def _close_worker(self):
        try:
            if self._start_thread is not None:
                self._start_thread.join()
            if self._install_thread is not None:
                self._install_thread.join()
            if self._update_thread is not None:
                self._update_thread.join()
            self.managed_update_bindings.wait()
            if self._management_thread is not None:
                self._management_thread.join()
            self.management_controller.close()
            if self._overview_thread is not None:
                self._overview_thread.join()
            self.overview_controller.close()
            self.overview_controller.assert_idle()
            if self._configuration_thread is not None:
                self._configuration_thread.join()
            self.configuration_controller.close()
            self.controller.close()
        except Exception as error:
            self._events.put(("cleanup-error", error))
        else:
            self._events.put(("cleanup-done", None))


def run_gui(packages_dir: Path | str, data_dir: Path | str, *, managed_root=None,
            login_argv=None, installation_root=None) -> int:
    from gameframe.managed_install import managed_entry
    with managed_entry(managed_root) as managed:
        app = QApplication.instance() or QApplication([])
        window = GameFrameWindow(packages_dir, data_dir, managed_root=managed,
                                 login_argv=login_argv, installation_root=installation_root)
        window.show()
        return app.exec()
