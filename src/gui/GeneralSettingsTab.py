"""One page containing every general automation setting."""

from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon

from ok.gui.widget.CustomTab import CustomTab


class GeneralSettingsTab(CustomTab):
    section_titles = ("监控与启动", "实时触发", "游戏快捷键", "全局行为")

    def __init__(self, config, exit_event, executor, global_config):
        super().__init__()
        from ok.gui.start.StartTab import StartTab
        from ok.gui.tasks.TriggerTaskTab import TriggerTaskTab
        from ok.gui.settings.GlobalConfigTab import GlobalConfigTab
        from ok.gui.settings.GlobalConfigCard import GlobalConfigCard

        self.start_panel = StartTab(config, exit_event)
        self.trigger_panel = TriggerTaskTab()
        self.trigger_tasks = tuple(task for task in executor.trigger_tasks if getattr(task, "visible", True))
        hotkey_tab = QWidget(self.view)
        hotkey_layout = QVBoxLayout(hotkey_tab)
        behavior_tab = QWidget(self.view)
        behavior_layout = QVBoxLayout(behavior_tab)
        behavior_layout.setContentsMargins(12, 12, 12, 12)
        self.hotkey_config = None
        for name, config_obj, option in global_config.get_all_visible_configs():
            if name == "Game Hotkey":
                self.hotkey_config = config_obj
                hotkey_layout.addWidget(GlobalConfigTab(config_obj, option))
            elif name not in {"Basic Options"}:
                behavior_layout.addWidget(GlobalConfigCard(config_obj, option))
        hotkey_layout.addStretch(1)
        behavior_layout.addStretch(1)
        for title, panel in zip(self.section_titles, (
                self.start_panel, self.trigger_panel, hotkey_tab, behavior_tab)):
            panel.setMinimumHeight(360)
            self.add_card(title, panel)

    @property
    def name(self): return "通用设置"

    @property
    def icon(self): return FluentIcon.HOME


__all__ = ["GeneralSettingsTab"]
