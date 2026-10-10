# SPDX-License-Identifier: AGPL-3.0-or-later
"""Production task forms backed by a separate, device-free configuration owner."""

import json
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, Signal, Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget)


class OrderedValues(QWidget):
    changed = Signal(list)

    def __init__(self, values, options, *, allow_duplication=False, parent=None):
        super().__init__(parent)
        self.allow_duplication = allow_duplication
        self.items = QListWidget(self)
        self.items.setMaximumHeight(150)
        for value in values:
            self._add(value)
        self.choice = QComboBox(self)
        self.choice.setEditable(not options)
        for value in options:
            self.choice.addItem(str(value), value)
        add = QPushButton('添加', self)
        remove = QPushButton('删除', self)
        up = QPushButton('上移', self)
        down = QPushButton('下移', self)
        apply = QPushButton('保存列表', self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.items)
        row = QHBoxLayout()
        for widget in (self.choice, add, remove, up, down, apply):
            row.addWidget(widget)
        layout.addLayout(row)
        add.clicked.connect(self._append)
        remove.clicked.connect(self._remove)
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        apply.clicked.connect(lambda: self.changed.emit(self.values()))

    def _add(self, value):
        item = QListWidgetItem(str(value))
        item.setData(Qt.UserRole, value)
        self.items.addItem(item)

    def values(self):
        return [self.items.item(index).data(Qt.UserRole) for index in range(self.items.count())]

    def _append(self):
        value = self.choice.currentData() if self.choice.count() else self.choice.currentText()
        if self.allow_duplication or value not in self.values():
            self._add(value)

    def _remove(self):
        row = self.items.currentRow()
        if row >= 0:
            self.items.takeItem(row)

    def _move(self, offset):
        row = self.items.currentRow()
        target = row + offset
        if row >= 0 and 0 <= target < self.items.count():
            item = self.items.takeItem(row)
            self.items.insertItem(target, item)
            self.items.setCurrentRow(target)


class NativeConfigurationTab(QWidget):
    management_requested = Signal()
    schema_changed = Signal(dict)
    lifecycle_failed = Signal(str)
    response_received = Signal(dict)
    busy_changed = Signal(bool)
    live_completed = Signal(object, object)

    def __init__(self, data_dir, version, manifest_path, parent=None, *, live_bridge=None):
        super().__init__(parent)
        self.live_bridge = live_bridge
        self.live_completed.connect(self._live_finished, Qt.QueuedConnection)
        from gameframe.packages import PackageManifest
        manifest = PackageManifest.read(Path(manifest_path).parent)
        self.schema = None
        self.applied_revision = None
        self.applied_character_revision = None
        self._entries = []
        self._request_id = 0
        self._pending = set()
        self._buffer = b''
        self._closing = False
        self._startup_failure = None
        self.selection = QListWidget(self)
        self.selection.setMinimumWidth(200)
        self.form = QFormLayout()
        content = QWidget(self)
        content.setLayout(self.form)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(content)
        split = QSplitter(self)
        split.addWidget(self.selection)
        split.addWidget(self.scroll)
        split.setStretchFactor(1, 1)
        self.status = QLabel('正在加载任务配置…', self)
        self.status.setWordWrap(True)
        self.refresh_button = QPushButton('刷新配置', self)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(self.status, 1)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        layout.addWidget(split, 1)
        self.selection.currentRowChanged.connect(self._render)
        self.refresh_button.clicked.connect(self.refresh)
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(Path(__file__).resolve().parents[2]))
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(self._read_errors)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self.process.started.connect(lambda: self.request('get-schema'))
        self._arguments = ['-u', '-m', 'gameframe.package_process',
            '--package', str(manifest.root), '--expected-version', manifest.version,
            '--module', 'src.runtime.native_configuration', '--',
            '--data-dir', str(Path(data_dir).resolve()), '--version', version,
            '--manifest', str(Path(manifest_path).resolve())]
        # FailedToStart can be emitted synchronously. Let the window connect
        # lifecycle signals before the first launch.
        QTimer.singleShot(0, self._start)

    def _start(self):
        if not self._closing:
            self.process.start(sys.executable, self._arguments)

    def refresh(self):
        if self.process.state() == QProcess.NotRunning:
            self.reload()
        elif self.process.state() == QProcess.Running:
            self.request('get-schema')

    def reload(self):
        """Rebind genuine account options after an explicit account transaction."""
        self.shutdown()
        self._closing = False
        self._startup_failure = None
        self.schema = None
        self._buffer = b''
        self._pending.clear()
        self.selection.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self._start()

    def _fail(self, message):
        self.status.setText('配置操作失败：' + str(message))

    def _fail_lifecycle(self, message):
        self._fail(message)
        self._pending.intersection_update(value for value in self._pending if isinstance(value, str))
        if not self._closing and self._startup_failure is None:
            self._startup_failure = str(message)
            self.lifecycle_failed.emit(self._startup_failure)
        self.busy_changed.emit(bool(self._pending))

    def _process_error(self, error):
        message = self.process.errorString()
        if error in (QProcess.FailedToStart, QProcess.Crashed):
            self._fail_lifecycle(message)
        else:
            self._fail(message)

    def _read_errors(self):
        message = bytes(self.process.readAllStandardError()).decode('utf-8', errors='replace').strip()
        if message:
            self._fail(message)

    def _finished(self, code, _status):
        if not self._closing and self._startup_failure is None:
            self._fail_lifecycle(f'配置进程退出（{code}）')
        self.selection.setEnabled(False)
        self.scroll.setEnabled(False)
        self.refresh_button.setEnabled(not self._closing)

    def request(self, command, **values):
        self._request_id += 1
        message = {'command': command, 'request_id': self._request_id, **values}
        if self._closing or self.process.state() != QProcess.Running:
            self._fail('配置进程未运行')
            return
        self._pending.add(self._request_id)
        self.scroll.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.status.setText('正在保存…' if command != 'get-schema' else '正在加载…')
        self.process.write((json.dumps(message, ensure_ascii=False) + '\n').encode('utf-8'))
        self.busy_changed.emit(True)
        return self._request_id

    def _read(self):
        self._buffer += bytes(self.process.readAllStandardOutput())
        while b'\n' in self._buffer:
            line, self._buffer = self._buffer.split(b'\n', 1)
            try:
                value = json.loads(line)
            except ValueError:
                continue  # Business logs share stdout; protocol replies are JSON events.
            if value.get('event') == 'configuration-failed':
                self._fail_lifecycle(value['error']['message'])
                continue
            if value.get('event') != 'configuration-response':
                continue
            self.applied_revision = value.get('applied_revision', self.applied_revision)
            self.applied_character_revision = value.get('applied_character_revision', self.applied_character_revision)
            self._pending.discard(value.get('request_id'))
            self.scroll.setEnabled(not self._pending)
            self.refresh_button.setEnabled(not self._pending)
            if not value['ok']:
                if self.schema is not None:
                    self.set_schema(self.schema)
                if value.get('command') == 'get-schema' and self.schema is None:
                    self._fail_lifecycle(value['error']['message'])
                else:
                    self._fail(value['error']['message'])
                self.response_received.emit(value)
                self.busy_changed.emit(bool(self._pending))
                continue
            self.set_schema(value['schema'])
            if value.get('command') in ('get-schema', 'user-task-save', 'user-task-delete',
                                        'user-bundle-import', 'user-bundle-delete'):
                self.schema_changed.emit(self.schema)
            self.status.setText('配置已保存。' if value.get('command') != 'get-schema' else '配置已加载。')
            self.response_received.emit(value)
            self.busy_changed.emit(bool(self._pending))

    def set_schema(self, schema):
        selected = self._entries[self.selection.currentRow()][:2] if self.selection.currentRow() >= 0 else None
        self.schema = schema
        self._entries = [('task', entry['id'], entry) for entry in schema['tasks'] if entry['visible']]
        self._entries += [('global', entry['id'], entry) for entry in schema['globals']]
        self.selection.blockSignals(True)
        self.selection.clear()
        for scope, _identifier, entry in self._entries:
            self.selection.addItem(('全局：' if scope == 'global' else '') + entry['name'])
        row = next((i for i, entry in enumerate(self._entries) if entry[:2] == selected), 0)
        self.selection.setCurrentRow(row if self._entries else -1)
        self.selection.blockSignals(False)
        self._render(self.selection.currentRow())

    def _set(self, scope, identifier, key, value):
        self.request('set-config', scope=scope, id=identifier, values={key: value})

    def _live_action(self, task_id, action_id):
        if self._closing:
            self._fail('配置窗口正在关闭')
            return
        future = self.live_bridge.request('invoke-action', task_id=task_id, action_id=action_id)
        self._pending.add(future.request_id)
        self.scroll.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.status.setText('正在执行设备动作…')
        self.busy_changed.emit(True)
        future.add_done_callback(lambda result: self.live_completed.emit(result.request_id, result))

    def _live_finished(self, request_id, future):
        self._pending.discard(request_id)
        self.scroll.setEnabled(not self._pending and not self._closing)
        self.refresh_button.setEnabled(not self._pending and not self._closing)
        try:
            future.result()
        except Exception as error:
            self._fail(str(error))
        else:
            self.status.setText('设备动作已执行。')
        self.busy_changed.emit(bool(self._pending))

    def _render(self, row):
        while self.form.rowCount():
            self.form.removeRow(0)
        if row < 0:
            return
        scope, identifier, entry = self._entries[row]
        description = QLabel(entry['description'], self)
        description.setWordWrap(True)
        self.form.addRow(description)
        current = entry['current_config']
        types = entry['config_type']
        hidden, shown = set(), set()
        for parent, details in types.items():
            for rule in details.get('sub_configs', []):
                hidden.update(rule['keys'])
                value = current.get(parent)
                if rule['value'] == value or (isinstance(value, list) and rule['value'] in value):
                    shown.update(rule['keys'])
        for key, default in entry['default_config'].items():
            details = types.get(key, {})
            if key in hidden - shown or details.get('hidden', False):
                continue
            value = current.get(key, default)
            widget = self._widget(scope, identifier, key, value, default, details,
                                  entry['readonly_values'])
            label = QLabel(key, self)
            label.setWordWrap(True)
            help_text = entry['config_description'].get(key, '')
            label.setToolTip(help_text)
            widget.setToolTip(help_text)
            label.setBuddy(widget)
            self.form.addRow(label, widget)

    def _widget(self, scope, identifier, key, value, default, details, readonly):
        kind = details.get('type')
        submitted = [value]
        def save(result):
            if result != submitted[0]:
                submitted[0] = result
                self._set(scope, identifier, key, result)
        if kind == 'label':
            return QLabel(str(readonly.get(key, value)), self)
        if kind == 'global':
            button = QPushButton('编辑全局配置', self)
            button.clicked.connect(lambda: self._select_global(key))
            return button
        if kind == 'button' or 'buttons' in details or 'action_id' in details:
            body = QWidget(self)
            layout = QHBoxLayout(body)
            layout.setContentsMargins(0, 0, 0, 0)
            for definition in details.get('buttons', [details]):
                button = QPushButton(definition.get('text', definition.get('name', key)), body)
                requires_device = definition.get('requires_device', False)
                if requires_device and self.live_bridge is None:
                    button.setEnabled(False)
                    button.setToolTip('此动作需要执行器连接游戏设备。')
                if definition['target'] == 'management':
                    button.clicked.connect(self.management_requested)
                else:
                    button.clicked.connect(lambda _=False, action=definition['action_id'],
                                                  live=requires_device:
                        self._live_action(identifier, action) if live else
                        self.request('invoke-action', task_id=identifier, action_id=action))
                layout.addWidget(button)
            return body
        options = details.get('options', [])
        if options and not isinstance(default, list):
            widget = QComboBox(self)
            for option in options:
                actual, text = option if kind == 'integer_drop_down' else (option, str(option))
                widget.addItem(str(text), actual)
            index = widget.findData(value)
            if index < 0:
                widget.addItem(str(value), value)
                index = widget.count() - 1
            widget.setCurrentIndex(index)
            widget.currentIndexChanged.connect(lambda index: save(widget.itemData(index)))
            return widget
        if isinstance(default, bool):
            widget = QCheckBox(self)
            widget.setChecked(value)
            widget.toggled.connect(save)
            return widget
        if isinstance(default, int):
            widget = QSpinBox(self)
            widget.setRange(details.get('min', -2147483648), details.get('max', 2147483647))
            widget.setValue(value)
            widget.editingFinished.connect(lambda: save(widget.value()))
            return widget
        if isinstance(default, float):
            widget = QDoubleSpinBox(self)
            widget.setDecimals(6)
            widget.setRange(details.get('min', -1e12), details.get('max', 1e12))
            widget.setValue(value)
            widget.editingFinished.connect(lambda: save(widget.value()))
            return widget
        if isinstance(default, list) and kind not in ('text_edit',):
            if kind in ('multi_selection', 'dropdown_multi_selection') or (options and kind is None):
                body = QWidget(self)
                layout = QVBoxLayout(body)
                layout.setContentsMargins(0, 0, 0, 0)
                for option in options:
                    checkbox = QCheckBox(str(option), body)
                    checkbox.setProperty('value', option)
                    checkbox.setChecked(option in value)
                    layout.addWidget(checkbox)
                button = QPushButton('保存选择', body)
                button.clicked.connect(lambda: save([item.property('value')
                    for item in body.findChildren(QCheckBox) if item.isChecked()]))
                layout.addWidget(button)
                return body
            widget = OrderedValues(value, details.get('options_available', options),
                                   allow_duplication=details.get('allow_duplication', False), parent=self)
            widget.changed.connect(save)
            return widget
        if kind == 'text_edit' or isinstance(default, (dict, list)) or '\n' in str(value):
            body = QWidget(self)
            layout = QVBoxLayout(body)
            layout.setContentsMargins(0, 0, 0, 0)
            widget = QPlainTextEdit(self)
            widget.setMaximumHeight(140)
            widget.setPlainText(json.dumps(value, ensure_ascii=False, indent=2)
                                if isinstance(default, (dict, list)) else value)
            button = QPushButton('保存', body)
            def apply():
                try:
                    result = json.loads(widget.toPlainText()) if isinstance(default, (dict, list)) else widget.toPlainText()
                except ValueError as error:
                    self._fail(error)
                    return
                save(result)
            button.clicked.connect(apply)
            layout.addWidget(widget)
            layout.addWidget(button)
            return body
        widget = QLineEdit(str(value), self)
        widget.editingFinished.connect(lambda: save(widget.text()))
        if kind != 'file_selector':
            return widget
        body = QWidget(self)
        layout = QHBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        browse = QPushButton('选择文件', body)
        def select():
            filename, _ = QFileDialog.getOpenFileName(self, key, widget.text(), details.get('filter', '所有文件 (*)'))
            if filename:
                save(filename)
        browse.clicked.connect(select)
        layout.addWidget(widget)
        layout.addWidget(browse)
        return body

    def _select_global(self, identifier):
        row = next(i for i, entry in enumerate(self._entries) if entry[:2] == ('global', identifier))
        self.selection.setCurrentRow(row)

    def shutdown(self):
        self._closing = True
        if self.process.state() == QProcess.NotRunning:
            return
        self.process.write(b'{"command":"stop"}\n')
        if not self.process.waitForFinished(5000):
            raise RuntimeError('配置进程未确认停止，暂不能关闭管理窗口或替换游戏包')
