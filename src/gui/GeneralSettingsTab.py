"""Global settings only: connection, keys, preferences and updates."""
from pathlib import Path
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget, QPushButton
from src.gui.ChoiceControls import QtComboBox as QComboBox
from qfluentwidgets import FluentIcon
from ok.gui.widget.CustomTab import CustomTab
from src.gui.SectionPanel import SectionPanel, reveal_widget


class GeneralSettingsTab(CustomTab):
    section_titles = ('游戏连接', '运行与按键', '程序偏好', '版本与更新')

    def __init__(self, config, exit_event, executor, global_config):
        super().__init__()
        from ok.gui.start.StartTab import StartTab
        from ok.gui.settings.GlobalConfigTab import GlobalConfigTab
        from ok.gui.settings.GlobalConfigCard import GlobalConfigCard
        from ok.gui.settings.SettingTab import SettingTab
        from src.gui.LanUpdateCard import LanUpdateCard
        from config import version
        # Assistant and tools reparent existing widgets, never create another handler.
        self.start_panel = StartTab(config, exit_event)
        self.preferences = SettingTab()
        self.preferences.basic_group.title_label.hide()
        self.preferences.add_widget(self.start_panel.open_install_folder_button)
        from src.runtime.diagnostic_storage import storage_path
        repo = Path(__file__).resolve().parents[2]
        root = storage_path('MaterialPlanner', repo / 'MaterialPlanner').parent
        storage_label = QLabel(f'程序位置：{repo}\n运行资料：{root}\n旧版资料迁移后保留原副本；统计与完成原图不自动删除。')
        storage_label.setWordWrap(True)
        self.preferences.add_widget(storage_label)
        open_data = QPushButton('打开运行资料目录')
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        open_data.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(root))))
        self.preferences.add_widget(open_data)
        self.lan_update_card = LanUpdateCard(
            Path(__file__).resolve().parents[2] / 'configs' / 'lan_update.json', version, executor, self.view)
        self.hotkey_config = None
        self.basic_config = None
        self.config_cards = {}
        self.section_panels = []
        runtime = QWidget(self.view)
        runtime_layout = QVBoxLayout(runtime)
        runtime_layout.setContentsMargins(0, 0, 0, 0)
        self.hotkey_section = SectionPanel('快捷键', parent=runtime, collapsible=True)
        runtime_layout.addWidget(self.hotkey_section)
        for name, config_obj, option in global_config.get_all_visible_configs():
            if name == 'Game Hotkey':
                self.hotkey_config = config_obj
                self.hotkey_panel = GlobalConfigTab(config_obj, option)
                self.hotkey_content = self.hotkey_panel.view
                self.hotkey_section.add_embedded_widget(self.hotkey_panel)
            elif name == 'Basic Options':
                self.basic_config = config_obj
            elif name not in ('Config Backup', '数据仓库文件夹'):
                card = GlobalConfigCard(config_obj, option)
                self.config_cards[name] = card
                if name in ('数据仓库文件夹', 'Notification', 'App Launcher'):
                    self.preferences.add_widget(card)
                else:
                    runtime_layout.addWidget(card)
        start_stop_row = QWidget(runtime)
        row = QHBoxLayout(start_stop_row)
        row.setContentsMargins(8, 4, 8, 4)
        self.start_stop_status = QLabel(start_stop_row)
        self.start_stop_status.setWordWrap(True)
        self.start_stop_combo = QComboBox(start_stop_row)
        self.start_stop_combo.setAccessibleName('程序启停快捷键')
        for hotkey in ('None', 'F9', 'F10', 'F11', 'F12'):
            self.start_stop_combo.addItem('无' if hotkey == 'None' else hotkey, hotkey)
        current = str(self.basic_config.get('Start/Stop') if self.basic_config else 'F9')
        self.start_stop_combo.setCurrentIndex(self.start_stop_combo.findData(current))
        self.start_stop_combo.currentIndexChanged.connect(
            lambda _: self._update_start_stop_hotkey(self.start_stop_combo.currentData()))
        row.addWidget(self.start_stop_status, 1)
        row.addWidget(self.start_stop_combo)
        self.hotkey_section.content_layout.insertWidget(0, start_stop_row)
        self._update_start_stop_hotkey(current)
        for title, panel in zip(self.section_titles, (
                self.start_panel, runtime, self.preferences, self.lan_update_card)):
            self.add_card(title, panel)
        from src.gui.compact_settings import compact_settings
        compact_settings(self)

    def _update_start_stop_hotkey(self, value):
        if self.basic_config is not None:
            self.basic_config['Start/Stop'] = value
        game_keys = {str(self.hotkey_config.get(key) or '').casefold() for key in (
            'Echo Key', 'Liberation Key', 'Resonance Key', 'Tool Key', 'Jump Key',
            'Dodge Key', 'Wheel Key', 'Guidebook Key', 'Bag Key')} if self.hotkey_config is not None else set()
        conflict = value != 'None' and value.casefold() in game_keys
        state = '与游戏快捷键冲突，请更换' if conflict else '已停用' if value == 'None' else '已启用'
        display_value = '无' if value == 'None' else value
        text = f'程序启停快捷键：{display_value}（{state}）'
        self.start_stop_status.setText(text)
        self.hotkey_section.set_summary(text)

    def goto_config(self, key):
        if key in ('Start/Stop', 'Game Hotkey') or (self.hotkey_config is not None and key in self.hotkey_config):
            self.hotkey_section.set_expanded(True)
            reveal_widget(self.start_stop_combo)
            return True
        for name, card in self.config_cards.items():
            if key == name or card.has_key(key):
                card.setExpand(True)
                reveal_widget(card)
                return True
        return self.preferences.goto_config(key)

    def add_card(self, title, widget, stretch=0, parent=None):
        if isinstance(widget, SectionPanel):
            section = widget
        else:
            section = SectionPanel(title, parent=self.view, collapsible=title == '游戏连接')
            section.add_embedded_widget(widget)
        if title == '游戏连接':
            card = self.start_panel.start_card
            section.add_action(card.refresh_button)
            card.disclosure_header = section.header
            card.update_status()
        self.section_panels.append(section)
        self.add_widget(section, stretch)
        return section

    @property
    def name(self): return '设置'

    @property
    def icon(self): return FluentIcon.SETTING
