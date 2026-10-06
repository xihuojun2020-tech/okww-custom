"""Flat bordered section container shared by all five top-level pages."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget, QSizePolicy, QToolButton, QScrollArea, QLayout

from src.gui.FlatSettingRow import FlatSettingRow
from src.gui.CodexTheme import SPACING
from src.gui.DisclosureHeader import DisclosureHeader


class SectionPanel(QWidget):
    def __init__(self, title: str, description: str = "", parent=None, *, collapsible=False, expanded=False):
        super().__init__(parent)
        self.title = title
        # Sections are the full-width building blocks of every hub page.
        # Explicitly opting into horizontal expansion prevents a child whose
        # size hint is only a few hundred pixels wide from leaving a large
        # unused area on the right side of the window. Vertically, sections
        # follow their content instead of distributing spare page height.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
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
        self.content_layout.setSpacing(SPACING['row'])
        self.content_layout.setAlignment(Qt.AlignTop)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(SPACING['panel'],) * 4)
        layout.setSpacing(SPACING['row'])
        self.header = DisclosureHeader(title, self)
        self.toggle_button = self.header.expandButton
        self.header.toggled.connect(self.set_expanded)
        self.collapsible = collapsible
        self.title_label.setVisible(not collapsible)
        self.header.setVisible(collapsible)
        layout.addWidget(self.title_label)
        layout.addWidget(self.header)
        self.content_layout.addWidget(self.description_label)
        self.description_label.setVisible(bool(description))
        layout.addWidget(self.content)
        self.set_expanded(expanded if collapsible else True)

    def set_flat(self):
        """Use for page wrappers and task groups containing their own panels."""
        self.setProperty('flat', True)
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_expanded(self, expanded):
        expanded = bool(expanded or not self.collapsible)
        self.header.set_expanded(expanded)
        self.content.setVisible(expanded)
        self.updateGeometry()

    def set_description(self, text):
        self.description_label.setText(text)
        self.description_label.setVisible(bool(text))

    def set_summary(self, text):
        self.header.set_summary(text)

    def add_action(self, widget):
        self.header.add_action(widget)

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
            content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
            if content.layout():
                # CustomTab's scroll view uses SetMinimumSize. Once detached,
                # that constraint can retain the expanded page's minimum
                # height and spread spare space across collapsed headers.
                # The containing hub now owns scrolling and content sizing.
                content.layout().setSizeConstraint(QLayout.SetDefaultConstraint)
                content.setMinimumSize(0, 0)
                content.layout().setContentsMargins(0, 0, 0, 0)
                content.layout().setSpacing(SPACING['row'])
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
