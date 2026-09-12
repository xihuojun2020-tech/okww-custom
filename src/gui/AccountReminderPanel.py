"""Small draft-only reminder editor, independent of task configuration."""
from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtWidgets import QCheckBox, QLabel, QWidget, QGridLayout

from src.account_reminders import REMINDERS, get_reminders, set_reminders
from src.gui.SectionPanel import SectionPanel
from src.evidence.model import GROUPS, project_group
from src.activity_catalog import LEGACY_ACTIVITIES


class AccountReminderPanel(SectionPanel):
    edited = Signal()

    def __init__(self, parent=None):
        super().__init__('待办提醒', '仅作提醒，不改变自动任务流程。', parent, collapsible=True)
        self.choices = {}
        self.groups = {}
        for group, title in GROUPS.items():
            label = QLabel(title, self)
            self.add_widget(label)
            host = QWidget(self)
            grid = QGridLayout(host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(4)
            self.add_widget(host)
            self.groups[group] = (label, host, grid)
        for key, title in REMINDERS.items():
            checkbox = QCheckBox(title, self)
            checkbox.toggled.connect(self._changed)
            self.choices[key] = checkbox
        self._legacy = set()
        self._arrange()

    def _arrange(self):
        for group, (label, host, grid) in self.groups.items():
            while grid.count():
                grid.takeAt(0)
            keys = [key for key in self.choices if project_group(key) == group
                    and (key not in LEGACY_ACTIVITIES or key in self._legacy)]
            label.setVisible(bool(keys))
            host.setVisible(bool(keys))
            needed = max((self.choices[key].sizeHint().width() for key in keys), default=0) * 2 + 8
            columns = 2 if self.content.width() >= needed else 1
            for key, checkbox in self.choices.items():
                if project_group(key) == group:
                    checkbox.setVisible(key in keys)
            for index, key in enumerate(keys):
                grid.addWidget(self.choices[key], index // columns, index % columns)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, int(columns == 2))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange()

    def _changed(self, *_):
        selected = [REMINDERS[key] for key, control in self.choices.items() if control.isChecked()]
        self.set_summary('、'.join(selected) if selected else '未设置')
        self.edited.emit()

    def load_account(self, account):
        values = get_reminders(account)
        self._legacy = set(values) & LEGACY_ACTIVITIES.keys()
        for key, control in self.choices.items():
            with QSignalBlocker(control):
                control.setChecked(key in values)
        with QSignalBlocker(self):
            self._changed()
        self._arrange()

    def apply_account(self, account):
        return set_reminders(account, [key for key, control in self.choices.items() if control.isChecked()])
