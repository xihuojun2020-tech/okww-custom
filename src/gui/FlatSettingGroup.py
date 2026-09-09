"""Natural-height compatibility widgets for the framework settings page."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton
from src.gui.SectionPanel import SectionPanel
from src.gui.FlatSettingRow import FlatSettingRow


class FlatSettingGroup(SectionPanel):
    def addSettingCard(self, card):
        self.add_widget(card)


class FlatActionSettingCard(SectionPanel):
    clicked = Signal()

    def __init__(self, text, icon, title, content='', parent=None):
        button = QPushButton(text)
        super().__init__(title, content, parent, collapsible=True)
        self.control = button
        self.add_action(button)
        button.clicked.connect(self.clicked)
