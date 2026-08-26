"""Flat bordered section container shared by all five top-level pages."""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from src.gui.FlatSettingRow import FlatSettingRow


class SectionPanel(QWidget):
    def __init__(self, title: str, description: str = "", parent=None):
        super().__init__(parent)
        self.title = title
        self.setObjectName("codexSection")
        self.title_label = QLabel(title, self)
        self.title_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.description_label = QLabel(description, self)
        self.description_label.setWordWrap(True)
        self.description_label.setProperty("role", "description")
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(2)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        layout.addWidget(self.title_label)
        if description:
            layout.addWidget(self.description_label)
        layout.addLayout(self.content_layout)

    def add_widget(self, widget: QWidget, stretch: int = 0):
        self.content_layout.addWidget(widget, stretch)
        return widget

    def add_row(self, label: str, control: QWidget, description: str = "", error: str | None = None):
        row = FlatSettingRow(label, control, description, self)
        row.set_error(error)
        self.add_widget(row)
        return row


__all__ = ["SectionPanel"]
