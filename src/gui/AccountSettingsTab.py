"""Integrated account configuration, sequences, and maintenance page."""

from PySide6.QtWidgets import QTabWidget
from qfluentwidgets import FluentIcon

from ok.gui.widget.CustomTab import CustomTab
from src.gui.AccountConfigTab import AccountConfigTab
from src.gui.SequenceManagementTab import SequenceManagementTab


class AccountSettingsTab(CustomTab):
    def __init__(self, maintenance_tab=None):
        super().__init__()
        from ok.gui.settings.SettingTab import SettingTab
        self.account_tab = AccountConfigTab()
        self.sequence_tab = SequenceManagementTab()
        self.maintenance_tab = maintenance_tab or SettingTab(account_maintenance_only=True)
        tabs = QTabWidget(self.view)
        tabs.addTab(self.account_tab, "账号配置")
        tabs.addTab(self.sequence_tab, "序列配置")
        tabs.addTab(self.maintenance_tab, "导入导出、备份与完整性")
        self.add_widget(tabs, stretch=1)

    @property
    def name(self): return "账号设置"

    @property
    def icon(self): return FluentIcon.PEOPLE


__all__ = ["AccountSettingsTab"]
