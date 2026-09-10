"""Shared Fluent dropdowns with stable values and keyboard/wheel behavior."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QSizePolicy
from qfluentwidgets import ComboBox as FluentComboBox, setCustomStyleSheet
from shiboken6 import isValid


class ComboBox(FluentComboBox):
    def __init__(self, parent=None):
        self._display_text = ''
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setMinimumWidth(80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.StrongFocus)
        from src.gui.CodexTheme import COLORS
        focus_style = f"ComboBox:focus {{ border: 1px solid {COLORS['accent']}; }}"
        setCustomStyleSheet(self, focus_style, focus_style)

    def setText(self, text):
        self._display_text = str(text)
        self.setToolTip(self._display_text)
        self._update_elision()

    def _update_elision(self):
        QPushButton.setText(self, self.fontMetrics().elidedText(
            self._display_text, Qt.ElideRight, max(1, self.width() - 40)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elision()

    def wheelEvent(self, event):
        event.ignore()

    def _toggleComboMenu(self):
        # Windows keeps the menu reference when the pointer remains over the button.
        if self.dropMenu is not None and not isValid(self.dropMenu):
            self.dropMenu = None
        super()._toggleComboMenu()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_F4) or (
                event.key() == Qt.Key_Down and event.modifiers() & Qt.AltModifier):
            self._toggleComboMenu()
            event.accept()
        elif event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End):
            enabled = [i for i, item in enumerate(self.items) if item.isEnabled]
            if enabled:
                if event.key() == Qt.Key_Home:
                    index = enabled[0]
                elif event.key() == Qt.Key_End:
                    index = enabled[-1]
                elif event.key() == Qt.Key_Down:
                    index = next((i for i in enabled if i > self.currentIndex()), enabled[-1])
                else:
                    index = next((i for i in reversed(enabled) if i < self.currentIndex()), enabled[0])
                self.setCurrentIndex(index)
            event.accept()
        else:
            super().keyPressEvent(event)


class QtComboBox(ComboBox):
    """Compatibility for local Qt-style addItem(text, userData) callers."""
    def addItem(self, text, userData=None):
        super().addItem(text, userData=userData)
