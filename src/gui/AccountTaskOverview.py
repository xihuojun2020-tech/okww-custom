"""ALAS-style account overview with input-free refresh and explicit manual marks."""
from time import monotonic

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QScrollArea

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
        self.repository, self.live_provider = repository, live_provider
        self.profile_id = None
        self._last_signature = None
        self._last_loaded = 0
        self._cards = []
        self._elapsed_labels = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel('请选择账号', self)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.notice = QLabel('', self)
        self.notice.setWordWrap(True)
        self.notice.setProperty('role', 'description')
        layout.addWidget(self.notice)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.host = QWidget(self.scroll)
        self.groups_layout = QVBoxLayout(self.host)
        self.groups_layout.setContentsMargins(0, 0, 4, 0)
        self.groups_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.host)
        layout.addWidget(self.scroll, 1)
        self.loading = BackgroundOperation(self)
        self.marking = BackgroundOperation(self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)

    def set_profile(self, identity):
        self.profile_id = identity
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
        for label, text in self._elapsed_labels:
            label.setText(text + f' · 本次运行耗时：{live.get("elapsed", 0)} 秒')
        now = beijing_now()
        signature = (self.profile_id, game_day_key(now), tuple(sorted((k, v) for k, v in live.items() if k != 'elapsed')))
        if not force and signature == self._last_signature and monotonic() - self._last_loaded < 10:
            return
        identity, repository = self.profile_id, self.repository
        self._last_signature = signature
        def work():
            profile = repository.load_profile(identity)
            cards = build_account_task_cards(profile, repository.integrity_service, now=now, live=live)
            return cards
        def loaded(cards):
            if identity != self.profile_id:
                QTimer.singleShot(0, lambda: self.refresh(force=True))
                return
            self._last_loaded = monotonic()
            self._cards = cards
            self._render(cards, now, live)
        def failed(error):
            if identity == self.profile_id:
                self.notice.setText(f'任务记录无法读取，请核对：{type(error).__name__}: {error}')
                self.summary.setText('当前账号记录无法读取 · 需要处理')
                self._cards = []
                self._clear()
            else:
                QTimer.singleShot(0, lambda: self.refresh(force=True))
        self.loading.start(work, loaded, failed)

    def _clear(self):
        self._elapsed_labels = []
        while self.groups_layout.count():
            item = self.groups_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    @staticmethod
    def _time(value):
        stamp = parse_legacy_time(value)
        return stamp.strftime('%m-%d %H:%M') if stamp else '未记录'

    def _render(self, cards, now, live):
        scroll = self.scroll.verticalScrollBar().value()
        self._clear()
        done = sum(c.state == 'completed' and not c.manual for c in cards)
        reminders = [c for c in cards if c.manual]
        self.summary.setText(f'游戏日 {game_day_key(now)} · 北京时间 · 手动启动\n'
                             f'执行／独立任务完成 {done}/{len(cards) - len(reminders)} · '
                             f'提醒完成 {sum(c.state == "completed" for c in reminders)}/{len(reminders)}')
        self.notice.setText('其他账号正在执行；本页只展示当前所选账号。'
                           if live.get('profile_id') and live['profile_id'] != self.profile_id else '')
        titles = {'running': '运行中', 'pending': '待执行／待办', 'waiting': '等待中',
                  'attention': '需要处理', 'completed': '已完成'}
        for state, title in titles.items():
            selected = [card for card in cards if card.state == state]
            group = SectionPanel(f'{title}（{len(selected)}）', parent=self.host)
            if not selected:
                group.add_widget(QLabel('无任务', group))
            for card in selected:
                body = QWidget(group)
                body_layout = QVBoxLayout(body)
                body_layout.setContentsMargins(8, 6, 8, 8)
                header = QHBoxLayout()
                name = QLabel(card.title, body)
                name.setProperty('role', 'sectionTitle')
                header.addWidget(name, 1)
                settings = QPushButton('设置', body)
                settings.clicked.connect(lambda *_, route=card.route: self.navigate.emit(route))
                header.addWidget(settings)
                record = QPushButton('记录', body)
                record.clicked.connect(lambda *_, key=card.task_id: self.records.emit(key))
                header.addWidget(record)
                body_layout.addLayout(header)
                text = card.detail + f'\n最近完成：{self._time(card.completed_at)} · 来源：{card.source}'
                if card.started_at:
                    text += f'\n最近开始：{self._time(card.started_at)}'
                if state == 'running' and live.get('elapsed') is not None:
                    running = True
                else:
                    running = False
                if card.next_at:
                    kind = ('下次可检查' if card.task_id in ('weekly_boss', 'merge_echo') else
                            '本期预计结束（倒计时上界）' if card.task_id == 'adversity_tower' else '下次重置')
                    text += f'\n{kind}：{self._time(card.next_at)}'
                label = QLabel(text, body)
                label.setWordWrap(True)
                label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                label.setProperty('role', 'error' if state == 'attention' else 'description')
                if running:
                    self._elapsed_labels.append((label, text))
                    label.setText(text + f' · 本次运行耗时：{live["elapsed"]} 秒')
                body_layout.addWidget(label)
                if card.manual:
                    button = QPushButton('撤销完成' if state == 'completed' else '手动标记完成', body)
                    button.clicked.connect(lambda *_, key=card.task_id, done=state != 'completed': self._mark(key, done))
                    button.setEnabled(not self.marking.busy)
                    body_layout.addWidget(button)
                if card.task_id == 'adversity_tower':
                    button = QPushButton('前往深塔任务（单独启动）', body)
                    button.clicked.connect(lambda *_: self.launch_page.emit('AutoAbyssTask'))
                    body_layout.addWidget(button)
                    if state == 'attention':
                        retry = QPushButton('重新评估本期受阻关卡', body)
                        retry.clicked.connect(self._reset_abyss)
                        body_layout.addWidget(retry)
                group.add_widget(body)
            self.groups_layout.addWidget(group)
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(scroll))

    def _mark(self, task_id, done):
        identity, repository = self.profile_id, self.repository
        def work():
            profile = repository.load_profile(identity)
            row = get_task_reminders(profile.account).get(task_id, {})
            return mark_manual_reminder(repository.integrity_service, identity, task_id, row, done=done)
        def loaded(_):
            self._last_loaded = 0
            self.refresh(force=True)
        self.marking.start(work, loaded, lambda error: self.notice.setText(f'标记未保存：{error}'))

    def _reset_abyss(self):
        identity, service = self.profile_id, self.repository.integrity_service
        if self.live_provider():
            self.notice.setText('请先停止当前任务，再重新评估深塔关卡。')
            return
        from src.task.abyss_cycle_progress import reset_abyss_failures
        self.marking.start(lambda: reset_abyss_failures(service, identity),
                           lambda _: self.refresh(force=True),
                           lambda error: self.notice.setText(f'重新评估未保存：{error}'))
