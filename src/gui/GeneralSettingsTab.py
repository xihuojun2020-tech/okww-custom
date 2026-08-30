"""One page containing every general automation setting."""

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon

from ok.gui.widget.CustomTab import CustomTab
from src.gui.SectionPanel import SectionPanel


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
        self.basic_config = None
        for name, config_obj, option in global_config.get_all_visible_configs():
            if name == "Game Hotkey":
                self.hotkey_config = config_obj
                hotkey_layout.addWidget(GlobalConfigTab(config_obj, option))
            elif name == "Basic Options":
                self.basic_config = config_obj
            else:
                behavior_layout.addWidget(GlobalConfigCard(config_obj, option))
        start_stop_row = QWidget(hotkey_tab)
        start_stop_layout = QHBoxLayout(start_stop_row)
        start_stop_layout.setContentsMargins(12, 8, 12, 8)
        self.start_stop_status = QLabel(start_stop_row)
        self.start_stop_combo = QComboBox(start_stop_row)
        self.start_stop_combo.addItems(["None", "F9", "F10", "F11", "F12"])
        current_hotkey = str(self.basic_config.get("Start/Stop") if self.basic_config else "F9")
        self.start_stop_combo.setCurrentText(current_hotkey)
        self.start_stop_combo.currentTextChanged.connect(self._update_start_stop_hotkey)
        start_stop_layout.addWidget(self.start_stop_status, 1)
        start_stop_layout.addWidget(self.start_stop_combo)
        hotkey_layout.insertWidget(0, start_stop_row)
        self._update_start_stop_hotkey(current_hotkey)
        hotkey_layout.addStretch(1)
        behavior_layout.addStretch(1)
        self.section_panels = []
        for title, panel in zip(self.section_titles, (
                self.start_panel, self.trigger_panel, hotkey_tab, behavior_tab)):
            panel.setMinimumHeight(360)
            self.add_card(title, panel)

    def _update_start_stop_hotkey(self, value):
        if self.basic_config is not None:
            self.basic_config["Start/Stop"] = value
        game_keys = {
            str(self.hotkey_config.get(key) or "").casefold()
            for key in ("Echo Key", "Liberation Key", "Resonance Key", "Tool Key",
                        "Jump Key", "Dodge Key", "Wheel Key", "Guidebook Key", "Bag Key")
        } if self.hotkey_config is not None else set()
        conflict = value.casefold() in game_keys and value != "None"
        state = "与游戏快捷键冲突，请更换" if conflict else ("已停用" if value == "None" else "已启用")
        self.start_stop_status.setText(f"程序启停快捷键：{value}（{state}）")

    def add_card(self, title, widget, stretch=0, parent=None):
        """Keep the old call site while using the shared flat section shell."""
        section = SectionPanel(title, parent=self.view)
        section.add_embedded_widget(widget, stretch=1)
        self.section_panels.append(section)
        self.add_widget(section, stretch)
        return section

    @property
    def name(self): return "通用设置"

    @property
    def icon(self): return FluentIcon.HOME


__all__ = ["GeneralSettingsTab"]
