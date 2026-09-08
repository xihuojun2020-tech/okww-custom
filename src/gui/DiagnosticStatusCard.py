"""Local diagnostic controls; SMB is never accessed by the Qt thread."""
import json
from collections import Counter

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton

from src.gui.BackgroundOperation import BackgroundOperation
from src.runtime.diagnostic_export import atomic_json, sanitize_text
from src.runtime.diagnostic_session import default_root, FileLease
from src.runtime.diagnostic_lifecycle import wake_uploader
from src.runtime.diagnostic_uploader import DEFAULT_TARGET
from src.runtime.diagnostic_policy import settings, save_credentials


def diagnostic_error_message(error):
    text = sanitize_text(error)
    if "No module named 'win32timezone'" in text:
        return '旧诊断上传组件不完整；请重启程序以自动重建并重试'
    if 'NAS authentication failed' in text or '用户名或密码不正确' in text:
        return 'NAS 用户名或密码不正确；请重新填写密码并保存设置'
    return text


def diagnostic_status_text(root):
    counts, upload_error, last_success = Counter(), '', 0
    for ready in root.glob('*/batches/*/_READY'):
        state_path = root / 'states' / (ready.parents[2].name + '--' + ready.parent.name + '.json')
        try:
            state = json.loads(state_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            state = {'status': 'pending'}
        counts[state.get('status', 'pending')] += 1
        upload_error = state.get('last_error') or upload_error
        last_success = max(last_success, state.get('uploaded_at', 0))
    from datetime import datetime
    success = datetime.fromtimestamp(last_success).isoformat(timespec='seconds') if last_success else '无'
    scheduler_path = root / 'scheduler.json'
    scheduler = json.loads(scheduler_path.read_text(encoding='utf-8')).get('status') if scheduler_path.exists() else '待安装'
    collector_error = root / 'collector-error.json'
    warning = ''
    if collector_error.exists():
        try:
            value = json.loads(collector_error.read_text(encoding='utf-8'))
            warning = value.get('error', '')
        except (OSError, ValueError):
            warning = '采集警告状态无法读取'
    return (f'批次：{dict(counts)}\n最后成功：{success}\n退出后补传任务：{scheduler}'
            f'\n最近上传错误：{diagnostic_error_message(upload_error) or "无"}'
            f'\n最近采集警告：{diagnostic_error_message(warning) or "无"}')


class DiagnosticStatusCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = default_root()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('日志与截图自动上传 NAS（仅从本版本开始）'))
        layout.addWidget(QLabel('每周清理超过 7 天且已上传的日志；截图和待补传资料保留。'))
        self.target = QLineEdit(DEFAULT_TARGET)
        self.target.setPlaceholderText('NAS 诊断目录，不填写密码')
        layout.addWidget(self.target)
        self.username = QLineEdit('ai-upload')
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText('首次连接时填写密码，仅保存到本机 Windows 凭据管理器')
        layout.addWidget(self.username)
        layout.addWidget(self.password)
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
            self.target.setText(settings(self.root).get('target', DEFAULT_TARGET))
        except (OSError, ValueError):
            pass
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(5000)
        self.refresh()

    def refresh(self):
        root = self.root
        def read():
            return diagnostic_status_text(root)
        self.operation.start(read, self.status.setText, lambda e: self.status.setText(sanitize_text(e)))

    def save(self):
        root, target = self.root, self.target.text().strip()
        username, secret = self.username.text().strip(), self.password.text()
        if not target:
            self.status.setText('请填写 NAS 目录')
            return
        def write():
            if secret:
                save_credentials(target, username, secret)
            value = settings(root)
            value['target'] = target
            atomic_json(root / 'settings.json', value)
            if secret:
                with FileLease(root / '.uploader.lock'):
                    for path in (root / 'states').glob('*.json'):
                        state = json.loads(path.read_text(encoding='utf-8'))
                        if state.get('status') == 'retrying':
                            state['next_retry'] = 0
                            atomic_json(path, state)
            wake_uploader(root)
        self.operation.start(write, lambda _: (self.password.clear(), self.refresh()),
                             lambda e: (self.password.clear(), self.status.setText(sanitize_text(e))))

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
