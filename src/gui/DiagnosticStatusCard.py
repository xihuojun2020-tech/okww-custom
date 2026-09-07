"""Local diagnostic controls; SMB is never accessed by the Qt thread."""
import json
from collections import Counter

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox

from src.gui.BackgroundOperation import BackgroundOperation
from src.runtime.diagnostic_export import atomic_json, sanitize_text
from src.runtime.diagnostic_session import default_root, FileLease
from src.runtime.diagnostic_lifecycle import wake_uploader
from src.runtime.diagnostic_uploader import DEFAULT_TARGET


class DiagnosticStatusCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = default_root()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('诊断日志与 NAS 上传（图片需单独审核）'))
        self.enabled = QCheckBox('启用 NAS 上传')
        self.target = QLineEdit(DEFAULT_TARGET)
        self.target.setPlaceholderText('NAS 诊断目录，不填写密码')
        layout.addWidget(self.enabled)
        layout.addWidget(self.target)
        self.status = QLabel('正在读取本地状态')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        save, retry, folder = (QPushButton(text) for text in ('保存设置', '重试网络失败批次', '打开本地诊断'))
        for button in (save, retry, folder):
            row.addWidget(button)
        layout.addLayout(row)
        self.operation = BackgroundOperation(self, (save, retry))
        save.clicked.connect(self.save)
        retry.clicked.connect(self.retry)
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root))))
        try:
            settings = json.loads((self.root / 'settings.json').read_text(encoding='utf-8'))
            self.enabled.setChecked(bool(settings.get('enabled')))
            self.target.setText(settings.get('target', DEFAULT_TARGET))
        except (OSError, ValueError):
            pass
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(5000)
        self.refresh()

    def refresh(self):
        root = self.root
        def read():
            counts, last_error, last_success = Counter(), '', 0
            for ready in root.glob('*/batches/*/_READY'):
                state_path = root / 'states' / (ready.parents[2].name + '--' + ready.parent.name + '.json')
                try:
                    state = json.loads(state_path.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    state = {'status': 'pending'}
                counts[state.get('status', 'pending')] += 1
                last_error = state.get('last_error') or last_error
                last_success = max(last_success, state.get('uploaded_at', 0))
            from datetime import datetime
            success = datetime.fromtimestamp(last_success).isoformat(timespec='seconds') if last_success else '无'
            return f'批次：{dict(counts)}\n最后成功：{success}\n最近阻塞：{sanitize_text(last_error) or "无"}'
        self.operation.start(read, self.status.setText, lambda e: self.status.setText(sanitize_text(e)))

    def save(self):
        root, target, enabled = self.root, self.target.text().strip(), self.enabled.isChecked()
        if enabled and not target:
            self.status.setText('请填写 NAS 目录')
            return
        def write():
            atomic_json(root / 'settings.json', {'enabled': enabled, 'target': target})
            wake_uploader(root)
        self.operation.start(write, lambda _: self.refresh(), lambda e: self.status.setText(sanitize_text(e)))

    def retry(self):
        root = self.root
        def reset():
            with FileLease(root / '.uploader.lock'):
                for path in (root / 'states').glob('*.json'):
                    state = json.loads(path.read_text(encoding='utf-8'))
                    if state.get('status') == 'retrying':
                        state['next_retry'] = 0
                        atomic_json(path, state)
            wake_uploader(root)
        self.operation.start(reset, lambda _: self.refresh(), lambda e: self.status.setText(sanitize_text(e)))
