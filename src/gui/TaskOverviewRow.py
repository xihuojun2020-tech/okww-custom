"""Stable compact task row with on-demand provenance and history."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QBoxLayout, QLabel, QPushButton, QToolButton, QSizePolicy
from qfluentwidgets import FluentIcon


class TaskOverviewRow(QWidget):
    def __init__(self, overview, card):
        super().__init__(overview.host)
        self.overview, self.card = overview, card
        self.setObjectName('accountTaskRow')
        self.setAttribute(Qt.WA_StyledBackground)
        layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(4)
        self.header = QHBoxLayout()
        self.name = QLabel(self)
        self.name.setProperty('role', 'sectionTitle')
        self.name.setWordWrap(True)
        self.header.addWidget(self.name, 1)
        self.actions = QWidget(self)
        self.action_layout = QHBoxLayout(self.actions)
        self.action_layout.setContentsMargins(0, 0, 0, 0)
        self.action_layout.setSpacing(8)
        self.badge = QLabel(self.actions)
        self.badge.setProperty('role', 'taskBadge')
        self.action_layout.addWidget(self.badge)
        self.primary = QPushButton(self)
        self.primary.clicked.connect(self._primary)
        self.primary.setProperty('role', 'link')
        self.action_layout.addWidget(self.primary)
        self.settings = QPushButton('设置', self)
        self.settings.clicked.connect(lambda: overview.navigate.emit(self.card.route))
        self.settings.setProperty('role', 'link')
        self.action_layout.addWidget(self.settings)
        self.toggle = QToolButton(self)
        self.toggle.setProperty('role', 'rowDisclosure')
        self.toggle.setIcon(FluentIcon.CHEVRON_RIGHT.icon())
        self.toggle.setFixedSize(36, 36)
        self.toggle.setToolTip('展开详情与记录')
        self.toggle.setCheckable(True)
        self.toggle.setAccessibleName(f'{card.title}：展开详情与记录')
        self.action_layout.addWidget(self.toggle)
        self.header.addWidget(self.actions)
        layout.addLayout(self.header)
        self.brief = QLabel(self)
        self.brief.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.brief.setWordWrap(True)
        self.brief.setProperty('role', 'description')
        self.time_label = QLabel(self)
        self.time_label.setProperty('role', 'description')
        self.time_label.setWordWrap(True)
        self.time_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.meta = QHBoxLayout()
        self.meta.addWidget(self.brief, 1)
        self.meta.addWidget(self.time_label, 1)
        layout.addLayout(self.meta)
        self.details = QWidget(self)
        detail_layout = QVBoxLayout(self.details)
        detail_layout.setContentsMargins(0, 4, 0, 0)
        self.description = QLabel(self.details)
        self.description.setWordWrap(True)
        self.description.setTextInteractionFlags(Qt.TextSelectableByMouse)
        detail_layout.addWidget(self.description)
        actions = QHBoxLayout()
        self.record = QPushButton('查看记录', self.details)
        self.record.clicked.connect(lambda: overview.records.emit(self.card.task_id))
        actions.addWidget(self.record)
        self.retry = QPushButton('重新评估本期受阻关卡', self.details)
        self.retry.clicked.connect(overview._reset_abyss)
        actions.addWidget(self.retry)
        actions.addStretch(1)
        detail_layout.addLayout(actions)
        layout.addWidget(self.details)
        self.details.hide()
        self.toggle.toggled.connect(self.details.setVisible)
        self.toggle.toggled.connect(lambda expanded: self.toggle.setIcon(
            (FluentIcon.ARROW_DOWN if expanded else FluentIcon.CHEVRON_RIGHT).icon()))
        self.update_card(card, {})

    def _primary(self):
        if self.card.manual:
            self.overview._mark(self.card.task_id, self.card.state != 'completed')
        else:
            self.overview.launch_page.emit('AutoAbyssTask')

    def update_card(self, card, live):
        self.card = card
        self.name.setText(card.title)
        self.badge.setText({'running': '运行中', 'attention': '需要处理', 'pending': '待完成',
                            'waiting': '等待中', 'completed': '已完成'}[card.state])
        if self.badge.property('state') != card.state:
            self.badge.setProperty('state', card.state)
            self.badge.style().unpolish(self.badge)
            self.badge.style().polish(self.badge)
        self.badge.setAccessibleName(f'{card.title}：{self.badge.text()}')
        stamp = self.overview._time
        next_text = ('下次可检查：' if card.task_id in ('weekly_boss', 'merge_echo') else
                    '本期预计结束：' if card.task_id == 'adversity_tower' else '下次重置：') + stamp(card.next_at) if card.next_at else ''
        time_text = ('最近完成：' + stamp(card.completed_at)) if card.completed_at else (
            '最近尝试：' + stamp(card.last_attempt_at)) if card.last_attempt_at else next_text or '尚无完成记录'
        brief = card.detail
        if card.state == 'attention':
            time_text = ('最近尝试：' + stamp(card.last_attempt_at)) if card.last_attempt_at else ''
        elif card.state == 'completed':
            time_text = '最近完成：' + stamp(card.completed_at)
        elif card.state == 'waiting' and not card.next_at:
            brief = '等待条件满足 · ' + card.detail
            time_text = ''
        if card.state == 'running':
            time_text = f'已运行 {live.get("elapsed", 0)} 秒'
        self._brief_text = brief
        self.brief.setText(brief)
        self.time_label.setText(time_text)
        self.brief.setToolTip(card.detail)
        self.primary.setVisible(card.manual or card.task_id == 'adversity_tower')
        self.primary.setText(('撤销完成' if card.state == 'completed' else '标记完成') if card.manual else '单独启动')
        self.primary.setToolTip('打开独立任务页，在该页启动' if not card.manual else self.primary.text())
        self.retry.setVisible(card.task_id == 'adversity_tower' and card.state == 'attention')
        text = card.detail + f'\n最近完成：{stamp(card.completed_at)} · 来源：{card.source}'
        if card.last_attempt_at:
            text += f'\n最近尝试结束：{stamp(card.last_attempt_at)}'
        if card.started_at:
            text += f'\n最近开始：{stamp(card.started_at)}'
        if card.next_at:
            text += '\n' + next_text
        self.description.setText(text)
        self.description.setProperty('role', 'error' if card.state == 'attention' else 'description')
        self.description.style().unpolish(self.description)
        self.description.style().polish(self.description)

    def resizeEvent(self, event):
        self.header.setDirection(QBoxLayout.TopToBottom if self.width() < 650 else QBoxLayout.LeftToRight)
        self.meta.setDirection(QBoxLayout.TopToBottom if self.width() < 580 else QBoxLayout.LeftToRight)
        super().resizeEvent(event)

    def set_writable(self, writable):
        self.primary.setEnabled(writable)
        self.retry.setEnabled(writable)
