"""Integrated account configuration, sequences, and maintenance page."""

from qfluentwidgets import FluentIcon

from ok.gui.widget.CustomTab import CustomTab
from src.gui.AccountConfigTab import AccountConfigTab
from src.gui.SequenceManagementTab import SequenceManagementTab
from src.gui.SectionPanel import SectionPanel


class AccountSettingsTab(CustomTab):
    def __init__(self, maintenance_tab=None):
        super().__init__()
        from ok.gui.settings.SettingTab import SettingTab
        self.account_tab = AccountConfigTab()
        self.sequence_tab = SequenceManagementTab()
        self.maintenance_tab = maintenance_tab or SettingTab(account_maintenance_only=True)
        self.section_panels = []
        for title, widget in (
                ("账号配置", self.account_tab),
                ("序列配置", self.sequence_tab),
                ("导入导出、备份与完整性", self.maintenance_tab)):
            section = SectionPanel(title, parent=self.view)
            section.add_widget(widget, stretch=1)
            self.section_panels.append(section)
            self.add_widget(section, stretch=1)

    @property
    def name(self): return "账号设置"

    @property
    def icon(self): return FluentIcon.PEOPLE


__all__ = ["AccountSettingsTab"]
