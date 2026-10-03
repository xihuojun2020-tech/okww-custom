"""Finite lifetime world-boss claim goals in the account stamina section."""
from PySide6.QtCore import Signal, QTimer
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (QWidget, QGridLayout, QLabel, QLineEdit, QPushButton,
                               QInputDialog, QMessageBox)
from src.gui.ChoiceControls import QtComboBox as QComboBox
from src.task.world_boss_materials import TARGETS_BY_ID
from src.task.world_boss_material_plan import MATERIAL_TARGETS, material_plan, choose_material_target
from src.task.world_boss_material_progress import WorldBossMaterialProgress


class WorldBossMaterialPlanWidget(QWidget):
    changed = Signal()

    def __init__(self, tasks, service=None, profile_id=None, parent=None):
        super().__init__(parent)
        self.progress = WorldBossMaterialProgress(service, profile_id) if service and profile_id else None
        self.fallback = tasks.get('Which to Farm', 'Tacet Suppression')
        self.planner_enabled = tasks.get('Material Planner Enabled', False)
        self.rows = []
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.addWidget(QLabel('世界首领突破材料 · 优先级与累计领取上限', self), 0, 0, 1, 6)
        for index, row in enumerate(material_plan(tasks)):
            target = QComboBox(self)
            target.addItem('无', 'none')
            for key, boss in TARGETS_BY_ID.items():
                target.addItem(boss.name, key)
            target.setCurrentIndex(target.findData(row['boss']))
            target.setAccessibleName(f'首领材料优先级{index + 1}目标')
            limit = QLineEdit(str(row['limit']), self)
            limit.setValidator(QIntValidator(0, 9999, limit))
            limit.setMaximumWidth(85)
            limit.setAccessibleName(f'首领材料优先级{index + 1}累计领取上限')
            limit.setToolTip('0至9999；0跳过。跨日跨周累计，只计算成功领取次数。')
            label = QLabel(self)
            label.setWordWrap(True)
            correct = QPushButton('校正', self)
            correct.setEnabled(self.progress is not None)
            correct.setToolTip('停止任务并核对待确认记录后，校正实际累计次数。')
            for column, widget in enumerate((QLabel(str(index + 1), self), target, limit,
                                            QLabel('次', self), label, correct)):
                layout.addWidget(widget, index + 1, column)
            self.rows.append((target, limit, label))
            target.currentIndexChanged.connect(self._edited)
            limit.textEdited.connect(self._edited)
            correct.clicked.connect(lambda checked=False, target=target: self._correct(target))
        layout.setColumnStretch(1, 2)
        layout.setColumnStretch(4, 1)
        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary, 4, 0, 1, 6)
        self.resolve_button = QPushButton('核对未确认的材料领取', self)
        self.resolve_button.clicked.connect(self._resolve)
        layout.addWidget(self.resolve_button, 5, 0, 1, 6)
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def set_fallback(self, target, planner_enabled=False):
        self.fallback, self.planner_enabled = target, planner_enabled
        self.refresh()

    def values(self):
        rows = []
        for target, limit, _ in self.rows:
            text = limit.text().strip()
            if not text.isascii() or not text.isdecimal():
                raise ValueError('首领材料次数请输入0至9999整数')
            rows.append({'boss': target.currentData(), 'limit': int(text)})
        return material_plan({MATERIAL_TARGETS: rows})

    def _edited(self, *_):
        self.refresh()
        self.changed.emit()

    def refresh(self):
        try:
            pending = bool(self.progress and self.progress.pending())
            self.resolve_button.setVisible(pending)
            counts = self.progress.counts() if self.progress else {}
            rows = self.values()
            for row, (_, _, label) in zip(rows, self.rows):
                count = counts.get(row['boss'], 0)
                status = ('关闭' if row['boss'] == 'none' or row['limit'] == 0 else
                          '已达标' if count >= row['limit'] else '待领取')
                label.setText(f'已领 {count}/{row["limit"]} · {status}')
            names = {'Tacet Suppression': '无音区', 'Forgery Challenge': '凝素领域',
                     'Simulation Challenge': '模拟训练'}
            fallback = '材料规划' if self.planner_enabled else names.get(self.fallback, str(self.fallback))
            choice = choose_material_target(rows, counts)
            status = (f'下一目标：{TARGETS_BY_ID[choice[0]].name}，还需 {choice[1]} 次。' if choice else
                      '全部启用目标已达标。' if any(r['boss'] != 'none' and r['limit'] > 0 for r in rows) else
                      '首领材料计划未启用。')
            self.summary.setText(('有材料领奖待核验，核对前暂停该账号体力消费。' if pending else status) +
                                 f'\n累计跨日跨周保留；达标后跟随账号的{fallback}安排。')
        except Exception as error:
            self.summary.setText(f'首领材料配置或进度待核对：{error}')

    def _editable_progress(self):
        from ok import og
        if getattr(getattr(og, 'executor', None), 'current_task', None) is not None:
            QMessageBox.information(self, '请先停止任务', '停止当前任务后再校正或核对领取记录。')
            return False
        return self.progress is not None

    def _correct(self, target):
        if not self._editable_progress() or target.currentData() == 'none':
            return
        try:
            if self.progress.pending():
                raise ValueError('请先核对未确认的材料领取')
            boss = target.currentData()
            count, ok = QInputDialog.getInt(self, '校正累计领取',
                f'{target.currentText()}：实际累计领取次数（跨日跨周保留）',
                self.progress.counts().get(boss, 0), 0, 999999)
            if ok:
                self.progress.correct(boss, count)
                self.refresh()
        except Exception as error:
            QMessageBox.warning(self, '校正失败', str(error))

    def _resolve(self):
        if not self._editable_progress():
            return
        try:
            for event_id, event in self.progress.pending().items():
                answer = QMessageBox.question(self, '核对未确认材料领取',
                    f'{TARGETS_BY_ID[event["boss"]].name}\n记录时间：{event["time"]}\n'
                    '这次是否已实际领取奖励？\n是：计入1次；否：确认未领取；取消：保持待核验。',
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Cancel)
                if answer == QMessageBox.Cancel:
                    break
                self.progress.resolve(event_id, answer == QMessageBox.Yes)
            self.refresh()
        except Exception as error:
            QMessageBox.warning(self, '核对失败', str(error))
