"""Reusable horizontal setting row for the light UI."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget


class FlatSettingRow(QWidget):
    def __init__(self, label: str, control: QWidget, description: str = "", parent=None):
        super().__init__(parent)
        self.control = control
        self.label = QLabel(label, self)
        self.label.setMinimumWidth(150)
        self.label.setProperty("role", "label")
        self.description_label = QLabel(description, self)
        self.description_label.setWordWrap(True)
        self.description_label.setProperty("role", "description")
        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #CF222E; font-size: 12px;")
        self.error_label.hide()
        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 12, 0)
        copy.setSpacing(2)
        copy.addWidget(self.label)
        if description:
            copy.addWidget(self.description_label)
        copy.addWidget(self.error_label)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        layout.addLayout(copy, 1)
        control.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(control, 1, Qt.AlignVCenter)

    def set_error(self, message: str | None):
        self.error_label.setText(message or "")
        self.error_label.setVisible(bool(message))


__all__ = ["FlatSettingRow"]
