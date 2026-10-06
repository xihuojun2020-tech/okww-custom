"""Small draft-only reminder editor, independent of task configuration."""
from PySide6.QtCore import Signal, QSignalBlocker, QDateTime
from PySide6.QtWidgets import QCheckBox, QLabel, QWidget, QGridLayout, QPlainTextEdit, QDateTimeEdit

from src.account_reminders import (NOTE_LIMIT, REMINDERS, get_reminder_note, get_reminders,
                                   set_reminder_note, set_reminders)
from src.gui.SectionPanel import SectionPanel
from src.account_reminders import TASK_REMINDERS, REMINDER_STATES, get_task_reminders, set_task_reminders, manual_reminder_state, reminder_period
from src.gui.ChoiceControls import QtComboBox


class AccountReminderPanel(SectionPanel):
    edited = Signal()

    def __init__(self, parent=None):
        super().__init__('待办提醒', '仅作提醒，不改变自动任务流程。', parent, collapsible=True)
        self.choices = {}
        self.host = QWidget(self)
        self.grid = QGridLayout(self.host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(4)
        self.add_widget(self.host)
        for key, title in REMINDERS.items():
            checkbox = QCheckBox(title, self)
            checkbox.toggled.connect(self._changed)
            self.choices[key] = checkbox
        self.note = QPlainTextEdit(self)
        self.note.setPlaceholderText('可填写该账号需要留意的事项')
        self.note.setMaximumHeight(90)
        self.note.textChanged.connect(self._note_changed)
        self.note_label = QLabel('备注', self)
        self.add_widget(self.note_label)
        self.add_widget(self.note)
        help_label = QLabel('具体任务提醒（勾选仅展示；深塔单独启动，其他项目手动标记）', self)
        help_label.setWordWrap(True)
        help_label.setProperty('role', 'description')
        self.add_widget(help_label)
        self.task_host = QWidget(self)
        task_grid = QGridLayout(self.task_host)
        self.task_grid = task_grid
        task_grid.setContentsMargins(0, 0, 0, 0)
        self.task_choices = {}
        for index, (key, title) in enumerate(TASK_REMINDERS.items()):
            box = QCheckBox(title, self)
            rule = QtComboBox(self)
            for option, label in REMINDER_STATES.items():
                rule.addItem(label, option)
            rule.setMinimumWidth(max(rule.fontMetrics().horizontalAdvance(label)
                                     for label in REMINDER_STATES.values()) + 48)
            date = QDateTimeEdit(QDateTime.currentDateTime().addDays(1), self)
            date.setDisplayFormat('yyyy-MM-dd HH:mm')
            date.setCalendarPopup(True)
            rule.setEnabled(True)
            def changed(*_, rule=rule, date=date):
                date.hide()
                self.edited.emit()
            rule.currentIndexChanged.connect(changed)
            box.toggled.connect(self.edited)
            date.dateTimeChanged.connect(self.edited)
            date.hide()
            task_grid.addWidget(box, index, 0)
            task_grid.addWidget(rule, index, 1)
            self.task_choices[key] = (box, rule, date)
        task_grid.setColumnStretch(0, 1)
        self.add_widget(self.task_host)
        self.deep_settings = QWidget(self)
        deep_grid = QGridLayout(self.deep_settings)
        deep_grid.setContentsMargins(0, 0, 0, 0)
        self.deep_priority = QtComboBox(self)
        for value in ('两侧塔优先', '中间塔优先'):
            self.deep_priority.addItem(value, value)
        self.deep_priority.currentIndexChanged.connect(self.edited)
        from src.gui.FlatSettingRow import FlatSettingRow
        deep_grid.addWidget(FlatSettingRow('深塔挑战顺序', self.deep_priority, '单独启动时生效', self), 0, 0, 1, 2)
        self.deep_towers = {}
        for index, title in enumerate(('残响之塔', '深境之塔', '回音之塔'), 1):
            box = QCheckBox(title, self)
            box.setChecked(True)
            box.toggled.connect(self.edited)
            deep_grid.addWidget(box, index, 0, 1, 2)
            self.deep_towers[title] = box
        self.add_widget(self.deep_settings)
        self.deep_settings.hide()
        self._arrange()

    def _arrange(self):
        while self.grid.count():
            self.grid.takeAt(0)
        columns = 3 if self.content.width() >= 520 else 2 if self.content.width() >= 340 else 1
        for index, checkbox in enumerate(self.choices.values()):
            self.grid.addWidget(checkbox, index // columns, index % columns)
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)
        narrow = self.content.width() < 600
        if narrow != getattr(self, '_task_narrow', None):
            self._task_narrow = narrow
            while self.task_grid.count():
                self.task_grid.takeAt(0)
            for index, (box, rule, date) in enumerate(self.task_choices.values()):
                if narrow:
                    self.task_grid.addWidget(box, index * 2, 0, 1, 3)
                    self.task_grid.addWidget(rule, index * 2 + 1, 0, 1, 3)
                else:
                    self.task_grid.addWidget(box, index, 0)
                    self.task_grid.addWidget(rule, index, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange()

    def _changed(self, *_):
        selected = [REMINDERS[key] for key, control in self.choices.items() if control.isChecked()]
        suffix = ' · 已填写备注' if self.note.toPlainText().strip() else ''
        self.set_summary(('、'.join(selected) if selected else '未设置') + suffix)
        self.edited.emit()

    def _note_changed(self):
        text = self.note.toPlainText()
        if len(text) > NOTE_LIMIT:
            cursor = self.note.textCursor()
            self.note.blockSignals(True)
            self.note.setPlainText(text[:NOTE_LIMIT])
            cursor.movePosition(cursor.MoveOperation.End)
            self.note.setTextCursor(cursor)
            self.note.blockSignals(False)
        self._changed()

    def load_account(self, account):
        values = get_reminders(account)
        for key, control in self.choices.items():
            with QSignalBlocker(control):
                control.setChecked(key in values)
        with QSignalBlocker(self.note):
            self.note.setPlainText(get_reminder_note(account))
        with QSignalBlocker(self):
            self._changed()
            rows = get_task_reminders(account)
            self._loaded_task_rows = rows
            provider = getattr(self, 'record_provider', lambda _: {})
            marks = provider(account.get('profile_id'))
            self._loaded_statuses = {}
            deep = rows.get('adversity_tower', {})
            with QSignalBlocker(self.deep_priority):
                self.deep_priority.setCurrentIndex(max(0, self.deep_priority.findData(deep.get('priority', '两侧塔优先'))))
            for title, box in self.deep_towers.items():
                with QSignalBlocker(box):
                    box.setChecked(title in deep.get('towers', list(self.deep_towers)))
            for key, (box, rule, date) in self.task_choices.items():
                row = rows.get(key, {'enabled': False, 'rule': 'none'})
                state = manual_reminder_state(row, marks.get(key, {}))
                self._loaded_statuses[key] = state
                with QSignalBlocker(box), QSignalBlocker(rule), QSignalBlocker(date):
                    box.setChecked(row['enabled'])
                    rule.setCurrentIndex(max(0, rule.findData(state)))
                    if row.get('reset_at'):
                        from src.game_period import beijing_now
                        date.setDateTime(QDateTime(beijing_now(row['reset_at']).replace(tzinfo=None)))
                    date.hide()
        self._arrange()

    def apply_account(self, account):
        result = set_reminders(account, [key for key, control in self.choices.items() if control.isChecked()])
        result = set_reminder_note(result, self.note.toPlainText())
        rows = {}
        for key, (box, rule, date) in self.task_choices.items():
            if box.isChecked() or key in getattr(self, '_loaded_task_rows', {}):
                from copy import deepcopy
                row = deepcopy(getattr(self, '_loaded_task_rows', {}).get(key, {'rule': 'none'}))
                row['enabled'] = box.isChecked()
                state = rule.currentData()
                if state != getattr(self, '_loaded_statuses', {}).get(key, 'pending'):
                    from src.game_period import beijing_now
                    row.update(status=state, marked_at=beijing_now().isoformat(timespec='microseconds'),
                               period_id=reminder_period(row))
                rows[key] = row
        return set_task_reminders(result, rows)
