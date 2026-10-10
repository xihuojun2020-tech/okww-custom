# SPDX-License-Identifier: AGPL-3.0-or-later
"""Edit trusted native scripts through the device-free configuration owner."""

import json

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget)


TEMPLATE = '''from src.runtime.native_task import NativeBaseTask


class UserTask(NativeBaseTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "我的任务"
        self.description = "编辑此原生任务的规则"
        self.support_schedule_task = True

    def run(self):
        self.log_info("用户任务已执行")
        return {"completed": True}
'''


class NativeUserTaskTab(QWidget):
    busy_changed = Signal(bool)

    def __init__(self, configuration, parent=None):
        super().__init__(parent)
        self.configuration = configuration
        self.busy = False
        self._request = None
        self._callback = None
        self._rows = []
        self._source_id = None
        self._catalog_revision = None
        self._list_catalog_revision = None
        self._saved = None
        layout = QVBoxLayout(self)
        label = QLabel('用户任务使用 NativeBaseTask / NativeTriggerTask。保存前独立验证代码；此处编辑的是可信可执行代码。保存只更新配置进程，实际运行进程需明确重载或重新启动。', self)
        label.setWordWrap(True)
        layout.addWidget(label)
        split = QSplitter(self)
        self.sources = QListWidget(self)
        split.addWidget(self.sources)
        editor = QWidget(self)
        edit_layout = QVBoxLayout(editor)
        form = QFormLayout()
        self.identity = QLabel('新任务', self)
        self.class_name = QLineEdit('UserTask', self)
        self.capabilities = QLineEdit('["frames", "keyboard", "mouse"]', self)
        form.addRow('稳定ID', self.identity)
        form.addRow('导出类名', self.class_name)
        form.addRow('所需能力 JSON', self.capabilities)
        edit_layout.addLayout(form)
        self.code = QPlainTextEdit(self)
        self.code.setPlainText(TEMPLATE)
        edit_layout.addWidget(self.code, 1)
        split.addWidget(editor)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        row = QHBoxLayout()
        self.refresh_button = QPushButton('刷新任务', self)
        self.new_button = QPushButton('新建任务', self)
        self.save_button = QPushButton('验证并保存', self)
        self.delete_button = QPushButton('删除任务', self)
        for button in (self.refresh_button, self.new_button, self.save_button, self.delete_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.status = QLabel('等待配置进程加载。', self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self._controls = (self.sources, self.class_name, self.capabilities, self.code,
            self.refresh_button, self.new_button, self.save_button, self.delete_button)
        self._remember()
        self.configuration.schema_changed.connect(self._ready)
        self.configuration.response_received.connect(self._response)
        self.configuration.lifecycle_failed.connect(self._failed_lifecycle)
        self.sources.currentRowChanged.connect(self._select)
        self.refresh_button.clicked.connect(self.refresh)
        self.new_button.clicked.connect(self.new_task)
        self.save_button.clicked.connect(self.save)
        self.delete_button.clicked.connect(self.delete)

    def _values(self):
        return self.class_name.text(), self.capabilities.text(), self.code.toPlainText()

    def _remember(self):
        self._saved = self._values()

    def _discard(self):
        return self._values() == self._saved or QMessageBox.question(self, '未保存的代码',
            '放弃当前未保存的修改？', QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def _ready(self, _schema):
        if not self.busy:
            self.refresh()

    def _submit(self, command, callback, **values):
        if self.busy:
            return
        request = self.configuration.request(command, **values)
        if request is None:
            self.status.setText('配置进程不可用，未提交代码。')
            return
        self._request, self._callback = request, callback
        self.busy = True
        for control in self._controls:
            control.setEnabled(False)
        self.status.setText('正在验证代码并处理任务…' if command == 'user-task-save' else '正在读取任务…')
        self.busy_changed.emit(True)

    def _finish(self):
        self._request = self._callback = None
        self.busy = False
        for control in self._controls:
            control.setEnabled(True)

    def _response(self, response):
        if self._request is None or response.get('request_id') != self._request:
            return
        callback = self._callback
        self._finish()
        try:
            if response['ok']:
                callback(response.get('result', {}))
            else:
                result = response.get('result', {})
                if result.get('catalog_revision'):
                    self._catalog_revision = result['catalog_revision']
                    if result.get('source_id'):
                        self._loaded(result)
                    self.status.setText('任务注册已更新到磁盘，配置进程未应用；运行中保留旧注册表。' + response['error']['message'])
                else:
                    self.status.setText('操作失败：' + response['error']['message'])
        finally:
            self.busy_changed.emit(self.busy)

    def _failed_lifecycle(self, message):
        self._finish()
        self.status.setText('配置进程不可用：' + message)
        self.busy_changed.emit(False)

    def refresh(self):
        self._submit('user-task-list', self._listed)

    def _listed(self, result):
        self._list_catalog_revision = result['catalog_revision']
        if self._source_id is None:
            self._catalog_revision = self._list_catalog_revision
        self._rows = result['tasks']
        self.sources.blockSignals(True)
        self.sources.clear()
        for item in self._rows:
            self.sources.addItem(f"{item['title']} · {item['class_name']}")
        index = next((i for i, item in enumerate(self._rows) if item['source_id'] == self._source_id), -1)
        self.sources.setCurrentRow(index)
        self.sources.blockSignals(False)
        applied = self.configuration.applied_revision or '未知'
        self.status.setText(f'已读取{len(self._rows)}个用户任务；已保存版本 {self._list_catalog_revision[:12]}，'
                            f'配置进程版本 {applied[:12]}；运行进程需单独重载。')

    def _select(self, row):
        if row < 0 or self.busy:
            return
        if not self._discard():
            previous = next((i for i, item in enumerate(self._rows) if item['source_id'] == self._source_id), -1)
            self.sources.blockSignals(True)
            self.sources.setCurrentRow(previous)
            self.sources.blockSignals(False)
            return
        self._submit('user-task-read', self._loaded, source_id=self._rows[row]['source_id'])

    def _loaded(self, result):
        self._source_id = result['source_id']
        self._catalog_revision = result['catalog_revision']
        self.identity.setText(result['id'])
        self.class_name.setText(result['class_name'])
        self.capabilities.setText(json.dumps(result['required_capabilities'], ensure_ascii=False))
        self.code.setPlainText(result['code'])
        self._remember()
        self.status.setText('源码已读取。修改类名仍保留这个稳定任务ID与配置。')

    def new_task(self):
        if self.busy or not self._discard():
            return
        self.sources.setCurrentRow(-1)
        self._source_id = None
        self._catalog_revision = self._list_catalog_revision
        self.identity.setText('新任务：保存时生成稳定ID')
        self.class_name.setText('UserTask')
        self.capabilities.setText('["frames", "keyboard", "mouse"]')
        self.code.setPlainText(TEMPLATE)
        self._remember()

    def save(self):
        try:
            capabilities = json.loads(self.capabilities.text())
        except ValueError as error:
            self.status.setText('能力JSON无效：' + str(error))
            return
        self._submit('user-task-save', self._saved_task, code=self.code.toPlainText(),
            class_name=self.class_name.text(), required_capabilities=capabilities,
            source_id=self._source_id, expected_revision=self._catalog_revision)

    def _saved_task(self, result):
        self._loaded(result)
        self.status.setText('验证与保存完成；配置进程已应用。实际worker需明确重载或重新启动。')
        self.refresh()

    def delete(self):
        if self._source_id is None:
            self.status.setText('请先选择已保存任务。')
            return
        if QMessageBox.question(self, '删除用户任务',
            f'删除任务 {self.identity.text()} 的注册？配置和历史源码保留。',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self._submit('user-task-delete', self._deleted, source_id=self._source_id,
            expected_revision=self._catalog_revision)

    def _deleted(self, _result):
        self._source_id = None
        self._remember()
        self.new_task()
        self.refresh()
