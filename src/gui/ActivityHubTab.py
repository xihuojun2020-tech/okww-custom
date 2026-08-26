from qfluentwidgets import FluentIcon
from ok.gui.widget.CustomTab import CustomTab
from ok.gui.tasks.OneTimeTaskTab import OneTimeTaskTab
from src.gui.navigation_sections import ACTIVITIES
from src.gui.SectionPanel import SectionPanel


class ActivityHubTab(CustomTab):
    def __init__(self):
        super().__init__()
        self.limited_tab = OneTimeTaskTab(section=ACTIVITIES, activity_category="限时活动")
        self.permanent_tab = OneTimeTaskTab(section=ACTIVITIES, activity_category="常驻活动")
        self.section_panels = []
        for title, tab in (("限时活动", self.limited_tab), ("常驻活动", self.permanent_tab)):
            section = SectionPanel(title, parent=self.view)
            section.add_widget(tab, stretch=1)
            self.section_panels.append(section)
            self.add_widget(section, stretch=1)

    @property
    def name(self): return "活动"

    @property
    def icon(self): return FluentIcon.GAME
