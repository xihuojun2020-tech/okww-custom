"""Two ordered additional-material goals with persistent round identities."""
from copy import deepcopy
from uuid import uuid4
from PySide6.QtCore import Signal, QTimer, QSignalBlocker
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QWidget, QGridLayout, QLabel, QLineEdit, QPushButton, QInputDialog, QMessageBox, QVBoxLayout
from src.gui.ChoiceControls import QtComboBox as QComboBox
from src.task.forgery_quota_plan import FORGERY_GOALS, FORGERY_MODE, TIERS, forgery_plan, green_units, goal_units, claim_estimate
from src.task.forgery_quota_progress import ForgeryQuotaProgress


class ForgeryQuotaWidget(QWidget):
    changed = Signal()

    def __init__(self, tasks, service=None, profile_id=None, parent=None):
        super().__init__(parent)
        from src.task.forgery_targets import FORGERY_DOMAIN_OPTIONS
        self.progress = ForgeryQuotaProgress(service, profile_id) if service and profile_id else None
        goals = forgery_plan(tasks)
        self.rows = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        from src.gui.FlatSettingRow import FlatSettingRow
        self.mode = QComboBox(self)
        self.mode.addItem('不限', 'unlimited')
        self.mode.addItem('按材料需求', 'materials')
        self.mode.setCurrentIndex(self.mode.findData(tasks.get(FORGERY_MODE) or ('materials' if goals else 'unlimited')))
        outer.addWidget(FlatSettingRow('凝素上限', self.mode, parent=self))
        self.goal_host = QWidget(self)
        outer.addWidget(self.goal_host)
        layout = QGridLayout(self.goal_host)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QLabel('输入已有材料与目标所需，程序计算缺口；两组达标后刷本账号无音区。', self)
        header.setWordWrap(True)
        layout.addWidget(header, 0, 0, 1, 8)
        for index in range(2):
            goal = deepcopy(goals[index]) if index < len(goals) else {
                'goal_id': str(uuid4()), 'domain': 0, 'need': dict.fromkeys(TIERS, 0), 'inventory': dict.fromkeys(TIERS, 0)}
            target = QComboBox(self)
            target.addItem('无（不启用目标）', 0)
            for value, name in FORGERY_DOMAIN_OPTIONS:
                target.addItem(name, value)
            target.setCurrentIndex(target.findData(goal['domain']))
            base = index * 7 + 1
            layout.addWidget(target, base, 0, 1, 8)
            layout.addWidget(QLabel('已有材料', self), base + 1, 0, 1, 8)
            inventory_fields = {}
            for column, (tier, label) in enumerate(zip(TIERS, ('金', '紫', '蓝', '绿'))):
                field = QLineEdit(str(goal.get('inventory', {}).get(tier, 0)), self)
                field.setValidator(QIntValidator(0, 999999, field))
                field.setMinimumWidth(40)
                field.setAccessibleName(f'凝素目标{index + 1}已有{label}色材料')
                layout.addWidget(QLabel(label, self), base + 2, column * 2)
                layout.addWidget(field, base + 2, column * 2 + 1)
                inventory_fields[tier] = field
                field.textEdited.connect(lambda *_, index=index: self._inventory_changed(index))
            need_label = QLabel('目标所需' if 'inventory' in goal else '旧配置：剩余需求（重新录入库存后切换）', self)
            need_label.setWordWrap(True)
            layout.addWidget(need_label, base + 3, 0, 1, 8)
            fields = {}
            for column, (tier, label) in enumerate(zip(TIERS, ('金', '紫', '蓝', '绿'))):
                field = QLineEdit(str(goal['need'][tier]), self)
                field.setValidator(QIntValidator(0, 999999, field))
                field.setMinimumWidth(40)
                field.setAccessibleName(f'凝素目标{index + 1}所需{label}色材料')
                layout.addWidget(QLabel(label, self), base + 4, column * 2)
                layout.addWidget(field, base + 4, column * 2 + 1)
                fields[tier] = field
                field.textEdited.connect(self._edited)
            status = QLabel(self)
            status.setWordWrap(True)
            status.setProperty('role', 'description')
            layout.addWidget(status, base + 5, 0, 1, 8)
            new_round = QPushButton('按当前库存重新计算', self)
            new_round.setToolTip('请填写背包现有材料和目标所需；建立新基准，旧流水保留，保存账号后生效。')
            layout.addWidget(new_round, base + 6, 0, 1, 8)
            self.rows.append({'goal_id': goal['goal_id'], 'domain': goal['domain'],
                              'target': target, 'fields': fields, 'status': status, 'inventory_fields': inventory_fields,
                              'snapshot': 'inventory' in goal, 'inventory_dirty': False, 'need_label': need_label})
            target.currentIndexChanged.connect(lambda value, index=index: self._domain_changed(index))
            new_round.clicked.connect(lambda checked=False, index=index: self._new_round(index))
        self.resolve_button = QPushButton('核对未确认的凝素领取（0 / 40 / 80体力）', self)
        self.resolve_button.clicked.connect(self._resolve)
        outer.addWidget(self.resolve_button)
        note = QLabel('金×27 + 紫×9 + 蓝×3 + 绿；80体力估算50当量，40体力估算25当量。'
                      '已有与所需均按上述比例折算。进度按已核验消费估算，库存不会被估算值自动覆盖。', self)
        note.setWordWrap(True)
        layout.addWidget(note, 15, 0, 1, 8)
        self.mode.currentIndexChanged.connect(self._edited)
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def values(self, *, preview=False, farm_kind='Forgery Challenge'):
        result = []
        for row in self.rows:
            domain = row['target'].currentData()
            if not domain:
                continue
            def quantities(fields):
                values = {}
                for tier, field in fields.items():
                    text = field.text().strip()
                    if not text.isascii() or not text.isdecimal():
                        raise ValueError('材料数量请输入0至999999整数')
                    values[tier] = int(text)
                return values
            if row['inventory_dirty'] and not preview:
                raise ValueError('库存已修改，请点击“按当前库存重新计算”，再保存账号')
            goal = dict(goal_id=row['goal_id'], domain=domain, need=quantities(row['fields']))
            if row['snapshot'] or (preview and row['inventory_dirty']):
                goal['inventory'] = quantities(row['inventory_fields'])
            result.append(goal)
        return forgery_plan({FORGERY_GOALS: result, FORGERY_MODE: self.mode.currentData(),
                             'Which to Farm': farm_kind})

    def _edited(self, *_):
        self.refresh()
        self.changed.emit()

    def _new_round(self, index):
        if self.progress and self.progress.pending():
            QMessageBox.warning(self, '请先核对', '存在未确认领奖，请核对后再重建库存基准。')
            return
        self.rows[index]['goal_id'] = str(uuid4())
        self.rows[index].update(snapshot=True, inventory_dirty=False)
        self.rows[index]['need_label'].setText('目标所需')
        self._edited()

    def _inventory_changed(self, index):
        self.rows[index]['inventory_dirty'] = True
        self._edited()

    def _domain_changed(self, index):
        row = self.rows[index]
        domain = row['target'].currentData()
        if domain and row['domain'] and domain != row['domain']:
            if self.progress and self.progress.pending():
                with QSignalBlocker(row['target']):
                    row['target'].setCurrentIndex(row['target'].findData(row['domain']))
                QMessageBox.warning(self, '请先核对', '存在未确认领奖，请核对后再更换领域。')
                return
            self._new_round(index)
        if domain:
            row['domain'] = domain
        self._edited()

    def refresh(self):
        self.goal_host.setVisible(self.mode.currentData() == 'materials')
        try:
            earned = self.progress.earned() if self.progress else {}
            pending = self.progress.pending() if self.progress else {}
            self.resolve_button.setVisible(bool(pending))
            goals = {g['goal_id']: g for g in self.values(preview=True)}
            for row in self.rows:
                goal = goals.get(row['goal_id'])
                if goal is None:
                    row['status'].setText('未启用')
                    continue
                total = goal_units(goal)
                done = 0 if row['inventory_dirty'] else earned.get(row['goal_id'], 0)
                left = max(0, total - done)
                double, single, cost = claim_estimate(left)
                base = (f'已有 {green_units(goal["inventory"])}，所需 {green_units(goal["need"])}，初始缺口 {total}；'
                        if 'inventory' in goal else f'旧剩余需求 {total}；')
                row['status'].setText(base + f'已确认新增 {done}，尚缺 {left}；'
                                      f'预计80体力 {double} 次、40体力 {single} 次，共 {cost} 体力' +
                                      ('；库存修改待重新计算' if row['inventory_dirty'] else '') +
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
