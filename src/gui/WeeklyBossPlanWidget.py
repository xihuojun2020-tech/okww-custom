"""Three priority rows, with limits immediately to the right of each target."""
from PySide6.QtCore import Signal, QTimer
from PySide6.QtWidgets import QWidget, QGridLayout, QLabel, QLineEdit, QPushButton, QInputDialog, QMessageBox, QComboBox

from src.task.weekly_boss import WEEKLY_BOSSES, WEEKLY_AUTO, WEEKLY_DISABLED
from src.task.weekly_boss_plan import WEEKLY_PLAN, weekly_plan, choose_weekly_target
from src.task.weekly_boss_progress import WeeklyBossProgress


class WeeklyBossPlanWidget(QWidget):
    changed = Signal()

    def __init__(self, tasks, service=None, profile_id=None, parent=None):
        super().__init__(parent)
        self.progress = WeeklyBossProgress(service, profile_id) if service and profile_id else None
        self.rows = []
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        names = {b.key: b.name for b in WEEKLY_BOSSES}
        for index, row in enumerate(weekly_plan(tasks)):
            target = QComboBox(self)
            for key in (WEEKLY_DISABLED, WEEKLY_AUTO, *names):
                target.addItem(names.get(key, key), key)
            target.setCurrentIndex(target.findData(row['boss']))
            limit = QLineEdit('不限' if row['limit'] == -1 else str(row['limit']), self)
            limit.setMaximumWidth(85)
            limit.setAccessibleName(f'优先级{index + 1}领取次数上限')
            limit.setToolTip('跨周累计目标，0跳过；不限会持续优先领取此目标。')
            label = QLabel(self)
            label.setWordWrap(True)
            correct = QPushButton('校正', self)
            correct.setToolTip('录入已知累计次数；请先停止运行中的任务。')
            layout.addWidget(QLabel(f'{index + 1}', self), index, 0)
            layout.addWidget(target, index, 1)
            layout.addWidget(limit, index, 2)
            layout.addWidget(QLabel('次', self), index, 3)
            layout.addWidget(label, index, 4)
            layout.addWidget(correct, index, 5)
            self.rows.append((target, limit, label))
            target.currentIndexChanged.connect(self._edited)
            limit.textEdited.connect(self._edited)
            correct.setEnabled(self.progress is not None)
            correct.clicked.connect(lambda checked=False, target=target: self._correct(target))
        layout.setColumnStretch(1, 2)
        layout.setColumnStretch(4, 1)
        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary, 3, 0, 1, 6)
        self.resolve_button = QPushButton('核对未确认领取', self)
        self.resolve_button.clicked.connect(self._resolve)
        layout.addWidget(self.resolve_button, 4, 0, 1, 6)
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def values(self):
        rows = []
        for target, limit, _ in self.rows:
            text = limit.text().strip()
            if text != '不限' and not text.isascii():
                raise ValueError('周本次数请输入整数，或填写“不限”')
            try:
                count = -1 if text == '不限' else int(text)
            except ValueError:
                raise ValueError('周本次数请输入0至9999整数，或填写“不限”') from None
            rows.append({'boss': target.currentData(), 'limit': count})
        return weekly_plan({WEEKLY_PLAN: rows})

    def _edited(self, *_):
        self.refresh()
        self.changed.emit()

    def refresh(self):
        try:
            counts = self.progress.counts() if self.progress else {}
            rows = self.values()
            choice = choose_weekly_target(rows, counts)
            for row, (_, _, label) in zip(rows, self.rows):
                count = counts.get(row['boss'], 0)
                cap = '不限' if row['limit'] == -1 else str(row['limit'])
                status = ('关闭' if row['boss'] == WEEKLY_DISABLED or row['limit'] == 0 else
                          '已达标' if row['limit'] > 0 and count >= row['limit'] else '待领取')
                label.setText(f'已领 {count}/{cap} · {status}')
            self.summary.setText('计划未启用' if choice is None else
                '全部目标已达标，后续领取游戏周本列表第一项' if choice[2] == '游戏列表首项保底' else
                '累计次数跨周保留；按1→2→3领取，全部达标后领取游戏列表第一项。')
            self.resolve_button.setVisible(bool(self.progress and self.progress.pending()))
        except Exception as error:
            self.summary.setText(f'周本配置或进度待核对：{error}')
            self.resolve_button.setVisible(False)

    def _editable_progress(self):
        from ok import og
        if getattr(getattr(og, 'executor', None), 'current_task', None) is not None:
            QMessageBox.information(self, '请先停止任务', '停止当前任务后再校正或核对领取记录。')
            return False
        return self.progress is not None

    def _correct(self, target):
        if not self._editable_progress() or target.currentData() in (WEEKLY_AUTO, WEEKLY_DISABLED):
            return
        try:
            boss = target.currentData()
            current = self.progress.counts().get(boss, 0)
            count, ok = QInputDialog.getInt(self, '校正累计领取',
                f'{target.currentText()}：累计实际领取次数（跨周保留）', current, 0, 999999)
            if ok:
                self.progress.correct(boss, count)
                self.refresh()
        except Exception as error:
            QMessageBox.warning(self, '校正失败', str(error))

    def _resolve(self):
        if not self._editable_progress():
            return
        try:
            names = {b.key: b.name for b in WEEKLY_BOSSES}
            for event_id, event in self.progress.pending().items():
                answer = QMessageBox.question(self, '核对未确认领取',
                    f'{names[event["boss"]]}\n记录时间：{event["time"]}\n'
                    '这次是否已实际领取奖励？\n是：计入1次；否：确认未领取；取消：保持待核验。',
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Cancel)
                if answer == QMessageBox.Cancel:
                    break
                self.progress.resolve(event_id, answer == QMessageBox.Yes)
            self.refresh()
        except Exception as error:
            QMessageBox.warning(self, '核对失败', str(error))
