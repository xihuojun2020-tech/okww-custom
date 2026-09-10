"""Continuous game helpers and the existing global run controller."""
from qfluentwidgets import FluentIcon
from ok.gui.widget.CustomTab import CustomTab
from ok.gui.tasks.TriggerTaskTab import TriggerTaskTab
from src.gui.SectionPanel import SectionPanel


class AssistantHubTab(CustomTab):
    def __init__(self, start_panel):
        super().__init__()
        self.run_section = SectionPanel('自动辅助', '开关决定启用哪些辅助；点击开始后才会运行。暂停不改变已保存的开关。', self.view)
        self.run_section.title_label.setProperty('role', 'pageTitle')
        self.run_section.add_widget(start_panel.start_card)
        self.add_widget(self.run_section)
        self.trigger_panel = TriggerTaskTab()
        section = SectionPanel('辅助功能', parent=self.view)
        section.title_label.hide()
        section.layout().setContentsMargins(0, 4, 0, 8)
        section.add_embedded_widget(self.trigger_panel)
        self.add_widget(section)

    @property
    def name(self): return '自动辅助'

    @property
    def icon(self): return FluentIcon.PLAY
