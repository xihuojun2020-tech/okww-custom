from PySide6.QtWidgets import QTabWidget
from qfluentwidgets import FluentIcon
from ok.gui.widget.CustomTab import CustomTab
from ok.gui.tasks.OneTimeTaskTab import OneTimeTaskTab
from src.gui.navigation_sections import ACTIVITIES


class ActivityHubTab(CustomTab):
    def __init__(self):
        super().__init__()
        tabs = QTabWidget(self.view)
        self.limited_tab = OneTimeTaskTab(section=ACTIVITIES, activity_category="限时活动")
        self.permanent_tab = OneTimeTaskTab(section=ACTIVITIES, activity_category="常驻活动")
        tabs.addTab(self.limited_tab, "限时活动")
        tabs.addTab(self.permanent_tab, "常驻活动")
        self.add_widget(tabs, stretch=1)

    @property
    def name(self): return "活动"

    @property
    def icon(self): return FluentIcon.GAME
