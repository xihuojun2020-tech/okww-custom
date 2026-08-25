from qfluentwidgets import FluentIcon
from ok.gui.widget.CustomTab import CustomTab
from ok.gui.tasks.OneTimeTaskTab import OneTimeTaskTab
from src.gui.navigation_sections import TASKS


class TaskHubTab(CustomTab):
    def __init__(self):
        super().__init__()
        self.task_tab = OneTimeTaskTab(section=TASKS)
        self.add_widget(self.task_tab, stretch=1)

    @property
    def name(self): return "任务"

    @property
    def icon(self): return FluentIcon.BOOK_SHELF
