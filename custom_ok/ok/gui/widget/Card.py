"""Compatibility shell for flat sections, with no nested card frame."""
from PySide6.QtWidgets import QWidget, QLayout, QHBoxLayout
from src.gui.SectionPanel import SectionPanel


class Card(SectionPanel):
    def __init__(self, title, widget, stretch=0, parent=None):
        super().__init__(title, parent=parent)
        if isinstance(widget, QLayout):
            container = QWidget(self)
            container.setLayout(widget)
            widget = container
        self.widget = widget
        self.titleLabel = self.title_label
        self.title_layout = QHBoxLayout()
        self.layout().removeWidget(self.title_label)
        self.title_layout.addWidget(self.title_label, 1)
        self.layout().insertLayout(0, self.title_layout)
        self.add_widget(widget)

    def add_top_widget(self, widget):
        self.title_layout.addWidget(widget)
