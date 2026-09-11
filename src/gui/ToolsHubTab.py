"""Diagnostics, data maintenance and clearly labeled experimental tasks."""
from qfluentwidgets import FluentIcon
from ok.gui.widget.CustomTab import CustomTab
from ok.gui.settings.SettingTab import SettingTab
from ok.gui.tasks.OneTimeTaskTab import OneTimeTaskTab
from src.gui.SectionPanel import SectionPanel, reveal_widget
from src.gui.DiagnosticStatusCard import DiagnosticStatusCard
from src.gui.navigation_sections import TOOLS


class ToolsHubTab(CustomTab):
    def __init__(self, start_panel):
        super().__init__()
        title = SectionPanel('工具', parent=self.view)
        title.title_label.setProperty('role', 'pageTitle')
        self.add_widget(title)
        self.diagnostic_panel = DiagnosticStatusCard(self.view)
        self.diagnostic_panel.add_action(start_panel.open_logs_button)
        for widget in (start_panel.export_log_button, start_panel.open_log_folder_button,
                       start_panel.open_screenshot_folder_button):
            self.diagnostic_panel.add_widget(widget)
        self.add_widget(self.diagnostic_panel)
        self.maintenance_tab = SettingTab(account_maintenance_only=True)
        maintenance = SectionPanel('数据维护', parent=self.view)
        maintenance.title_label.hide()
        maintenance.add_embedded_widget(self.maintenance_tab)
        self.add_widget(maintenance)
        self.experiments = OneTimeTaskTab(section=TOOLS)
        self.task_tab = self.experiments  # Legacy hidden account-switch refresh entry.
        experimental = SectionPanel('实验功能', '功能仍在验证中，请确认游戏状态后使用。', self.view)
        experimental.add_embedded_widget(self.experiments)
        self.add_widget(experimental)
        self.developer_section = SectionPanel('开发诊断', '截图、OCR 与调试框，仅用于排查识别问题。', self.view, collapsible=True)
        self.developer_section.add_widget(start_panel.start_card.capture_button)
        self.developer_section.add_widget(start_panel.debug_widget)
        self.developer_section.add_widget(start_panel.overlay_widget)
        self.add_widget(self.developer_section)
        start_panel.tools_button.hide()
        start_panel.overlay_card.hide()
        from src.gui.compact_settings import compact_settings
        compact_settings(self)
        title.content.hide()
        title.layout().setContentsMargins(0, 0, 0, 4)

    def goto_config(self, key):
        return self.maintenance_tab.goto_config(key)

    def show_diagnostics(self):
        self.diagnostic_panel.set_expanded(True)
        reveal_widget(self.diagnostic_panel.status)

    @property
    def name(self): return '工具'

    @property
    def icon(self): return FluentIcon.DEVELOPER_TOOLS
