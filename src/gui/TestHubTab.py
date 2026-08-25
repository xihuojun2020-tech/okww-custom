from qfluentwidgets import FluentIcon
from ok.gui.widget.CustomTab import CustomTab
from ok.gui.tasks.OneTimeTaskTab import OneTimeTaskTab
from src.gui.navigation_sections import TESTS


class TestHubTab(CustomTab):
    def __init__(self):
        super().__init__()
        self.task_tab = OneTimeTaskTab(section=TESTS)
        self.add_widget(self.task_tab, stretch=1)

    @property
    def name(self): return "测试功能"

    @property
    def icon(self): return FluentIcon.DEVELOPER_TOOLS
