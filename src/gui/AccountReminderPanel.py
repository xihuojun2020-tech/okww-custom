"""Small draft-only reminder editor, independent of task configuration."""
from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtWidgets import QCheckBox

from src.account_reminders import REMINDERS, get_reminders, set_reminders
from src.gui.SectionPanel import SectionPanel


class AccountReminderPanel(SectionPanel):
    edited = Signal()

    def __init__(self, parent=None):
        super().__init__('待办提醒', '仅作提醒，不改变自动任务流程。', parent, collapsible=True)
        self.choices = {}
        for key, title in REMINDERS.items():
            checkbox = QCheckBox(title, self)
            checkbox.toggled.connect(self._changed)
            self.add_widget(checkbox)
            self.choices[key] = checkbox

    def _changed(self, *_):
        selected = [REMINDERS[key] for key, control in self.choices.items() if control.isChecked()]
        self.set_summary('、'.join(selected) if selected else '未设置')
        self.edited.emit()

    def load_account(self, account):
        values = get_reminders(account)
        for key, control in self.choices.items():
            with QSignalBlocker(control):
                control.setChecked(key in values)
        with QSignalBlocker(self):
            self._changed()

    def apply_account(self, account):
        return set_reminders(account, [key for key, control in self.choices.items() if control.isChecked()])
