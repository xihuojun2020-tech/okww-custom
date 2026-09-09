from qfluentwidgets import FluentIcon
from ok.gui.widget.CustomTab import CustomTab
from ok.gui.tasks.OneTimeTaskTab import OneTimeTaskTab
from src.gui.navigation_sections import TASKS
from src.gui.SectionPanel import SectionPanel


class TaskHubTab(CustomTab):
    def __init__(self):
        super().__init__()
        self.task_tab = OneTimeTaskTab(section=TASKS, group_tasks=True)
        self.section_panels = [SectionPanel("任务", "选择任务后开始执行。各账号的每日计划在账号页编辑；实验功能位于工具页。", self.view)]
        self.section_panels[0].add_embedded_widget(self.task_tab)
        self.section_panels[0].title_label.setProperty('role', 'pageTitle')
        self.add_widget(self.section_panels[0])

    @property
    def name(self): return "任务"

    @property
    def icon(self): return FluentIcon.BOOK_SHELF
