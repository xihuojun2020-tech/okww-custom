from qfluentwidgets import FluentIcon
from ok.gui.widget.CustomTab import CustomTab
from ok.gui.tasks.OneTimeTaskTab import OneTimeTaskTab
from src.gui.navigation_sections import TASKS
from src.gui.SectionPanel import SectionPanel


class TaskHubTab(CustomTab):
    def __init__(self):
        super().__init__()
        self.task_tab = OneTimeTaskTab(section=TASKS)
        self.section_panels = [SectionPanel("每日任务", "每日任务、多账号每日任务及其他任务均在此直接展开。", self.view)]
        self.section_panels[0].add_embedded_widget(self.task_tab, stretch=1)
        self.add_widget(self.section_panels[0], stretch=1)

    @property
    def name(self): return "任务"

    @property
    def icon(self): return FluentIcon.BOOK_SHELF
