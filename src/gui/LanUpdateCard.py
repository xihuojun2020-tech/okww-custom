from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from qfluentwidgets import MessageBox

from src.account_config_editor import sanitize_error
from src.gui.BackgroundOperation import BackgroundOperation
from src.update.lan_service import LanUpdateService


class LanUpdateCard(QWidget):
    apply_requested = Signal(Path)

    def __init__(self, config_path: Path, current_version: str, executor, parent=None):
        super().__init__(parent)
        self.config_path = Path(config_path)
        self.current_version = current_version
        self.executor = executor
        self.release = None
        self.service = None
        self.status = QLabel(f"当前版本：{current_version}", self)
        self.status.setWordWrap(True)
        self.action = QPushButton("检查局域网更新", self)
        self.action.clicked.connect(self._action)
        row = QHBoxLayout()
        row.addWidget(self.status, 1)
        row.addWidget(self.action)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        self.operation = BackgroundOperation(self, (self.action,))

    def _action(self):
        if self.release is None:
            self._check()
        else:
            self._download()

    def _check(self):
        def work():
            service = LanUpdateService(self.config_path)
            return service, service.check(self.current_version)

        def complete(value):
            self.service, availability = value
            self.release = availability.release
            self.status.setText(availability.message)
            self.action.setText("下载并安装" if self.release else "重新检查")

        self.operation.start(work, complete, self._failed, timeout_ms=8000)

    def _download(self):
        if getattr(self.executor, "current_task", None) is not None:
            self.status.setText("自动化任务运行中，停止任务后才能安装更新")
            return
        root = Path(__file__).resolve().parents[2]
        release, service = self.release, self.service

        def work():
            archive = service.download(release, root)
            return service.create_apply_request(
                release, archive, root, [sys.executable, str(root / "main.py")])

        def complete(request):
            dialog = MessageBox("安装局域网更新",
                                f"已验证版本 {release.version}。程序将退出、安装并自动重启，是否继续？", self.window())
            dialog.yesButton.setText("安装并重启")
            dialog.cancelButton.setText("取消")
            if dialog.exec():
                self.apply_requested.emit(request)
            else:
                self.status.setText("安装已取消，当前版本未改变")

        self.operation.start(work, complete, self._failed)

    def _failed(self, error):
        self.status.setText("局域网更新失败：" + sanitize_error(error))


__all__ = ["LanUpdateCard"]
