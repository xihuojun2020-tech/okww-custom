from qfluentwidgets import FluentIcon
from ok.gui.widget.CustomTab import CustomTab
from ok.gui.tasks.OneTimeTaskTab import OneTimeTaskTab
from src.gui.navigation_sections import TESTS
from src.gui.SectionPanel import SectionPanel


class TestHubTab(CustomTab):
    def __init__(self):
        super().__init__()
        self.task_tab = OneTimeTaskTab(section=TESTS)
        self.section_panels = [SectionPanel("测试功能", "仅供诊断与验证，请确认游戏状态后运行。", self.view)]
        self.section_panels[0].add_embedded_widget(self.task_tab)
        self.add_widget(self.section_panels[0])

    @property
    def name(self): return "测试功能"

    @property
    def icon(self): return FluentIcon.DEVELOPER_TOOLS
