from qfluentwidgets import FluentIcon
from ok.gui.widget.CustomTab import CustomTab
from ok.gui.tasks.OneTimeTaskTab import OneTimeTaskTab
from src.gui.navigation_sections import TESTS
from src.gui.SectionPanel import SectionPanel


class TestHubTab(CustomTab):
    def __init__(self):
        super().__init__()
        self.task_tab = OneTimeTaskTab(section=TESTS)
        self.account_switch_description = "账号切换测试（多账号每日任务测试）"
        self.section_panels = [SectionPanel("测试任务", self.account_switch_description, self.view)]
        self.section_panels[0].add_embedded_widget(self.task_tab, stretch=1)
        self.add_widget(self.section_panels[0], stretch=1)

    @property
    def name(self): return "测试功能"

    @property
    def icon(self): return FluentIcon.DEVELOPER_TOOLS
