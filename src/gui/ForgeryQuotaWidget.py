"""Two ordered additional-material goals with persistent round identities."""
from copy import deepcopy
from uuid import uuid4
from PySide6.QtCore import Signal, QTimer
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QWidget, QGridLayout, QLabel, QLineEdit, QPushButton, QInputDialog, QMessageBox
from src.gui.ChoiceControls import QtComboBox as QComboBox
from src.task.forgery_quota_plan import FORGERY_GOALS, TIERS, forgery_plan, green_units
from src.task.forgery_quota_progress import ForgeryQuotaProgress


class ForgeryQuotaWidget(QWidget):
    changed = Signal()

    def __init__(self, tasks, service=None, profile_id=None, parent=None):
        super().__init__(parent)
        from src.task.forgery_targets import FORGERY_DOMAIN_OPTIONS
        self.progress = ForgeryQuotaProgress(service, profile_id) if service and profile_id else None
        goals = forgery_plan(tasks)
        self.rows = []
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QLabel('凝素本轮还需材料 · 两组按顺序执行，完成后自动刷本账号无音区', self)
        header.setWordWrap(True)
        layout.addWidget(header, 0, 0, 1, 7)
        for index in range(2):
            goal = deepcopy(goals[index]) if index < len(goals) else {
                'goal_id': str(uuid4()), 'domain': 0, 'need': dict.fromkeys(TIERS, 0)}
            target = QComboBox(self)
            target.addItem('无（不启用目标）', 0)
            for value, name in FORGERY_DOMAIN_OPTIONS:
                target.addItem(name, value)
            target.setCurrentIndex(target.findData(goal['domain']))
            layout.addWidget(target, index * 3 + 1, 0, 1, 7)
            fields = {}
            for column, (tier, label) in enumerate(zip(TIERS, ('金', '紫', '蓝', '绿'))):
                field = QLineEdit(str(goal['need'][tier]), self)
                field.setValidator(QIntValidator(0, 999999, field))
                field.setMaximumWidth(80)
                field.setAccessibleName(f'凝素目标{index + 1}{label}色剩余需求')
                layout.addWidget(QLabel(label, self), index * 3 + 2, column * 2)
                layout.addWidget(field, index * 3 + 2, column * 2 + 1)
                fields[tier] = field
                field.textEdited.connect(self._edited)
            status = QLabel(self)
            status.setWordWrap(True)
            layout.addWidget(status, index * 3 + 3, 0, 1, 6)
            new_round = QPushButton('新一轮', self)
            new_round.setToolTip('保留需求数量，以新的轮次从零累计；保存账号后生效。')
            layout.addWidget(new_round, index * 3 + 3, 6, 1, 2)
            self.rows.append({'goal_id': goal['goal_id'], 'domain': goal['domain'],
                              'target': target, 'fields': fields, 'status': status})
            target.currentIndexChanged.connect(lambda value, index=index: self._domain_changed(index))
            new_round.clicked.connect(lambda checked=False, index=index: self._new_round(index))
        self.resolve_button = QPushButton('核对未确认的凝素领取（0 / 40 / 80体力）', self)
        self.resolve_button.clicked.connect(self._resolve)
        layout.addWidget(self.resolve_button, 7, 0, 1, 8)
        note = QLabel('金×27 + 紫×9 + 蓝×3 + 绿；80体力估算50当量，40体力估算25当量。'
                      '未设置目标时沿用旧凝素刷法。进度只按已核验消费累计，材料实际掉落可能有差异。', self)
        note.setWordWrap(True)
        layout.addWidget(note, 8, 0, 1, 8)
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def values(self):
        result = []
        for row in self.rows:
            domain = row['target'].currentData()
            if not domain:
                continue
            need = {}
            for tier, field in row['fields'].items():
                text = field.text().strip()
                if not text.isascii() or not text.isdecimal():
                    raise ValueError('凝素需求请输入0至999999整数')
                need[tier] = int(text)
            result.append(dict(goal_id=row['goal_id'], domain=domain, need=need))
        return forgery_plan({FORGERY_GOALS: result})

    def _edited(self, *_):
        self.refresh()
        self.changed.emit()

    def _new_round(self, index):
        self.rows[index]['goal_id'] = str(uuid4())
        self._edited()

    def _domain_changed(self, index):
        row = self.rows[index]
        domain = row['target'].currentData()
        if domain and row['domain'] and domain != row['domain']:
            row['goal_id'] = str(uuid4())
        if domain:
            row['domain'] = domain
        self._edited()

    def refresh(self):
        try:
            earned = self.progress.earned() if self.progress else {}
            pending = self.progress.pending() if self.progress else {}
            self.resolve_button.setVisible(bool(pending))
            goals = {g['goal_id']: g for g in self.values()}
            for row in self.rows:
                goal = goals.get(row['goal_id'])
                if goal is None:
                    row['status'].setText('未启用')
                    continue
                total = green_units(goal['need'])
                done = earned.get(row['goal_id'], 0)
                left = max(0, total - done)
                double, single = divmod(left, 50)
                single = (single + 24) // 25
                row['status'].setText(f'绿色当量 {total}，已确认 {done}，剩余 {left}；'
                                      f'预计80体力 {double} 次、40体力 {single} 次' +
                                      ('；领奖待核验' if pending else '；已完成' if not left else ''))
        except Exception as error:
            for row in self.rows:
                row['status'].setText(f'配置或领取记录待核对：{error}')

    def _resolve(self):
        from ok import og
        if getattr(getattr(og, 'executor', None), 'current_task', None) is not None:
            QMessageBox.information(self, '请先停止任务', '停止任务并核对实际体力扣除后再确认。')
            return
        try:
            for event_id, event in self.progress.pending().items():
                answer, accepted = QInputDialog.getItem(self, '核对凝素领取',
                    f'领域 {event["domain"]}，记录时间 {event["time"]}\n本次实际消耗多少体力？',
                    ['0（确认未领取）', '40', '80'], 0, False)
                if not accepted:
                    break
                self.progress.resolve(event_id, int(answer.split('（')[0]))
            self.refresh()
        except Exception as error:
            QMessageBox.warning(self, '核对失败', str(error))
