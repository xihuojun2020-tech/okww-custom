"""ALAS-style account overview with input-free refresh and explicit manual marks."""
from time import monotonic

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QGridLayout, QScrollArea, QSizePolicy

from src.gui.BackgroundOperation import BackgroundOperation
from src.gui.SectionPanel import SectionPanel
from src.account_task_state import build_account_task_cards
from src.account_reminders import get_task_reminders, mark_manual_reminder
from src.game_period import beijing_now, parse_legacy_time, game_day_key


class AccountTaskOverview(QWidget):
    navigate = Signal(str)
    records = Signal(str)
    launch_page = Signal(str)

    def __init__(self, repository, live_provider, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.repository, self.live_provider = repository, live_provider
        self.profile_id = None
        self._last_signature = None
        self._last_loaded = 0
        self._cards = []
        self._elapsed_labels = []
        self._rows, self._groups = {}, {}
        self._generation = 0
        self._filter = None
        self._stale = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel('请选择账号', self)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.notice = QLabel('', self)
        self.notice.setWordWrap(True)
        self.notice.setProperty('role', 'description')
        layout.addWidget(self.notice)
        self.notice.hide()
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.host = QWidget(self.scroll)
        self.groups_layout = QVBoxLayout(self.host)
        self.groups_layout.setContentsMargins(0, 0, 4, 0)
        self.groups_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.host)
        layout.addWidget(self.scroll, 1)
        self.filter_host = QWidget(self)
        self.filter_host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.filters = QGridLayout(self.filter_host)
        self.filters.setContentsMargins(0, 0, 0, 0)
        self.filter_buttons = {}
        for state, title in ((None, '全部'), ('running', '运行中'), ('attention', '需处理'),
                             ('pending', '待执行'), ('waiting', '等待'), ('completed', '已完成')):
            button = QPushButton(title, self)
            button.setCheckable(True)
            button.clicked.connect(lambda *_, state=state: self._set_filter(state))
            index = len(self.filter_buttons)
            self.filters.addWidget(button, index // 3, index % 3)
            self.filter_buttons[state] = button
        layout.insertWidget(2, self.filter_host)
        self.loading = BackgroundOperation(self)
        self.marking = BackgroundOperation(self)
        self.marking.busy_changed.connect(self._update_writable)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)

    def resizeEvent(self, event):
        columns = 6 if self.width() >= 680 else 3
        if columns != getattr(self, '_filter_columns', None):
            self._filter_columns = columns
            for index, button in enumerate(self.filter_buttons.values()):
                self.filters.addWidget(button, index // columns, index % columns)
        super().resizeEvent(event)

    def set_profile(self, identity):
        self.profile_id = identity
        self._generation += 1
        self._stale = False
        self._last_signature = None
        self._last_loaded = 0
        # Remove previous account data immediately, before asynchronous reads finish.
        self._cards = []
        self.summary.setText('正在读取当前账号的任务…')
        self.notice.clear()
        self._clear()
        self.refresh(force=True)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh(force=True)

    def refresh(self, *, force=False):
        if not self.profile_id or self.loading.busy or (not force and not self.isVisible()):
            return
        live = self.live_provider() or {}
        for row in self._rows.values():
            if row.card.state == 'running':
                row.update_card(row.card, live)
        now = beijing_now()
        signature = (self.profile_id, game_day_key(now), tuple(sorted((k, v) for k, v in live.items() if k != 'elapsed')))
        if not force and signature == self._last_signature and monotonic() - self._last_loaded < 10:
            return
        identity, repository = self.profile_id, self.repository
        generation = self._generation
        self._last_signature = signature
        def work():
            profile = repository.load_profile(identity)
            cards = build_account_task_cards(profile, repository.integrity_service, now=now, live=live)
            return cards
        def loaded(cards):
            if identity != self.profile_id or generation != self._generation:
                QTimer.singleShot(0, lambda: self.refresh(force=True))
                return
            self._last_loaded = monotonic()
            self._cards = cards
            self._stale = False
            self._render(cards, now, live)
        def failed(error):
            if identity == self.profile_id and generation == self._generation:
                self._stale = True
                self.notice.setText(f'任务记录读取失败；保留上次快照，状态可能已过期。{type(error).__name__}: {error}')
                self.notice.show()
                if not self._cards:
                    self.summary.setText('当前账号记录无法读取 · 需要处理')
                self._update_writable()
            else:
                QTimer.singleShot(0, lambda: self.refresh(force=True))
        self.loading.start(work, loaded, failed)

    def _clear(self):
        self._elapsed_labels = []
        self._rows, self._groups = {}, {}
        while self.groups_layout.count():
            item = self.groups_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    @staticmethod
    def _time(value):
        stamp = parse_legacy_time(value)
        return stamp.strftime('%m-%d %H:%M') if stamp else '未记录'

    def _set_filter(self, state):
        self._filter = state
        if state == 'completed' and state in self._groups:
            self._groups[state].set_expanded(True)
        self._apply_filter()

    def _apply_filter(self):
        for state, group in self._groups.items():
            group.setVisible(any(c.state == state for c in self._cards) and
                             (self._filter is None or state == self._filter))
        for state, button in self.filter_buttons.items():
            button.setChecked(state == self._filter)

    def _update_writable(self, *_):
        for row in self._rows.values():
            row.set_writable(not self._stale and not self.marking.busy)

    def _render(self, cards, now, live):
        from src.gui.TaskOverviewRow import TaskOverviewRow
        done = sum(c.state == 'completed' and not c.manual for c in cards)
        reminders = [c for c in cards if c.manual]
        self.summary.setText(f'游戏日 {game_day_key(now)} · 北京时间 · 手动启动 · '
                             f'执行完成 {done}/{len(cards) - len(reminders)} · '
                             f'提醒完成 {sum(c.state == "completed" for c in reminders)}/{len(reminders)}')
        self.notice.setText('其他账号正在执行；本页只展示当前所选账号。'
                           if live.get('profile_id') and live['profile_id'] != self.profile_id else '')
        self.notice.setVisible(bool(self.notice.text()))
        titles = {'running': '运行中', 'attention': '需要处理', 'pending': '待执行／待办',
                  'waiting': '等待中', 'completed': '已完成'}
        for state, title in titles.items():
            count = sum(c.state == state for c in cards)
            if state not in self._groups:
                group = SectionPanel(title, parent=self.host, collapsible=state == 'completed')
                self._groups[state] = group
                self.groups_layout.addWidget(group)
            group = self._groups[state]
            group.title_label.setText(f'{title}（{count}）')
            group.header.titleLabel.setText(f'{title}（{count}）')
            group.set_summary('展开查看完成时间与记录' if state == 'completed' else '')
            self.filter_buttons[state].setText(f'{title.split("／")[0]} {count}')
        for key in set(self._rows) - {c.task_id for c in cards}:
            self._rows.pop(key).deleteLater()
        for card in cards:
            row = self._rows.get(card.task_id)
            if row is None:
                row = self._rows[card.task_id] = TaskOverviewRow(self, card)
            elif row.card != card or card.state == 'running':
                row.update_card(card, live)
            group = self._groups[card.state]
            if row.parentWidget() != group.content:
                group.add_widget(row)
        for state, group in self._groups.items():
            for index, card in enumerate(c for c in cards if c.state == state):
                row = self._rows[card.task_id]
                if group.content_layout.indexOf(row) != index + 1:
                    group.content_layout.insertWidget(index + 1, row)
        self.filter_buttons[None].setText(f'全部 {len(cards)}')
        self._apply_filter()
        self._update_writable()

    def _mark(self, task_id, done):
        if self._stale or self.marking.busy:
            return
        identity, repository = self.profile_id, self.repository
        def work():
            profile = repository.load_profile(identity)
            row = get_task_reminders(profile.account).get(task_id, {})
            return mark_manual_reminder(repository.integrity_service, identity, task_id, row, done=done)
        def loaded(_):
            self._last_loaded = 0
            self.refresh(force=True)
        self.marking.start(work, loaded, lambda error: self._write_failed(identity, f'标记未保存：{error}'))

    def _write_failed(self, identity, message):
        if identity == self.profile_id:
            self.notice.setText(message)
            self.notice.show()

    def _reset_abyss(self):
        if self._stale or self.marking.busy:
            return
        identity, service = self.profile_id, self.repository.integrity_service
        if self.live_provider():
            self.notice.setText('请先停止当前任务，再重新评估深塔关卡。')
            self.notice.show()
            return
        from src.task.abyss_cycle_progress import reset_abyss_failures
        self.marking.start(lambda: reset_abyss_failures(service, identity),
                           lambda _: self.refresh(force=True),
                           lambda error: self._write_failed(identity, f'重新评估未保存：{error}'))
