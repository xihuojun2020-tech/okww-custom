"""Output-only relocation coordinated with the management window's owner stop."""
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from src.account_config_editor import sanitize_error
from src.gui.BackgroundOperation import BackgroundOperation


class NativeStorageTab(QWidget):
    def __init__(self, service, maintain, parent=None):
        super().__init__(parent)
        self.service, self.maintain = service, maintain
        self._preview = None
        layout = QVBoxLayout(self)
        description = QLabel('此页迁移输出资料，并保留原文件。账号、配置、用户脚本和数据根不迁移。'
                             '迁移前停止本窗口配置进程；其他所有者仍占用数据时会明确失败。', self)
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QFormLayout()
        self.path_labels = {}
        for title, key in (('数据根（配置权威）', 'data'), ('日志', 'logs'), ('截图', 'screenshots'),
                           ('诊断', 'diagnostics'), ('配置备份', 'backups'), ('完成证据', 'CompletionEvidence'),
                           ('运行控制状态（不迁移）', 'runtime')):
            row = QWidget(self)
            fields = QHBoxLayout(row); fields.setContentsMargins(0, 0, 0, 0)
            label = QLabel(row); label.setWordWrap(True)
            button = QPushButton('打开目录', row)
            button.clicked.connect(lambda _=False, key=key: self._open(key))
            fields.addWidget(label, 1); fields.addWidget(button)
            form.addRow(title, row); self.path_labels[key] = label
        layout.addLayout(form)
        destination = QHBoxLayout()
        self.destination = QLineEdit(self)
        self.destination.setAccessibleName('输出资料目标目录')
        self.select_button = QPushButton('选择输出目录', self)
        self.select_button.clicked.connect(self._select)
        destination.addWidget(self.destination, 1); destination.addWidget(self.select_button)
        layout.addLayout(destination)
        actions = QHBoxLayout()
        self.preview_button = QPushButton('预览输出迁移', self)
        self.migrate_button = QPushButton('确认迁移输出', self)
        self.migrate_button.setEnabled(False)
        self.refresh_button = QPushButton('刷新目录', self)
        for button in (self.preview_button, self.migrate_button, self.refresh_button): actions.addWidget(button)
        layout.addLayout(actions)
        self.status = QLabel('选择数据根所在本机磁盘上的空输出目录，先预览再迁移。', self)
        self.status.setWordWrap(True); layout.addWidget(self.status); layout.addStretch(1)
        self.operation = BackgroundOperation(self, (self.destination, self.select_button,
            self.preview_button, self.migrate_button, self.refresh_button))
        self.destination.textChanged.connect(self._invalidate)
        self.preview_button.clicked.connect(self.preview)
        self.migrate_button.clicked.connect(self.migrate)
        self.refresh_button.clicked.connect(self.refresh)
        self.refresh()

    def _open(self, key):
        try:
            path = self.service.paths()[key]
            if not path.is_dir():
                raise OSError('目录尚未创建：' + str(path))
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                raise OSError('无法打开目录：' + str(path))
        except Exception as error:
            self._failed(error)

    def refresh(self):
        try:
            paths = self.service.paths()
            for key, label in self.path_labels.items(): label.setText(str(paths[key]))
        except Exception as error:
            self._failed(error)

    def _select(self):
        path = QFileDialog.getExistingDirectory(self, '选择空输出目录', str(self.service.root.parent))
        if path: self.destination.setText(path)

    def _invalidate(self):
        self._preview = None
        self.migrate_button.setEnabled(False)

    def preview(self):
        destination = self.destination.text().strip()
        if not destination:
            self.status.setText('请先选择输出目录。')
            return
        self._preview = None
        self.operation.start(lambda: self.service.preview(Path(destination)), self._previewed, self._failed)

    def _previewed(self, preview):
        self._preview = preview
        self.migrate_button.setEnabled(True)
        self.status.setText(f"输出迁移预览：{preview['files']}个文件，{preview['bytes'] / 1024**2:.2f} MiB。"
                            '保留原文件；账号、配置和用户脚本留在数据根。')

    def migrate(self):
        preview = self._preview
        if preview is None: return
        if QMessageBox.question(self, '确认迁移输出资料',
                f"将输出复制并校验到：{preview['destination']}\n保留原文件，更新输出目录配置，随后重新加载配置进程。") != QMessageBox.Yes:
            return
        self.migrate_button.setEnabled(False)
        self.status.setText('正在停止配置所有者并迁移输出…')
        self.maintain(lambda: self.service.migrate(preview), self._migrated, self._failed, False)

    def _migrated(self, result):
        self._invalidate(); self.refresh()
        self.status.setText('输出目录已提交，原文件保留；数据根未迁移。配置进程将重新加载目录配置。')

    def _failed(self, error):
        committed = getattr(error, 'committed', False)
        self.status.setText(('输出目录已提交，收尾失败，请重新加载管理窗口：' if committed else
                             '操作失败，输出迁移未提交：') + sanitize_error(error))
        self._invalidate()
