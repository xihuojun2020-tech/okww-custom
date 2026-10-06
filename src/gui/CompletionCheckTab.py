"""Read-only account evidence dashboard and explicit manual capture/recycle UI."""
from functools import partial
import json
import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QPixmap, QImage, QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QListWidget, QListWidgetItem, QLineEdit, QScrollArea, QDialog, QDialogButtonBox,
    QMessageBox, QCheckBox, QPlainTextEdit, QSizePolicy, QPushButton, QApplication, QMenu)
from qfluentwidgets import FluentIcon, PushButton, PrimaryPushButton

from src.account_display import account_display_label, account_sort_key, parse_account_label
from src.account_repository import get_default_repository
from src.evidence.model import (PROJECTS, CURRENT_PROJECTS, GROUPS, project_group,
    STATUSES, SOURCES, ASSETS, period_for, period_label, summarize, now_iso)
from src.evidence.export import export_screenshots, export_state
from src.evidence.service import EvidenceService, get_evidence_service, request_capture
from src.gui.BackgroundOperation import BackgroundOperation
from src.gui.ChoiceControls import QtComboBox
from src.gui.CodexTheme import COLORS


def picture(data, width=280, height=140):
    pixmap = QPixmap()
    if data:
        pixmap.loadFromData(data)
    return pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def copy_image(data):
    """Decode before touching the clipboard; always copy original pixels."""
    image = QImage.fromData(data or b'')
    if image.isNull():
        raise ValueError('原图缺失或无法读取，未更改剪贴板')
    QApplication.clipboard().setImage(image)


def image_copy_menu(widget, callback):
    widget.setContextMenuPolicy(Qt.CustomContextMenu)
    def show(position):
        menu = QMenu(widget)
        menu.addAction('复制图片', callback)
        menu.exec(widget.mapToGlobal(position))
    widget.customContextMenuRequested.connect(show)


class EvidenceCaptureDialog(QDialog):
    def __init__(self, capture, profiles, selected, project=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('保存当前画面为完成证据')
        self.resize(660, 600)
        self.capture = capture
        layout = QVBoxLayout(self)
        frame = capture['frame']
        image = QImage(frame.data, frame.shape[1], frame.shape[0], frame.strides[0], QImage.Format_BGR888)
        preview = QLabel(self)
        preview.setAlignment(Qt.AlignCenter)
        preview.setPixmap(QPixmap.fromImage(image).scaled(600, 280, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(preview)
        self.account = QtComboBox(self)
        self.account.addItem('请选择账号', None)
        for profile_id, label in profiles.items():
            self.account.addItem(label, profile_id)
        binding = capture.get('profile_id')
        self.account.setCurrentIndex(0)
        layout.addWidget(QLabel('截图所属账号（不是游戏自动登录操作）'))
        layout.addWidget(self.account)
        if binding:
            hint = QLabel('采集时运行绑定：' + profiles.get(binding, binding), self)
            hint.setWordWrap(True)
            layout.addWidget(hint)
        self.project = QtComboBox(self)
        for key in CURRENT_PROJECTS:
            self.project.addItem(PROJECTS[key][0], key)
        if project in PROJECTS:
            self.project.setCurrentIndex(self.project.findData(project))
        layout.addWidget(QLabel('证据项目'))
        layout.addWidget(self.project)
        self.status = QtComboBox(self)
        for key in ('unknown', 'completed', 'partial', 'incomplete', 'not_applicable'):
            self.status.addItem(STATUSES[key], key)
        layout.addWidget(QLabel('人工核验状态'))
        layout.addWidget(self.status)
        self.note = QPlainTextEdit(self)
        self.note.setPlaceholderText('备注或进度，例如：已完成所选聚落中的 3 个；不修改自动任务断点')
        self.note.setMaximumHeight(75)
        layout.addWidget(self.note)
        self.confirm = QCheckBox('我确认画面属于上述账号；完成状态仅用于证据看板', self)
        layout.addWidget(self.confirm)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        self.buttons.button(QDialogButtonBox.Save).setText('保存证据')
        self.buttons.button(QDialogButtonBox.Cancel).setText('取消')
        self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
        self.confirm.toggled.connect(lambda checked: self.buttons.button(QDialogButtonBox.Save).setEnabled(
            checked and self.account.currentData() is not None))
        self.account.currentIndexChanged.connect(lambda _: self.buttons.button(QDialogButtonBox.Save).setEnabled(
            self.confirm.isChecked() and self.account.currentData() is not None))
        self.buttons.accepted.connect(self.confirm_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def confirm_accept(self):
        if not self.confirm.isChecked() or not self.account.currentData():
            return
        binding = self.capture.get('profile_id')
        if binding and binding != self.account.currentData():
            if QMessageBox.question(self, '确认截图归属',
                    '所选账号与采集时的运行绑定不同，确认将此截图保存到所选账号？',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        self.accept()

    def metadata(self):
        if not self.confirm.isChecked() or self.account.currentData() is None:
            raise ValueError('请明确确认截图所属账号')
        status = self.status.currentData()
        return dict(profile_id=self.account.currentData(), project_id=self.project.currentData(),
                    completion_status=status, source='manual_capture' if status == 'unknown' else 'manual_confirmation',
                    captured_at=self.capture['captured_at'], identity_source='user_confirmed',
                    runtime_profile_id=self.capture.get('profile_id'),
                    note=self.note.toPlainText().strip())


class EvidenceDetailDialog(QDialog):
    def __init__(self, record, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(PROJECTS[record['project_id']][0] + ' · 证据详情')
        self.resize(880, 680)
        self.pixmap = QPixmap()
        self._original_data = data
        if data:
            self.pixmap.loadFromData(data)
        layout = QVBoxLayout(self)
        self.image = QLabel('原图缺失或本条只有完成记录', self)
        self.image.setAlignment(Qt.AlignCenter)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.image)
        layout.addWidget(self.scroll, 1)
        labels = {'initial': '初始次数', 'claimed': '本次确认领奖', 'remaining': '剩余次数',
                  'points': '识别积分', 'target': '达标积分'}
        progress = '，'.join(f'{labels[key]}：{value}' for key, value in record.get('progress', {}).items() if key in labels)
        text = QLabel(f"{STATUSES[record['completion_status']]} · {SOURCES[record['source']]}\n"
                      f"记录时间：{record['captured_at']}\n{period_label(record['period_id'], record['project_id'])}\n{progress}\n"
                      f"{record.get('reason', '')}\n{record.get('note', '')}\n{record.get('nas_status', '')}", self)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(text)
        self.copy_notice = QLabel('', self)
        layout.addWidget(self.copy_notice)
        controls = QHBoxLayout()
        for title, callback in [('复制图片', self.copy_original), ('适应窗口', self.fit), ('原始大小', self.original), ('关闭', self.accept)]:
            button = PushButton(title, self)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        image_copy_menu(self.image, self.copy_original)
        QTimer.singleShot(0, self.fit)

    def copy_original(self):
        try:
            copy_image(self._original_data)
            self.copy_notice.setText('图片已复制，可在微信中粘贴')
        except ValueError as error:
            self.copy_notice.setText(str(error))

    def fit(self):
        if not self.pixmap.isNull():
            self.image.setMinimumSize(0, 0)
            self.image.setPixmap(self.pixmap.scaled(self.scroll.viewport().size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def original(self):
        if not self.pixmap.isNull():
            self.image.setPixmap(self.pixmap)
            self.image.setMinimumSize(self.pixmap.size())


class CompletionCheckTab(QWidget):
    name = '完成检查'
    icon = FluentIcon.PHOTO
    export_progress = Signal(int, int)

    def __init__(self, executor, repository=None, account_provider=None):
        super().__init__()
        self.setObjectName('CompletionCheckTab')
        self.executor = executor
        self.service = EvidenceService(repository) if repository else get_evidence_service()
        self.repository = self.service.repository
        executor.completion_evidence_service = self.service
        self.account_provider = account_provider or get_default_repository
        self._profiles, self._sequences, self._rows = {}, {}, []
        self._nicknames = {}
        self._export_cancel = threading.Event()
        cancel_on_destroy = self._export_cancel
        self.destroyed.connect(lambda: cancel_on_destroy.set())
        self._export_path = None
        self._selected = None
        self._offset = 0
        self._loaded = False
        self._revision = self.service.revision
        self._periods = (period_for('daily_activity'), period_for('weekly_boss'))
        self._reload_pending = False
        self._cards = []
        self._group_headers = {}
        self._run_record, self._completions = None, {}
        self._material_summary = []
        self._run_panel = None
        self._history_error = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        title = QLabel('完成检查', self)
        title.setProperty('role', 'pageTitle')
        layout.addWidget(title)
        self.notice = QLabel('截图长期保留，仅由你手动删除；查看账号不会切换游戏账号。', self)
        self.notice.setWordWrap(True)
        self.notice.setProperty('role', 'description')
        layout.addWidget(self.notice)
        body = QHBoxLayout()
        layout.addLayout(body, 1)
        sidebar = QWidget(self)
        sidebar.setFixedWidth(210)
        left = QVBoxLayout(sidebar)
        left.setContentsMargins(0, 0, 8, 0)
        self.sequence = QtComboBox(sidebar)
        self.sequence.addItem('全部账号', None)
        self.search = QLineEdit(sidebar)
        self.search.setPlaceholderText('搜索账号编号或昵称')
        self.accounts = QListWidget(sidebar)
        self.accounts.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left.addWidget(self.sequence)
        left.addWidget(self.search)
        left.addWidget(self.accounts, 1)
        self.refresh_button = PushButton('刷新', sidebar)
        left.addWidget(self.refresh_button)
        body.addWidget(sidebar)
        right = QWidget(self)
        content = QVBoxLayout(right)
        content.setContentsMargins(0, 0, 0, 0)
        self.account_title = QLabel('请选择账号', right)
        self.account_title.setWordWrap(True)
        content.addWidget(self.account_title)
        tools = QHBoxLayout()
        self.mode = QtComboBox(right)
        for title, key in [('当前检查', 'current'), ('历史记录', 'history'), ('回收区', 'trash')]:
            self.mode.addItem(title, key)
        self.project_filter = QtComboBox(right)
        self.project_filter.addItem('全部项目', None)
        for key, (name, _) in PROJECTS.items():
            self.project_filter.addItem(name, key)
        tools.addWidget(self.mode)
        tools.addWidget(self.project_filter)
        content.addLayout(tools)
        actions = QHBoxLayout()
        self.pending_only = QCheckBox('仅待检查', right)
        self.capture_button = PrimaryPushButton('保存当前画面', right)
        self.export_button = PushButton('打包当前账号截图', right)
        self.export_button.setEnabled(False)
        self.reexport_button = PushButton('重新打包', right)
        self.reexport_button.setToolTip('按凌晨4点分日，重新打包所有日期各类别最后一张截图，不要求新增截图。')
        self.reexport_button.setEnabled(False)
        self.cancel_export_button = PushButton('取消打包', right)
        self.cancel_export_button.hide()
        self.open_export_button = PushButton('打开压缩包所在文件夹', right)
        self.open_export_button.hide()
        actions.addWidget(self.pending_only)
        actions.addStretch()
        actions.addWidget(self.open_export_button)
        actions.addWidget(self.cancel_export_button)
        actions.addWidget(self.reexport_button)
        actions.addWidget(self.export_button)
        actions.addWidget(self.capture_button)
        content.addLayout(actions)
        self.export_status = QLabel('每天每个类别仅打包最后一张原图；后续点击自动续打包。', right)
        self.export_status.setWordWrap(True)
        content.addWidget(self.export_status)
        self.scroll = QScrollArea(right)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid_widget = QWidget(self.scroll)
        self.grid = QGridLayout(self.grid_widget)
        self.grid.setAlignment(Qt.AlignTop)
        self.grid.setSpacing(12)
        self.scroll.setWidget(self.grid_widget)
        content.addWidget(self.scroll, 1)
        self.more = PushButton('加载下一页', right)
        self.previous = PushButton('上一页', right)
        self.more.hide()
        self.previous.hide()
        paging = QHBoxLayout()
        paging.addWidget(self.previous)
        paging.addWidget(self.more)
        content.addLayout(paging)
        self.storage_button = PushButton('检查存储与空间', sidebar)
        left.addWidget(self.storage_button)
        self.backup_button = PushButton('备份证据', sidebar)
        left.addWidget(self.backup_button)
        body.addWidget(right, 1)
        self.load_operation = BackgroundOperation(self)
        self.load_operation.busy_changed.connect(self._load_state_changed)
        self.capture_operation = BackgroundOperation(self, (self.capture_button,))
        self.action_operation = BackgroundOperation(self)
        self.export_operation = BackgroundOperation(self)
        self.export_operation.busy_changed.connect(self._export_busy_changed)
        self.export_progress.connect(self._export_progress_changed)
        self.export_button.clicked.connect(self.export_account_screenshots)
        self.reexport_button.clicked.connect(lambda: self.export_account_screenshots(full=True))
        self.cancel_export_button.clicked.connect(self._export_cancel.set)
        self.open_export_button.clicked.connect(self._open_export_folder)
        self.search.textChanged.connect(self._filter_accounts)
        self.sequence.currentIndexChanged.connect(self._filter_accounts)
        self.accounts.currentItemChanged.connect(self._select_account)
        self.refresh_button.clicked.connect(self.reload_accounts)
        self.mode.currentIndexChanged.connect(self.reload_records)
        self.project_filter.currentIndexChanged.connect(self.reload_records)
        self.pending_only.toggled.connect(self._display_records)
        self.capture_button.clicked.connect(lambda: self.capture_evidence())
        self.more.clicked.connect(self.next_page)
        self.previous.clicked.connect(self.previous_page)
        self.storage_button.clicked.connect(self.inspect_storage)
        self.backup_button.clicked.connect(self.backup_evidence)
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.reload_accounts)

    def _error(self, error):
        self.notice.setText(f'证据操作失败：{error}。原有截图不会自动删除。')

    def reload_accounts(self):
        if self.load_operation.busy:
            return
        provider, repository = self.account_provider, self.repository
        def work():
            source = provider()
            projection = source.get_detached_projection() if source else {}
            return projection, repository.profiles(), repository.get_preference('selected_account')
        self.load_operation.start(work, self._accounts_loaded, self._error)

    def select_account_project(self, profile_id, task_id):
        mapping = {'nightmare_nest': 'nightmare_nest', 'daily_activity': 'daily_activity',
                   'weekly_boss': 'weekly_boss', 'weekly_garden': 'weekly_garden',
                   'adversity_tower': 'adversity_tower'}
        self._selected = profile_id
        self.sequence.setCurrentIndex(0)
        self.search.clear()
        self.pending_only.setChecked(False)
        self.mode.setCurrentIndex(max(0, self.mode.findData('current')))
        project = mapping.get(task_id, task_id if self.project_filter.findData(task_id) >= 0 else None)
        self.project_filter.setCurrentIndex(max(0, self.project_filter.findData(project)))
        if self._loaded:
            self._filter_accounts()
        else:
            self.reload_accounts()

    def _accounts_loaded(self, result):
        projection, archived, preferred = result
        profiles = projection.get('profiles', {})
        self._profiles = {p['profile_id']: account_display_label(p) for p in
                          sorted(profiles.values(), key=lambda p: account_sort_key(p, p['profile_id']))}
        self._nicknames = {p['profile_id']: p.get('nickname') or
                           parse_account_label(p.get('display_name') or name).get('nickname') or
                           p.get('short_name') or p['profile_id'][:8]
                           for name, p in profiles.items()}
        names = {name: p['profile_id'] for name, p in profiles.items()}
        self._sequences = {key: [names[n] for n in values if n in names]
                           for key, values in projection.get('sequences', {}).items()}
        for identity in archived:
            self._profiles.setdefault(identity, f'已停用账号 · {identity[:8]}')
        self._selected = self._selected or preferred
        chosen = self.sequence.currentData()
        self.sequence.blockSignals(True)
        self.sequence.clear()
        self.sequence.addItem('全部账号', None)
        for sequence in self._sequences:
            self.sequence.addItem(sequence, sequence)
        self.sequence.setCurrentIndex(max(0, self.sequence.findData(chosen)))
        self.sequence.blockSignals(False)
        self._loaded = True
        self._filter_accounts()
        pending = getattr(self, '_pending_capture', None)
        if pending is not None:
            self._pending_capture = None
            QTimer.singleShot(0, lambda: self.capture_evidence(pending or None))

    def _filter_accounts(self, *_):
        selected, query = self._selected, self.search.text().strip().casefold()
        members = self._sequences.get(self.sequence.currentData())
        ids = [identity for identity in self._profiles if members is None or identity in members]
        self.accounts.blockSignals(True)
        self.accounts.clear()
        current = None
        for identity in ids:
            label = self._profiles[identity]
            if query and query not in label.casefold():
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, identity)
            item.setToolTip(label)
            self.accounts.addItem(item)
            if identity == selected:
                current = item
        self.accounts.blockSignals(False)
        self.accounts.setCurrentItem(current or self.accounts.item(0))
        if not self.accounts.count():
            self._selected = None
            self.export_button.setEnabled(False)
            self.reexport_button.setEnabled(False)
            if not self.export_operation.busy:
                self._export_path = None
                self.open_export_button.hide()
            self.account_title.setText('没有匹配的账号')
            self._rows = []
            self._display_records()

    def _select_account(self, current, _previous=None):
        if current:
            self._run_record, self._completions, self._history_error = None, {}, ''
            self._material_summary = []
            self._selected = current.data(Qt.UserRole)
            self.export_button.setEnabled(not self.export_operation.busy)
            self.reexport_button.setEnabled(not self.export_operation.busy)
            if not self.export_operation.busy:
                self._export_path = None
                self.open_export_button.hide()
                self.export_status.setText('正在读取该账号的上次打包记录…')
            self.account_title.setText(self._profiles[self._selected])
            self._rows = []
            self._display_records()
            self.reload_records()

    def reload_records(self, *_):
        self._offset = 0
        self._load_records()

    def next_page(self):
        self._offset += 60
        self._load_records()

    def previous_page(self):
        self._offset = max(0, self._offset - 60)
        self._load_records()

    def inspect_storage(self):
        def loaded(result):
            self.notice.setText(f"证据占用 {result['bytes'] / 1024 / 1024:.1f} MB；"
                f"待整理文件 {len(result['orphans'])} 个，缺失文件 {len(result['missing'])} 个。"
                f"所有文件均保留。目录：{self.repository.root}")
        self.action_operation.start(self.repository.inspect_storage, loaded, self._error)

    def backup_evidence(self):
        self.action_operation.start(self.repository.backup,
            lambda path: self.notice.setText(f'证据备份已保存：{path}；备份也不会自动清理。'), self._error)

    def _load_records(self):
        if not self._selected:
            return
        if self.load_operation.busy:
            self._reload_pending = True
            return
        self._reload_pending = False
        identity, project = self._selected, self.project_filter.currentData()
        mode, offset, repo = self.mode.currentData(), self._offset, self.repository
        provider = self.account_provider
        def work():
            # View preferences are not account task configuration or completion state.
            repo.set_preference('selected_account', identity)
            rows = (repo.read_current(identity, project) if mode == 'current' else
                    repo.read_page(identity, project, mode == 'trash', offset=offset))
            completions, error, material_summary = {}, '', []
            try:
                source = provider()
                if source and any(p.profile_id == identity for p in source.list_profiles()):
                    completions = source.get_profile_completions(identity)
                    from src.task.world_boss_material_plan import material_plan
                    from src.task.world_boss_material_progress import WorldBossMaterialProgress
                    from src.task.world_boss_materials import TARGETS_BY_ID
                    from src.task.farming_task_queue import FARMING_TASKS, farming_tasks, task_status, task_target_label
                    tasks = source.load_profile(identity).tasks
                    if FARMING_TASKS in tasks:
                        for item in farming_tasks(tasks):
                            done, pending, detail, _ = task_status(item, source.integrity_service, identity)
                            state = '领取待核验' if pending else '已达标' if done else '已暂停' if not item['enabled'] else '待执行'
                            material_summary.append(f'{item["name"]} · {task_target_label(item)}：{detail} · {state}')
                    else:
                        plan = material_plan(tasks)
                        progress = WorldBossMaterialProgress(source.integrity_service, identity)
                        counts = progress.counts()
                        for row in plan:
                            if row['boss'] != 'none' and row['limit'] > 0:
                                count = counts.get(row['boss'], 0)
                                material_summary.append(f"{TARGETS_BY_ID[row['boss']].name}：已领 {count}/{row['limit']} 次" +
                                                        (' · 已达标' if count >= row['limit'] else ' · 待领取'))
                        if progress.pending():
                            material_summary.append('有材料领奖待核验，请停止任务后到账号设置核对。')
            except Exception:
                error = '完成记录或首领材料进度暂不可读取；截图记录不受影响。'
            migration = json.loads(repo.get_preference('daily_periods_v2') or '{}')
            if migration.get('invalid'):
                error += f" {len(migration['invalid'])} 条旧证据时间无效，保留在历史记录中，未猜测周期。"
            return rows, repo.latest_run(identity), completions, error, export_state(repo, identity), material_summary
        def loaded(result):
            if (identity, project, mode, offset) != (self._selected, self.project_filter.currentData(), self.mode.currentData(), self._offset):
                self._load_records()
                return
            rows, self._run_record, self._completions, self._history_error, state, self._material_summary = result
            if not self.export_operation.busy:
                self._show_export_state(state)
            self._rows = rows
            if self._history_error:
                self.notice.setText(self._history_error)
            self.more.setVisible(mode != 'current' and len(rows) == 60)
            self.previous.setVisible(mode != 'current' and offset > 0)
            self._display_records()
        self.load_operation.start(work, loaded, self._error)

    def _show_export_state(self, state):
        self._export_path = state.get('path')
        self.open_export_button.setVisible(bool(self._export_path))
        self.export_status.setText(
            f"上次成功打包：{state['completed_at']}；下次从 {state['cutoff']} 继续（北京时间）。"
            if state else '按北京时间凌晨4点分日，每个类别仅保留最后一张截图；首次覆盖历史，后续自动续打包。')

    def _export_busy_changed(self, busy):
        self.export_button.setEnabled(bool(self._selected) and not busy)
        self.reexport_button.setEnabled(bool(self._selected) and not busy)
        self.cancel_export_button.setVisible(busy)

    def _export_progress_changed(self, done, total):
        self.export_status.setText(f'正在打包：{done}/{total} 张；完成后校验压缩包。')

    def export_account_screenshots(self, checked=False, *, full=False):
        if not self._selected or self.export_operation.busy:
            return
        identity, cutoff, repo = self._selected, now_iso(), self.repository
        nickname = self._nicknames.get(identity) or self._profiles.get(identity, identity[:8])
        self._export_cancel.clear()
        cancel, progress = self._export_cancel, self.export_progress.emit
        self.export_status.setText(f'正在重新打包 {nickname} 全部日期的最后截图…' if full else
                                   f'正在打包 {nickname} 每天各类别的最后截图…')
        def work():
            return export_screenshots(repo, identity, nickname, cutoff, cancelled=cancel, progress=progress, full=full)
        def loaded(result):
            if not result['path']:
                self.export_status.setText(f'{nickname} 没有可打包截图。' if full else
                                           f'{nickname} 没有新增截图；可点击“重新打包”再次打包全部日期。')
                return
            self._export_path = result['path']
            self.open_export_button.show()
            self.export_status.setText(f"{nickname} 打包成功，共 {result['count']} 张；"
                                       f"截止 {result['state']['cutoff']}。压缩包：{result['path']}")
            self._open_export_folder()
        def failed(error):
            self.export_status.setText(f'截图打包未完成：{error}。上次成功截止时间保持不变。')
        self.export_operation.start(work, loaded, failed)

    def _open_export_folder(self):
        if not self._export_path:
            return
        try:
            import os
            if os.name == 'nt':
                subprocess.Popen(['explorer.exe', '/select,', self._export_path])
            elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._export_path).parent))):
                raise OSError('无法启动文件管理器')
        except OSError as error:
            self.export_status.setText(f'压缩包已保存：{self._export_path}；打开文件夹失败：{error}，可点击按钮重试。')

    def _load_state_changed(self, busy):
        if not busy and self._reload_pending:
            QTimer.singleShot(0, self._resume_pending_load)

    def _resume_pending_load(self):
        if self._reload_pending:
            self._load_records()

    def _display_records(self, *_):
        expanded = bool(self._run_panel and self._run_panel.toggle_button.isChecked())
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards = []
        self._group_headers = {}
        if not self._selected:
            self._run_panel = None
            return
        self._add_run_panel(expanded)
        mode = self.mode.currentData()
        if mode == 'current':
            projects = [self.project_filter.currentData()] if self.project_filter.currentData() else list(PROJECTS)
            for project in projects:
                if project not in CURRENT_PROJECTS and not any(r['project_id'] == project for r in self._rows):
                    continue
                period = period_for(project)
                rows = [r for r in self._rows if r['project_id'] == project and r['period_id'] == period]
                record, conflict = summarize(rows)
                if self.pending_only.isChecked() and record and record['completion_status'] == 'completed' and not conflict:
                    continue
                self._add_card(project, record, conflict)
        else:
            for record in self._rows:
                if self.pending_only.isChecked() and record['completion_status'] == 'completed':
                    continue
                self._add_card(record['project_id'], record)
        if not self._cards:
            self.grid.addWidget(QLabel('暂无符合条件的证据；没有截图不代表未完成。'), 1, 0)
        self._layout_cards()

    def _add_run_panel(self, expanded):
        from pathlib import Path
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from src.gui.SectionPanel import SectionPanel
        panel = self._run_panel = SectionPanel('运行记录', parent=self.grid_widget,
                                              collapsible=True, expanded=expanded)
        panel.setStyleSheet('QWidget#codexSection { border: 0; }')
        panel.layout().setContentsMargins(0, 0, 0, 0)
        record = self._run_record or {}
        results = {'running': '未记录结束（结果未确认）', 'returned': '正常返回（不代表全部完成）',
                   'failed': '执行出错', 'stopped': '已停止'}
        scopes = {'weekly_boss': '周本单独执行', 'world_boss_material': '首领材料单独执行', 'daily': '每日任务'}
        lines = ['最近执行范围：' + (scopes.get(record.get('scope'), '每日任务') if record else '无记录'),
                 '最近开始时间：' + str(record.get('started_at') or '无记录'),
                 '最近结束时间：' + str(record.get('finished_at') or '无记录'),
                 '最近执行结果：' + results.get(record.get('result'), '无记录')]
        names = {'Daily Task': '每日任务', 'Nightmare Nest': '残像聚落', 'Weekly Garden': '每周乐园',
                 'Weekly Boss Monday Check': '周本周一检查', 'Weekly Boss Sunday Check': '周本周日复检',
                 'Tacet Suppression': '无音区', 'Forgery Challenge': '凝素领域',
                 'Simulation Challenge': '模拟训练', 'Merge Echo': '声骸合成'}
        completed = [(names.get(key, key), stamp) for key, stamp in self._completions.items() if isinstance(stamp, str)]
        lines.append('上次完成时间（仅有完成记录，不等于图片证据）：')
        lines.extend(f'{name}：{stamp}' for name, stamp in completed)
        if not completed:
            lines.append('无记录')
        if self._material_summary:
            lines.append('首领材料累计目标（跨日跨周保留）：')
            lines.extend(self._material_summary)
        if self._history_error:
            lines.append(self._history_error)
        label = QLabel('\n'.join(lines), panel)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        panel.add_widget(label)
        for index, value in enumerate(record.get('video_paths', []), 1):
            path = Path(value)
            button = PushButton(f'打开关联录像 {index}', panel)
            # Only explicit local video paths recorded by this run; never infer ownership from folders.
            button.setEnabled(path.is_absolute() and path.suffix.lower() == '.mp4')
            def open_video(*_, path=path):
                if path.is_file():
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                else:
                    self.notice.setText('关联录像不存在或设备路径不可用；未删除任何记录。')
            button.clicked.connect(open_video)
            panel.add_widget(button)
        self.grid.addWidget(panel, 0, 0, 1, 3)

    def _add_card(self, project, record, conflict=False):
        card = QWidget(self.grid_widget)
        card.setProperty('project_id', project)
        card.setObjectName('completionEvidenceCard')
        card.setStyleSheet(f'QWidget#completionEvidenceCard {{ background: {COLORS["panel"]}; border: 1px solid {COLORS["border"]}; border-radius: 10px; }}')
        card.setMinimumWidth(160)
        layout = QVBoxLayout(card)
        layout.setAlignment(Qt.AlignTop)
        preview = QPushButton('暂无图片', card)
        preview.setFixedHeight(110)
        preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if record and record.get('_thumbnail'):
            from PySide6.QtGui import QIcon
            from PySide6.QtCore import QSize
            preview.setText('')
            preview.setIcon(QIcon(picture(record['_thumbnail'], 240, 105)))
            preview.setIconSize(QSize(220, 100))
        preview.setAccessibleName(PROJECTS[project][0] + '证据预览')
        preview.setEnabled(bool(record))
        if record:
            preview.clicked.connect(partial(self.show_detail, record))
        layout.addWidget(preview)
        title = QLabel(PROJECTS[project][0], card)
        title.setWordWrap(True)
        layout.addWidget(title)
        if record:
            text = (f"{STATUSES[record['completion_status']]} · {SOURCES[record['source']]}\n"
                    f"{ASSETS[record['asset_status']]}\n{record['captured_at'][:19].replace('T', ' ')}\n"
                    f"{period_label(record['period_id'], project)}")
            if conflict:
                text += '\n自动与人工结论不同，请核验历史'
            observation = record.get('_period_observation')
            if observation:
                text += (f"\n本周期另有记录：{STATUSES[observation['completion_status']]}"
                         f" · {SOURCES[observation['source']]}\n{observation['captured_at'][:19]}（不替代本图判断）")
        else:
            text = {'day': '本日暂无记录', 'week': '本周暂无记录'}.get(PROJECTS[project][1], '暂无截图')
            text += '\n可查看历史或手动保存；没有记录不代表未完成'
        description = QLabel(text, card)
        description.setWordWrap(True)
        description.setProperty('role', 'description')
        layout.addWidget(description)
        if record:
            copy_button = PushButton('复制图片', card)
            copy_button.clicked.connect(partial(self.copy_record, record))
            layout.addWidget(copy_button)
            image_copy_menu(card, partial(self.copy_record, record))
            image_copy_menu(preview, partial(self.copy_record, record))
            actions = QHBoxLayout()
            if record['trashed']:
                for title, action in [('恢复', 'restore'), ('永久删除', 'delete')]:
                    button = PushButton(title, card)
                    button.clicked.connect(partial(self.change_record, record, action))
                    actions.addWidget(button)
            else:
                button = PushButton('移入回收区', card)
                button.clicked.connect(partial(self.change_record, record, 'trash'))
                actions.addWidget(button)
            layout.addLayout(actions)
        self._cards.append(card)

    def _layout_cards(self):
        columns = max(1, min(3, self.scroll.viewport().width() // 250))
        for card in self._cards:
            self.grid.removeWidget(card)
        for header in self._group_headers.values():
            self.grid.removeWidget(header)
        row = 1
        if self.mode.currentData() == 'current':
            for group, title in GROUPS.items():
                cards = [card for card in self._cards if project_group(card.property('project_id')) == group]
                if not cards:
                    continue
                if group not in self._group_headers:
                    header = QLabel(title, self.grid_widget)
                    header.setProperty('role', 'sectionTitle')
                    self._group_headers[group] = header
                self.grid.addWidget(self._group_headers[group], row, 0, 1, columns)
                row += 1
                for index, card in enumerate(cards):
                    self.grid.addWidget(card, row + index // columns, index % columns)
                row += (len(cards) + columns - 1) // columns
        else:
            for index, card in enumerate(self._cards):
                self.grid.addWidget(card, row + index // columns, index % columns)
        for column in range(3):
            self.grid.setColumnStretch(column, int(column < columns))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_cards'):
            QTimer.singleShot(0, self._layout_cards)

    def show_detail(self, record):
        if self.action_operation.busy:
            return
        repo = self.repository
        def work():
            relative = record.get('image_path')
            return repo.asset_path(relative).read_bytes() if relative and repo.asset_path(relative).is_file() else None
        self.action_operation.start(work, lambda data: EvidenceDetailDialog(record, data, self).exec(), self._error)

    def copy_record(self, record):
        if self.action_operation.busy:
            return
        repo, relative = self.repository, record.get('image_path')
        def work():
            return repo.asset_path(relative).read_bytes() if relative else None
        def copied(data):
            try:
                copy_image(data)
                self.notice.setText('图片已复制，可在微信中粘贴')
            except ValueError as error:
                self._error(error)
        self.action_operation.start(work, copied, self._error)

    def change_record(self, record, action):
        if self.action_operation.busy:
            return
        title = {'trash': '移入回收区', 'restore': '恢复证据', 'delete': '永久删除'}[action]
        message = (f"{title}这张 {PROJECTS[record['project_id']][0]} 证据？\n记录时间：{record['captured_at']}\n"
                   + ('原图及说明将不可恢复。' if action == 'delete' else '不会修改自动任务的完成状态。'))
        if QMessageBox.question(self, title, message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        repo, identity = self.repository, record['evidence_id']
        work = (lambda: repo.permanently_delete(identity, confirmed=True)) if action == 'delete' else partial(getattr(repo, action), identity)
        self.action_operation.start(work, lambda _: self.reload_records(), self._error)

    def capture_evidence(self, project_id=None):
        if self.capture_operation.busy:
            return
        if not self._profiles:
            if self._loaded:
                self._error(ValueError('没有可保存证据的账号，请先配置账号'))
                return
            self._pending_capture = project_id or ''
            self.reload_accounts()
            return
        selected, profiles = self._selected, dict(self._profiles)
        try:
            future = request_capture(self.executor)
        except Exception as error:
            self._error(error)
            return
        def failed(error):
            future.cancel()
            self._error(error)
        def captured(value):
            dialog = EvidenceCaptureDialog(value, profiles, selected, project_id, self)
            if dialog.exec() != QDialog.Accepted:
                return
            metadata = dialog.metadata()
            service, frame = self.service, value['frame']
            self.capture_operation.start(lambda: service.submit(metadata, frame).result(),
                lambda _: self.reload_records(), self._error)
        self.capture_operation.start(lambda: future.result(timeout=9), captured, failed)

    def _poll(self):
        periods = (period_for('daily_activity'), period_for('weekly_boss'))
        if self.isVisible() and (self.service.revision != self._revision or periods != self._periods):
            self._periods = periods
            self._revision = self.service.revision
            self.reload_records()
        if self.isVisible() and self.service.last_error:
            self.notice.setText(self.service.last_error + '；旧截图不会自动删除。')
