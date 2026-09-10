"""Read-only account evidence dashboard and explicit manual capture/recycle UI."""
from functools import partial

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QListWidget, QListWidgetItem, QLineEdit, QScrollArea, QDialog, QDialogButtonBox,
    QMessageBox, QCheckBox, QPlainTextEdit, QSizePolicy, QPushButton)
from qfluentwidgets import FluentIcon, PushButton, PrimaryPushButton

from src.account_display import account_display_label
from src.account_repository import get_default_repository
from src.evidence.model import PROJECTS, STATUSES, SOURCES, ASSETS, period_for, period_label, summarize
from src.evidence.service import EvidenceService, get_evidence_service, request_capture
from src.gui.BackgroundOperation import BackgroundOperation
from src.gui.ChoiceControls import QtComboBox
from src.gui.CodexTheme import COLORS


def picture(data, width=280, height=140):
    pixmap = QPixmap()
    if data:
        pixmap.loadFromData(data)
    return pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)


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
        for profile_id, label in profiles.items():
            self.account.addItem(label, profile_id)
        binding = capture.get('profile_id')
        candidate = binding or selected
        self.account.setCurrentIndex(self.account.findData(candidate))
        self.account.setEnabled(not bool(binding))
        layout.addWidget(QLabel('截图所属账号（不是游戏自动登录操作）'))
        layout.addWidget(self.account)
        self.project = QtComboBox(self)
        for key, (title, _) in PROJECTS.items():
            self.project.addItem(title, key)
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
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def metadata(self):
        if not self.confirm.isChecked() or self.account.currentData() is None:
            raise ValueError('请明确确认截图所属账号')
        status = self.status.currentData()
        return dict(profile_id=self.account.currentData(), project_id=self.project.currentData(),
                    completion_status=status, source='manual_capture' if status == 'unknown' else 'manual_confirmation',
                    captured_at=self.capture['captured_at'], identity_source=self.capture['identity_source'],
                    note=self.note.toPlainText().strip())


class EvidenceDetailDialog(QDialog):
    def __init__(self, record, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(PROJECTS[record['project_id']][0] + ' · 证据详情')
        self.resize(880, 680)
        self.pixmap = QPixmap()
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
                      f"记录时间：{record['captured_at']}\n{period_label(record['period_id'])}\n{progress}\n"
                      f"{record.get('reason', '')}\n{record.get('note', '')}", self)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(text)
        controls = QHBoxLayout()
        for title, callback in [('适应窗口', self.fit), ('原始大小', self.original), ('关闭', self.accept)]:
            button = PushButton(title, self)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        QTimer.singleShot(0, self.fit)

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

    def __init__(self, executor, repository=None, account_provider=None):
        super().__init__()
        self.setObjectName('CompletionCheckTab')
        self.executor = executor
        self.service = EvidenceService(repository) if repository else get_evidence_service()
        self.repository = self.service.repository
        executor.completion_evidence_service = self.service
        self.account_provider = account_provider or get_default_repository
        self._profiles, self._sequences, self._rows = {}, {}, []
        self._selected = None
        self._offset = 0
        self._loaded = False
        self._revision = self.service.revision
        self._periods = (period_for('daily_activity'), period_for('weekly_boss'))
        self._reload_pending = False
        self._cards = []
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
        for title, key in [('当前周期', 'current'), ('历史记录', 'history'), ('回收区', 'trash')]:
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
        actions.addWidget(self.pending_only)
        actions.addStretch()
        actions.addWidget(self.capture_button)
        content.addLayout(actions)
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

    def _accounts_loaded(self, result):
        projection, archived, preferred = result
        profiles = projection.get('profiles', {})
        self._profiles = {p['profile_id']: account_display_label(p) for p in profiles.values()}
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
        ids = self._sequences.get(self.sequence.currentData(), list(self._profiles))
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
            self.account_title.setText('没有匹配的账号')
            self._rows = []
            self._display_records()

    def _select_account(self, current, _previous=None):
        if current:
            self._selected = current.data(Qt.UserRole)
            self.account_title.setText(self._profiles[self._selected])
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
        def work():
            # View preferences are not account task configuration or completion state.
            repo.set_preference('selected_account', identity)
            return (repo.read_current(identity, project) if mode == 'current' else
                    repo.read_page(identity, project, mode == 'trash', offset=offset))
        def loaded(rows):
            if (identity, project, mode, offset) != (self._selected, self.project_filter.currentData(), self.mode.currentData(), self._offset):
                self._load_records()
                return
            self._rows = rows
            self.more.setVisible(mode != 'current' and len(rows) == 60)
            self.previous.setVisible(mode != 'current' and offset > 0)
            self._display_records()
        self.load_operation.start(work, loaded, self._error)

    def _load_state_changed(self, busy):
        if not busy and self._reload_pending:
            QTimer.singleShot(0, self._resume_pending_load)

    def _resume_pending_load(self):
        if self._reload_pending:
            self._load_records()

    def _display_records(self, *_):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards = []
        if not self._selected:
            return
        mode = self.mode.currentData()
        if mode == 'current':
            projects = [self.project_filter.currentData()] if self.project_filter.currentData() else list(PROJECTS)
            for project in projects:
                period = period_for(project)
                rows = [r for r in self._rows if r['project_id'] == project and r['period_id'] == period]
                record, conflict = summarize(rows)
                if self.pending_only.isChecked() and period and record and record['completion_status'] == 'completed' and not conflict:
                    continue
                self._add_card(project, record, conflict)
        else:
            for record in self._rows:
                if self.pending_only.isChecked() and record['completion_status'] == 'completed':
                    continue
                self._add_card(record['project_id'], record)
        if not self._cards:
            self.grid.addWidget(QLabel('暂无符合条件的证据；没有截图不代表未完成。'), 0, 0)
        self._layout_cards()

    def _add_card(self, project, record, conflict=False):
        card = QWidget(self.grid_widget)
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
                    f"{period_label(record['period_id'])}")
            if conflict:
                text += '\n自动与人工结论不同，请核验历史'
        else:
            text = '暂无当前周期证据\n可手动保存；未识别不等于未完成'
            if project not in ('daily_activity', 'weekly_garden', 'weekly_boss'):
                text += '\n尚未接入自动采集'
        description = QLabel(text, card)
        description.setWordWrap(True)
        description.setProperty('role', 'description')
        layout.addWidget(description)
        if record:
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
        for index, card in enumerate(self._cards):
            self.grid.addWidget(card, index // columns, index % columns)
        for column in range(3):
            self.grid.setColumnStretch(column, int(column < columns))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_cards'):
            self._layout_cards()

    def show_detail(self, record):
        if self.action_operation.busy:
            return
        repo = self.repository
        def work():
            relative = record.get('image_path')
            return repo.asset_path(relative).read_bytes() if relative and repo.asset_path(relative).is_file() else None
        self.action_operation.start(work, lambda data: EvidenceDetailDialog(record, data, self).exec(), self._error)

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
