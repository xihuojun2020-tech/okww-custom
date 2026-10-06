"""Stable compact task row with on-demand provenance and history."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QBoxLayout, QLabel, QPushButton, QToolButton


class TaskOverviewRow(QWidget):
    def __init__(self, overview, card):
        super().__init__(overview.host)
        self.overview, self.card = overview, card
        self.setObjectName('accountTaskRow')
        self.setAttribute(Qt.WA_StyledBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(2)
        self.header = QHBoxLayout()
        self.name = QLabel(self)
        self.name.setProperty('role', 'sectionTitle')
        self.name.setWordWrap(True)
        self.header.addWidget(self.name, 1)
        self.primary = QPushButton(self)
        self.primary.clicked.connect(self._primary)
        self.header.addWidget(self.primary)
        self.settings = QPushButton('设置', self)
        self.settings.clicked.connect(lambda: overview.navigate.emit(self.card.route))
        self.header.addWidget(self.settings)
        self.toggle = QToolButton(self)
        self.toggle.setText('详情')
        self.toggle.setCheckable(True)
        self.toggle.setAccessibleName(f'{card.title}：展开详情与记录')
        self.header.addWidget(self.toggle)
        layout.addLayout(self.header)
        self.brief = QLabel(self)
        from PySide6.QtWidgets import QSizePolicy
        self.brief.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.brief.setProperty('role', 'description')
        self.time_label = QLabel(self)
        self.time_label.setProperty('role', 'description')
        self.meta = QHBoxLayout()
        self.meta.addWidget(self.brief, 1)
        self.meta.addWidget(self.time_label)
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
        self.update_card(card, {})

    def _primary(self):
        if self.card.manual:
            self.overview._mark(self.card.task_id, self.card.state != 'completed')
        else:
            self.overview.launch_page.emit('AutoAbyssTask')

    def update_card(self, card, live):
        self.card = card
        self.name.setText(card.title)
        stamp = self.overview._time
        time_text = ('下次可检查：' if card.task_id in ('weekly_boss', 'merge_echo') else
                 '本期预计结束：' if card.task_id == 'adversity_tower' else '下次重置：') + stamp(card.next_at) if card.next_at else card.detail
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
        self._elide_brief()
        self.time_label.setText(time_text if card.next_at or card.state in ('completed', 'running', 'attention') else '')
        self.brief.setToolTip(card.detail)
        self.primary.setVisible(card.manual or card.task_id == 'adversity_tower')
        self.primary.setText(('撤销完成' if card.state == 'completed' else '标记完成') if card.manual else '前往任务')
        self.retry.setVisible(card.task_id == 'adversity_tower' and card.state == 'attention')
        text = card.detail + f'\n最近完成：{stamp(card.completed_at)} · 来源：{card.source}'
        if card.last_attempt_at:
            text += f'\n最近尝试结束：{stamp(card.last_attempt_at)}'
        if card.started_at:
            text += f'\n最近开始：{stamp(card.started_at)}'
        if card.next_at:
            text += '\n' + time_text
        self.description.setText(text)
        self.description.setProperty('role', 'error' if card.state == 'attention' else 'description')
        self.description.style().unpolish(self.description)
        self.description.style().polish(self.description)

    def _elide_brief(self):
        self.brief.setText(self.brief.fontMetrics().elidedText(getattr(self, '_brief_text', ''), Qt.ElideRight,
                                                             max(1, self.brief.width())))

    def resizeEvent(self, event):
        self.meta.setDirection(QBoxLayout.TopToBottom if self.width() < 580 else QBoxLayout.LeftToRight)
        self._elide_brief()
        super().resizeEvent(event)

    def set_writable(self, writable):
        self.primary.setEnabled(writable)
        self.retry.setEnabled(writable)
