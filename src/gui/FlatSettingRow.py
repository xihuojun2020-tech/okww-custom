"""Reusable horizontal setting row for the light UI."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget, QAbstractButton, QAbstractSpinBox
from qfluentwidgets import ComboBox


class FlatSettingRow(QWidget):
    def __init__(self, label: str, control: QWidget, description: str = "", parent=None):
        super().__init__(parent)
        from ok import og
        if og.app is not None:
            label = og.app.tr(label)
            description = og.app.tr(description) if description else ''
        self.control = control
        self.label = QLabel(label, self)
        self.label.setWordWrap(True)
        self.label.setProperty("role", "label")
        self.label.setBuddy(control)
        if not control.accessibleName():
            control.setAccessibleName(label)
        control.setAccessibleDescription(description)
        self.description_label = QLabel(description, self)
        self.description_label.setWordWrap(True)
        self.description_label.setProperty("role", "description")
        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.setProperty("role", "error")
        self.error_label.hide()
        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 12, 0)
        copy.setSpacing(1)
        copy.setAlignment(Qt.AlignVCenter)
        copy.addWidget(self.label)
        if description:
            copy.addWidget(self.description_label)
        copy.addWidget(self.error_label)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        layout.addLayout(copy, 1)
        compact = isinstance(control, (QAbstractButton, QAbstractSpinBox)) and not isinstance(control, ComboBox)
        control.setSizePolicy(QSizePolicy.Preferred if compact else QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(control, 0 if compact else 1, Qt.AlignVCenter)

    def resizeEvent(self, event):
        self.layout().setDirection(QBoxLayout.TopToBottom if self.width() < 600 else QBoxLayout.LeftToRight)
        super().resizeEvent(event)

    def set_error(self, message: str | None):
        self.error_label.setText(message or "")
        self.error_label.setVisible(bool(message))
        if message:
            from src.gui.SectionPanel import reveal_widget
            reveal_widget(self.control)


__all__ = ["FlatSettingRow"]
