"""Local diagnostic controls; SMB is never accessed by the Qt thread."""
import json
import time
from collections import Counter

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton

from src.gui.BackgroundOperation import BackgroundOperation
from src.gui.FlatSettingRow import FlatSettingRow
from src.gui.SectionPanel import SectionPanel, reveal_widget
from src.runtime.diagnostic_export import atomic_json, sanitize_text
from src.runtime.diagnostic_session import default_root, FileLease
from src.runtime.diagnostic_lifecycle import wake_uploader
from src.runtime.diagnostic_uploader import DEFAULT_TARGET, bounded_probe
from src.runtime.diagnostic_policy import settings, save_credentials


def diagnostic_error_message(error):
    text = sanitize_text(error)
    reasons = {'frame_unavailable': '等待游戏画面', 'stale_frame': '画面未更新，缺失截图会如实标记',
               'low_disk_space': '磁盘剩余不足 2 GiB，已暂停新增诊断截图',
               'pending_size_limit': '待传资料超过 2 GiB，已暂停新增诊断截图'}
    if text in reasons:
        return reasons[text]
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
    scheduler = json.loads(scheduler_path.read_text(encoding='utf-8')) if scheduler_path.exists() else {}
    if scheduler.get('status') == 'installed':
        scheduler_text = '已由系统验证' if scheduler.get('system_verified') else '已缓存（未验证系统任务）'
    else:
        scheduler_text = scheduler.get('status', '待安装')
    collector_error = root / 'collector-error.json'
    warning = ''
    if collector_error.exists():
        try:
            value = json.loads(collector_error.read_text(encoding='utf-8'))
            warning = value.get('error', '')
        except (OSError, ValueError):
            warning = '采集警告状态无法读取'
    evidence = {}
    for path in root.glob('*/evidence-status.json'):
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if value.get('updated_at', 0) > evidence.get('updated_at', 0):
                evidence = value
        except (OSError, ValueError):
            continue
    capture = ('正在采集错误后画面' if evidence.get('active_incident') else
               f'已缓存 {evidence.get("ring_frames", 0)} 张报错前画面') if evidence else '等待程序采集'
    if evidence.get('warning'):
        capture += '；' + diagnostic_error_message(evidence['warning'])
    if evidence and time.time() - evidence.get('updated_at', 0) > 10:
        capture = '采集已停止或状态未刷新；' + capture
    return (f'批次：{dict(counts)}\n最后成功：{success}\n退出后补传任务：{scheduler_text}'
            f'\n最近上传错误：{diagnostic_error_message(upload_error) or "无"}'
            f'\n最近采集警告：{diagnostic_error_message(warning) or "无"}\n错误截图：{capture}')


class DiagnosticStatusCard(SectionPanel):
    def __init__(self, parent=None):
        super().__init__('日志与诊断', parent=parent, collapsible=True)
        self.root = default_root()
        self.set_summary('正在读取本地状态…')
        layout = self.content_layout
        description = QLabel('日志和截图自动上传到局域网共享目录。错误前 10 秒、后 5 秒每秒采集一张游戏画面；无画面时标记缺失。每周清理超过 7 天且已上传的日志，截图和待补传资料保留。')
        description.setWordWrap(True)
        description.setProperty('role', 'description')
        layout.addWidget(description)
        self.settings_section = self
        self.target = QLineEdit(DEFAULT_TARGET)
        self.target.setPlaceholderText(r'\\接收电脑\共享目录，不填写密码')
        self.settings_section.add_row('上传目录', self.target)
        self.username = QLineEdit('ai-upload')
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText('首次连接时填写密码，仅保存到本机 Windows 凭据管理器')
        self.settings_section.add_row('用户名', self.username)
        self.settings_section.add_row('密码', self.password, '仅保存到本机 Windows 凭据管理器；留空不修改。')
        self.status = QLabel('正在读取本地状态')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        save, retry, folder = (QPushButton(text) for text in ('保存设置', '重试上传', '打开目录'))
        probe, capture = QPushButton('测试共享连接'), QPushButton('测试错误截图')
        row.addWidget(save)
        for button in (retry, folder):
            self.add_action(button)
        checks = QHBoxLayout()
        checks.addWidget(probe)
        checks.addWidget(capture)
        checks.addStretch(1)
        layout.addLayout(row)
        layout.addLayout(checks)
        self.operation = BackgroundOperation(self, (save, retry, probe, capture))
        save.clicked.connect(self.save)
        retry.clicked.connect(self.retry)
        probe.clicked.connect(self.test_connection)
        capture.clicked.connect(self.test_capture)
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
        self.operation.start(read, self._show_status, lambda e: self._show_status(sanitize_text(e)))

    def _show_status(self, text):
        self.status.setText(text)
        lines = text.splitlines()
        errors = [line for line in lines if line.startswith(('最近上传错误：', '最近采集警告：')) and not line.endswith('：无')]
        self.set_summary('存在诊断异常，展开查看' if errors else next((line for line in lines if line.startswith('最后成功：')), text))

    def save(self):
        root, target = self.root, self.target.text().strip()
        username, secret = self.username.text().strip(), self.password.text()
        if not target:
            self._show_status('请填写 NAS 目录')
            reveal_widget(self.target)
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
                             lambda e: (self.password.clear(), self._show_status(sanitize_text(e))))

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
        self.operation.start(reset, lambda _: self.refresh(), lambda e: self._show_status(sanitize_text(e)))

    def test_connection(self):
        target = self.target.text().strip()
        self._show_status('正在检查共享目录；最长等待 30 秒，请先保存设置和凭据。')
        self.operation.start(lambda: bounded_probe(target),
                             lambda _: self._show_status('共享连接通过：写入、读取、重命名、删除均成功。'),
                             lambda e: self._show_status('共享连接失败：' + diagnostic_error_message(e)))

    def test_capture(self):
        from src.runtime import diagnostic_lifecycle
        session = diagnostic_lifecycle._session
        if session is None or session.closed_session:
            self._show_status('诊断会话尚未启动，请重启程序后再测试。')
            return
        data = {'message': '用户主动测试错误截图', 'source': 'manual_test', 'level': 'ERROR'}
        session.record_event('manual_evidence_test', data)
        session.record_error(data)
        self._show_status('已触发截图测试：请保持游戏画面可见 5 秒。启动不足 10 秒时，报错前画面可能不完整。')
