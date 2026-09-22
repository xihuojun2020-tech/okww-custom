"""Small draft-only reminder editor, independent of task configuration."""
from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtWidgets import QCheckBox, QLabel, QWidget, QGridLayout, QPlainTextEdit

from src.account_reminders import (NOTE_LIMIT, REMINDERS, get_reminder_note, get_reminders,
                                   set_reminder_note, set_reminders)
from src.gui.SectionPanel import SectionPanel


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
        self.add_widget(QLabel('备注', self))
        self.add_widget(self.note)
        self._arrange()

    def _arrange(self):
        while self.grid.count():
            self.grid.takeAt(0)
        columns = 3 if self.content.width() >= 520 else 2 if self.content.width() >= 340 else 1
        for index, checkbox in enumerate(self.choices.values()):
            self.grid.addWidget(checkbox, index // columns, index % columns)
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)

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
        self._arrange()

    def apply_account(self, account):
        result = set_reminders(account, [key for key, control in self.choices.items() if control.isChecked()])
        return set_reminder_note(result, self.note.toPlainText())
