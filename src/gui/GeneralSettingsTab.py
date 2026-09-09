"""One page containing every general automation setting."""

from pathlib import Path

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon

from ok.gui.widget.CustomTab import CustomTab
from src.gui.SectionPanel import SectionPanel


class GeneralSettingsTab(CustomTab):
    section_titles = ("连接与运行", "启动与实时功能", "快捷键", "日志与诊断", "版本与更新", "其他全局设置")

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
        behavior_layout.setContentsMargins(0, 0, 0, 0)
        from src.gui.DiagnosticStatusCard import DiagnosticStatusCard
        self.diagnostic_panel = DiagnosticStatusCard(self.view)
        from config import version
        from src.gui.LanUpdateCard import LanUpdateCard
        self.lan_update_card = LanUpdateCard(
            Path(__file__).resolve().parents[2] / "configs" / "lan_update.json",
            version, executor, behavior_tab)
        self.hotkey_config = None
        self.basic_config = None
        self.config_cards = {}
        for name, config_obj, option in global_config.get_all_visible_configs():
            if name == "Game Hotkey":
                self.hotkey_config = config_obj
                self.hotkey_panel = GlobalConfigTab(config_obj, option)
                content = self.hotkey_panel.takeWidget()
                self.hotkey_content = content
                content.layout().setContentsMargins(0, 0, 0, 0)
                hotkey_layout.addWidget(content)
            elif name == "Basic Options":
                self.basic_config = config_obj
            else:
                card = GlobalConfigCard(config_obj, option)
                self.config_cards[name] = card
                behavior_layout.addWidget(card)
        start_stop_row = QWidget(hotkey_tab)
        start_stop_layout = QHBoxLayout(start_stop_row)
        start_stop_layout.setContentsMargins(12, 8, 12, 8)
        self.start_stop_status = QLabel(start_stop_row)
        self.start_stop_status.setWordWrap(True)
        self.start_stop_combo = QComboBox(start_stop_row)
        self.start_stop_combo.addItems(["None", "F9", "F10", "F11", "F12"])
        current_hotkey = str(self.basic_config.get("Start/Stop") if self.basic_config else "F9")
        self.start_stop_combo.setCurrentText(current_hotkey)
        self.start_stop_combo.currentTextChanged.connect(self._update_start_stop_hotkey)
        start_stop_layout.addWidget(self.start_stop_status, 1)
        start_stop_layout.addWidget(self.start_stop_combo)
        hotkey_layout.insertWidget(0, start_stop_row)
        self._update_start_stop_hotkey(current_hotkey)
        self.section_panels = []
        for title, panel in zip(self.section_titles, (
                self.start_panel, self.trigger_panel, hotkey_tab, self.diagnostic_panel,
                self.lan_update_card, behavior_tab)):
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
        for section in getattr(self, 'section_panels', ()):
            if section.title == '快捷键':
                section.set_summary(self.start_stop_status.text())

    def goto_config(self, key):
        from src.gui.SectionPanel import reveal_widget
        if self.hotkey_config is not None and (key == 'Game Hotkey' or key in self.hotkey_config):
            reveal_widget(self.hotkey_content)
            self.ensureWidgetVisible(self.hotkey_content)
            return True
        for name, card in self.config_cards.items():
            if key == name or card.has_key(key):
                card.setExpand(True)
                reveal_widget(card)
                self.ensureWidgetVisible(card)
                return True
        return False

    def add_card(self, title, widget, stretch=0, parent=None):
        """Keep the old call site while using the shared flat section shell."""
        if isinstance(widget, SectionPanel):
            self.section_panels.append(widget)
            self.add_widget(widget, stretch)
            return widget
        section = SectionPanel(title, parent=self.view,
                               collapsible=title in ('连接与运行', '快捷键'))
        section.add_embedded_widget(widget)
        if title == '连接与运行':
            card = self.start_panel.start_card
            for button in (card.refresh_button, card.start_button):
                section.add_action(button)
            card.disclosure_header = section.header
            card.update_status()
        elif title == '快捷键':
            section.set_summary(self.start_stop_status.text())
        self.section_panels.append(section)
        self.add_widget(section, stretch)
        return section

    @property
    def name(self): return "通用设置"

    @property
    def icon(self): return FluentIcon.HOME


__all__ = ["GeneralSettingsTab"]
