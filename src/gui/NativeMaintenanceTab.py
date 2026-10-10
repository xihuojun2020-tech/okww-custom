# SPDX-License-Identifier: AGPL-3.0-or-later
"""Existing verified configuration backups, coordinated with active owners."""

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from src.account_config_editor import sanitize_error
from src.gui.BackgroundOperation import BackgroundOperation


class NativeMaintenanceTab(QWidget):
    def __init__(self, service, coordinate, parent=None):
        super().__init__(parent)
        self.service, self.coordinate = service, coordinate
        layout = QVBoxLayout(self)
        description = QLabel('备份包含完整配置。恢复前停止本窗口配置进程；其他执行器或总览仍占用数据时，操作会明确失败。', self)
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QFormLayout()
        for title, key in (('数据目录', 'data'), ('配置目录', 'configs'), ('备份目录', 'backups')):
            path = service.paths()[key]
            row = QWidget(self)
            fields = QHBoxLayout(row)
            fields.setContentsMargins(0, 0, 0, 0)
            label = QLabel(str(path), row)
            label.setWordWrap(True)
            button = QPushButton('打开目录', row)
            button.clicked.connect(lambda _=False, path=path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
            fields.addWidget(label, 1)
            fields.addWidget(button)
            form.addRow(title, row)
        layout.addLayout(form)
        snapshot = QHBoxLayout()
        self.snapshot = QLineEdit(self)
        self.snapshot.setAccessibleName('待验证或恢复的备份目录')
        select = QPushButton('选择备份目录', self)
        select.clicked.connect(self._select)
        snapshot.addWidget(self.snapshot, 1)
        snapshot.addWidget(select)
        layout.addLayout(snapshot)
        actions = QHBoxLayout()
        self.create_button = QPushButton('创建完整备份', self)
        self.verify_button = QPushButton('验证备份', self)
        self.restore_button = QPushButton('预览并恢复', self)
        self.sequence_button = QPushButton('检查遗漏序列', self)
        self.cleanup_button = QPushButton('清理过期备份', self)
        controls = (self.create_button, self.verify_button, self.restore_button,
                    self.sequence_button, self.cleanup_button, select, self.snapshot)
        for button in controls[:5]:
            actions.addWidget(button)
        layout.addLayout(actions)
        self.status = QLabel('等待操作。', self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch(1)
        self.operation = BackgroundOperation(self, controls)
        self.create_button.clicked.connect(lambda: self.coordinate(
            service.create_snapshot, self._created, self._failed, False))
        self.verify_button.clicked.connect(self._verify)
        self.restore_button.clicked.connect(self._preview_restore)
        self.sequence_button.clicked.connect(self._preview_sequences)
        self.cleanup_button.clicked.connect(lambda: self.operation.start(
            service.cleanup, self._cleaned, self._failed))

    def _select(self):
        path = QFileDialog.getExistingDirectory(self, '选择含manifest.json的完整备份目录',
                                               str(self.service.paths()['backups']))
        if path:
            self.snapshot.setText(path)

    def _selected(self):
        text = self.snapshot.text().strip()
        if not text:
            self.status.setText('请先选择备份目录。')
            return None
        return Path(text)

    def _failed(self, error):
        self.status.setText('操作失败：' + sanitize_error(error))

    def _created(self, snapshot):
        self.snapshot.setText(str(snapshot.path))
        self.status.setText('完整备份已创建并验证：' + str(snapshot.path))

    def _verify(self):
        path = self._selected()
        if path is not None:
            self.operation.start(lambda: self.service.verify_snapshot(path), self._verified, self._failed)

    def _verified(self, result):
        self.status.setText(f'备份验证通过：{len(result.files)}个文件。' if result.ok else
                            '备份验证失败：' + (result.error or
                            f'缺失{len(result.missing)}，额外{len(result.extra)}，内容差异{len(result.hash_differences)}。'))

    def _preview_restore(self):
        path = self._selected()
        if path is not None:
            self.operation.start(lambda: self.service.preview_restore(path),
                                 lambda preview: self._confirm_restore(path, preview), self._failed)

    def _confirm_restore(self, path, preview):
        if not preview.ok:
            self.status.setText('此备份不能恢复：' + preview.error)
            return
        text = (f'将替换当前完整配置：{preview.account_count}个账号、{preview.sequence_count}个序列、'
                f'{len(preview.files)}个文件。\n恢复前保留当前配置的事务备份。\n备份：{path}')
        if not preview.master_config_present:
            text += '\n此备份没有可信账号主配置；恢复后可能需要重新锚定。'
        if QMessageBox.question(self, '确认恢复完整配置', text) == QMessageBox.Yes:
            self.coordinate(lambda: self.service.restore(path, preview, confirmed=True),
                            lambda _: self.status.setText('配置恢复已提交。'), self._failed, True)

    def _preview_sequences(self):
        self.operation.start(self.service.preview_sequence_repair, self._confirm_sequences, self._failed)

    def _confirm_sequences(self, preview):
        if not preview['eligible']:
            self.status.setText('；'.join(preview.get('errors', [])) or preview.get('reason') or '没有可恢复的遗漏序列。')
            return
        sequences = '\n'.join(f'{name}：{len(members)}个账号' for name, members in preview['sequences'].items())
        if QMessageBox.question(self, '确认恢复遗漏序列',
                f'从{preview["source"]}恢复以下序列，提交前保存事务备份：\n{sequences}') == QMessageBox.Yes:
            self.coordinate(lambda: self.service.repair_sequences(preview, confirmed=True),
                            lambda _: self.status.setText('遗漏序列已恢复。'), self._failed, True)

    def _cleaned(self, result):
        self.status.setText('备份清理已完成。' if result else
                            '清理未完成，请查看日志中的备份维护警告。')
