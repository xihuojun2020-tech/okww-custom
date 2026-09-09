"""Flat bordered section container shared by all five top-level pages."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget, QSizePolicy, QToolButton, QScrollArea

from src.gui.FlatSettingRow import FlatSettingRow
from src.gui.CodexTheme import SPACING


class SectionPanel(QWidget):
    def __init__(self, title: str, description: str = "", parent=None, *, collapsible=False, expanded=False):
        super().__init__(parent)
        self.title = title
        # Sections are the full-width building blocks of every hub page.
        # Explicitly opting into horizontal expansion prevents a child whose
        # size hint is only a few hundred pixels wide from leaving a large
        # unused area on the right side of the window.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setObjectName("codexSection")
        self.setAttribute(Qt.WA_StyledBackground)
        self.title_label = QLabel(title, self)
        self.title_label.setProperty("role", "sectionTitle")
        self.title_label.setWordWrap(True)
        self.description_label = QLabel(description, self)
        self.description_label.setWordWrap(True)
        self.description_label.setProperty("role", "description")
        self.content = QWidget(self)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(2)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, SPACING['row'], 0, SPACING['section'])
        layout.setSpacing(SPACING['row'])
        self.toggle_button = QToolButton(self)
        self.toggle_button.setText(title)
        self.toggle_button.setAccessibleName(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.toggle_button.setProperty("role", "disclosure")
        self.toggle_button.toggled.connect(self.set_expanded)
        self.collapsible = collapsible
        self.title_label.setVisible(not collapsible)
        self.toggle_button.setVisible(collapsible)
        layout.addWidget(self.title_label)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.description_label)
        self.description_label.setVisible(bool(description))
        layout.addWidget(self.content)
        self.set_expanded(expanded if collapsible else True)

    def set_expanded(self, expanded):
        expanded = bool(expanded or not self.collapsible)
        self.toggle_button.blockSignals(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.blockSignals(False)
        self.toggle_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.toggle_button.setAccessibleDescription("已展开" if expanded else "已收起")
        self.content.setVisible(expanded)
        self.updateGeometry()

    def set_description(self, text):
        self.description_label.setText(text)
        self.description_label.setVisible(bool(text))

    def add_widget(self, widget: QWidget, stretch: int = 0):
        policy = widget.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        widget.setSizePolicy(policy)
        self.content_layout.addWidget(widget, stretch)
        return widget

    def add_embedded_widget(self, widget: QWidget, stretch: int = 0):
        """Embed a CustomTab's content without keeping its inner scroll area."""
        content = getattr(widget, "view", widget)
        if content is not widget:
            take_widget = getattr(widget, "takeWidget", None)
            if callable(take_widget):
                take_widget()
            content.setParent(self)
            if content.layout():
                content.layout().setContentsMargins(0, 0, 0, 0)
        return self.add_widget(content, stretch)

    def add_row(self, label: str, control: QWidget, description: str = "", error: str | None = None):
        row = FlatSettingRow(label, control, description, self)
        row.set_error(error)
        self.add_widget(row)
        return row


def reveal_widget(widget):
    """Open containing sections before navigating to a field or validation error."""
    parent = widget.parentWidget()
    pages = []
    while parent is not None:
        if isinstance(parent, SectionPanel):
            parent.set_expanded(True)
        if isinstance(parent, QScrollArea):
            pages.append(parent)
        parent = parent.parentWidget()
    widget.setFocus(Qt.OtherFocusReason)
    from PySide6.QtCore import QTimer
    for page in pages:
        QTimer.singleShot(0, lambda page=page: page.ensureWidgetVisible(widget))


__all__ = ["SectionPanel", "reveal_widget"]
