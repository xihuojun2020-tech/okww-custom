# SPDX-License-Identifier: AGPL-3.0-or-later
"""Character source editor; all validation and publication belong to the child."""

from difflib import SequenceMatcher

from PySide6.QtCore import Signal, QUrl
from PySide6.QtGui import QDesktopServices, QTextCursor, QTextFormat
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel,
    QListWidget, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QTextEdit, QVBoxLayout, QWidget)

from src.runtime.native_language import translate


BASE_CHAR_URL = 'https://raw.githubusercontent.com/ok-oldking/ok-wuthering-waves/refs/heads/master/src/char/BaseChar.py'
CONTRIBUTE_URL = 'https://github.com/ok-oldking/ok-wuthering-waves/edit/master/src/char/{class_name}.py'


class NativeCharacterCodeTab(QWidget):
    busy_changed = Signal(bool)

    def __init__(self, configuration, parent=None):
        super().__init__(parent)
        self.configuration = configuration
        self.busy = False
        self._request = self._callback = None
        self._rows = []
        self._class_name = self._revision = None
        self._record = None
        self._editor_mode = 0
        self._saved = ''
        layout = QVBoxLayout(self)
        description = QLabel(translate('选择内置或自定义角色代码。保存前独立验证；运行中的共享会话需要明确重载，单次任务重启后应用。'), self)
        description.setWordWrap(True)
        layout.addWidget(description)
        split = QSplitter(self)
        self.characters = QListWidget(self)
        split.addWidget(self.characters)
        editor = QWidget(self)
        edit_layout = QVBoxLayout(editor)
        row = QHBoxLayout()
        self.identity = QLabel(translate('请选择角色'), self)
        self.mode = QComboBox(self)
        self.mode.addItems((translate('内置代码'), translate('自定义代码')))
        row.addWidget(self.identity, 1)
        row.addWidget(self.mode)
        edit_layout.addLayout(row)
        self.code = QPlainTextEdit(self)
        self.code.setReadOnly(True)
        edit_layout.addWidget(self.code, 1)
        split.addWidget(editor)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        row = QHBoxLayout()
        self.refresh_button = QPushButton(translate('刷新角色'), self)
        self.save_button = QPushButton(translate('验证并保存'), self)
        self.reset_button = QPushButton(translate('恢复内置代码'), self)
        self.ask_ai_button = QPushButton(translate('复制修改提示'), self)
        self.help_button = QPushButton(translate('修改说明'), self)
        self.contribute_button = QPushButton(translate('贡献代码'), self)
        for button in (self.refresh_button, self.save_button, self.reset_button,
                       self.ask_ai_button, self.help_button, self.contribute_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.status = QLabel(translate('等待配置进程加载。'), self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self._controls = (self.characters, self.mode, self.code, self.refresh_button,
            self.save_button, self.reset_button, self.ask_ai_button, self.help_button,
            self.contribute_button)
        self.configuration.schema_changed.connect(self._ready)
        self.configuration.response_received.connect(self._response)
        self.configuration.lifecycle_failed.connect(self._failed_lifecycle)
        self.characters.currentRowChanged.connect(self._select)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.code.textChanged.connect(self._highlight)
        self.refresh_button.clicked.connect(self.refresh)
        self.save_button.clicked.connect(self.save)
        self.reset_button.clicked.connect(self.reset)
        self.ask_ai_button.clicked.connect(self.copy_prompt)
        self.help_button.clicked.connect(self.show_help)
        self.contribute_button.clicked.connect(self.contribute)

    def _discard(self):
        return self.code.toPlainText() == self._saved or QMessageBox.question(
            self, translate('未保存的代码'), translate('放弃当前未保存的角色修改？'),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def _ready(self, _schema):
        if not self.busy:
            self.refresh()

    def _submit(self, command, callback, **values):
        if self.busy:
            return
        request = self.configuration.request(command, **values)
        if request is None:
            self.status.setText(translate('配置进程不可用，未提交角色修改。'))
            return
        self._request, self._callback = request, callback
        self.busy = True
        for control in self._controls:
            control.setEnabled(False)
        self.status.setText(translate('正在验证并保存角色…') if command == 'character-save' else translate('正在处理角色…'))
        self.busy_changed.emit(True)
        return request

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
                if result.get('saved_revision'):
                    self._loaded(result)
                    self.status.setText(translate('角色代码已保存，配置进程未应用；运行进程保留旧代码。') +
                                        response['error']['message'])
                else:
                    self._restore_mode()
                    self.status.setText(translate('操作失败，草稿保留：') + response['error']['message'])
        finally:
            self.busy_changed.emit(self.busy)

    def _failed_lifecycle(self, message):
        self._finish()
        self._restore_mode()
        self.status.setText(translate('配置进程不可用，草稿保留：') + message)
        self.busy_changed.emit(False)

    def refresh(self):
        self._submit('character-list', self._listed)

    def _listed(self, result):
        self._rows = result['characters']
        self.characters.blockSignals(True)
        self.characters.clear()
        for item in self._rows:
            self.characters.addItem(f"{item['display_name']} · {item['class_name']}")
        selected = next((i for i, item in enumerate(self._rows)
                         if item['class_name'] == self._class_name), -1)
        self.characters.setCurrentRow(selected)
        self.characters.blockSignals(False)
        applied = self.configuration.applied_character_revision
        self.status.setText(translate('已读取{count}个角色；已保存版本 {saved}，'
                                     '配置进程版本 {applied}。运行进程需单独重载。').format(
                                         count=len(self._rows), saved=result['saved_revision'][:12],
                                         applied=applied[:12] if applied else translate('未知')))

    def _select(self, row):
        if row < 0 or self.busy:
            return
        if not self._discard():
            old = next((i for i, item in enumerate(self._rows)
                        if item['class_name'] == self._class_name), -1)
            self.characters.blockSignals(True)
            self.characters.setCurrentRow(old)
            self.characters.blockSignals(False)
            return
        self._submit('character-read', self._loaded, class_name=self._rows[row]['class_name'])

    def _loaded(self, result):
        self._record = result
        self._class_name, self._revision = result['class_name'], result['saved_revision']
        self.identity.setText(f"{result['display_name']} · {self._class_name}")
        self._editor_mode = 1 if result['use_custom'] else 0
        self._restore_mode()
        self.code.setReadOnly(not result['use_custom'])
        self.code.setPlainText(result['custom_code'] if result['use_custom'] else result['builtin_code'])
        self._saved = self.code.toPlainText()
        self._highlight()
        self.status.setText(translate('角色源码已读取。自定义代码须保留当前类名。'))

    def _restore_mode(self):
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(self._editor_mode)
        self.mode.blockSignals(False)

    def _mode_changed(self, index):
        if self._record is None or self.busy:
            return
        if not self._discard():
            self._restore_mode()
            return
        if index == 1 and not self._record['has_custom']:
            self._editor_mode = 1
            self.code.setReadOnly(False)
            self.code.setPlainText(self._record['builtin_code'])
            self._saved = self.code.toPlainText()
            self.status.setText(translate('正在编辑自定义草稿，保存后才启用。'))
            return
        if self._submit('character-set-mode', self._committed, class_name=self._class_name,
            use_custom=bool(index), expected_revision=self._revision) is None:
            self._restore_mode()

    def save(self):
        if self._class_name is None or self.mode.currentIndex() != 1:
            self.status.setText(translate('请先选择角色并切换到自定义代码。'))
            return
        self._submit('character-save', self._committed, class_name=self._class_name,
            code=self.code.toPlainText(), expected_revision=self._revision)

    def reset(self):
        if self._class_name is None:
            return
        if QMessageBox.question(self, translate('恢复内置角色'), translate('删除此角色自定义代码并恢复内置模式？'),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self._submit('character-reset', self._committed, class_name=self._class_name,
                     expected_revision=self._revision)

    def _committed(self, result):
        self._loaded(result)
        self.status.setText(translate('角色修改已保存，配置进程已应用。实际运行进程需明确重载或重启任务。'))

    def _highlight(self):
        if self._record is None:
            return
        changed = []
        color = self.palette().highlight().color()
        color.setAlpha(36)
        current = self.code.toPlainText().splitlines()
        for tag, _, _, start, end in SequenceMatcher(
                None, self._record['builtin_code'].splitlines(), current).get_opcodes():
            if tag == 'equal':
                continue
            for index in range(start, end):
                selection = QTextEdit.ExtraSelection()
                selection.cursor = QTextCursor(self.code.document().findBlockByLineNumber(index))
                selection.format.setBackground(color)
                selection.format.setProperty(QTextFormat.FullWidthSelection, True)
                changed.append(selection)
        self.code.setExtraSelections(changed)

    def copy_prompt(self):
        if self._class_name is None:
            return
        QApplication.clipboard().setText(
            f'```python\n{self.code.toPlainText()}\n```\n\n我想实现：\n\n'
            f'请修改上述完整角色代码，保留类名 {self._class_name} 和必要导入。'
            '只返回完整 Python 文件，不返回补丁或解释。\n'
            f'BaseChar 参考：{BASE_CHAR_URL}\n')
        self.status.setText(translate('修改提示已复制，可粘贴到聊天工具并补充需求。'))

    def show_help(self):
        QMessageBox.information(self, translate('修改角色代码'),
            translate('选择角色和自定义模式，编辑或粘贴完整 Python 文件。改动行会高亮。\n'
            '保存前独立验证代码；失败会保留草稿。运行中的共享会话需在启动器明确重载，'
            '单次任务需重新启动。恢复内置会删除此角色的自定义源码。'))

    def contribute(self):
        if self._class_name is not None:
            QDesktopServices.openUrl(QUrl(CONTRIBUTE_URL.format(class_name=self._class_name)))
