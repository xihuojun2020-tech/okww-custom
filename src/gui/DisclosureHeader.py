"""Shared compact header: a clickable summary and independent action controls."""
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QVBoxLayout, QToolButton, QSizePolicy


class DisclosureHeader(QWidget):
    toggled = Signal(bool)

    def __init__(self, title, parent=None, *, icon=None):
        super().__init__(parent)
        self.setObjectName('disclosureHeader')
        self.setAttribute(Qt.WA_StyledBackground)
        self.setMinimumHeight(56)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._actions = []
        self.layout_row = QHBoxLayout(self)
        self.layout_row.setContentsMargins(12, 6, 8, 6)
        self.layout_row.setSpacing(8)
        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(24, 24)
        if icon is not None:
            from qfluentwidgets.common.icon import toQIcon
            self.icon_label.setPixmap(toQIcon(icon).pixmap(QSize(20, 20)))
        else:
            self.icon_label.hide()
        self.titleLabel = QLabel(title, self)
        self.titleLabel.setWordWrap(True)
        self.titleLabel.setProperty('role', 'sectionTitle')
        self.summary_label = QLabel(self)
        self.summary_label.setWordWrap(True)
        self.summary_label.setProperty('role', 'description')
        self.summary_label.hide()
        self.text_layout = QVBoxLayout()
        self.text_layout.setSpacing(1)
        self.text_layout.setAlignment(Qt.AlignVCenter)
        self.text_layout.addWidget(self.titleLabel)
        self.text_layout.addWidget(self.summary_label)
        self.expandButton = QToolButton(self)
        self.expandButton.setProperty('role', 'disclosure')
        self.expandButton.setFixedSize(40, 40)
        self.expandButton.setCheckable(True)
        self.expandButton.setAccessibleName(f'{title}：展开或收起详情')
        self.expandButton.toggled.connect(self.toggled)
        self.layout_row.addWidget(self.icon_label)
        self.layout_row.addLayout(self.text_layout, 1)
        self.layout_row.addWidget(self.expandButton)
        # Only header labels forward clicks. Detail editors are never filtered.
        for label in (self.icon_label, self.titleLabel, self.summary_label):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.set_expanded(False)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            if any(widget.isVisible() and widget.rect().contains(
                    widget.mapFrom(self, event.position().toPoint())) for widget in self._actions):
                event.accept()
                return
            if self.expandButton.isEnabled() and not self.expandButton.isHidden():
                self.expandButton.click()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def add_action(self, widget):
        self._actions.append(widget)
        self.layout_row.insertWidget(self.layout_row.count() - 1, widget)
        if widget.focusPolicy() != Qt.NoFocus:
            QWidget.setTabOrder(widget, self.expandButton)

    def set_summary(self, text):
        self.summary_label.setText(text)
        self.summary_label.setVisible(bool(text))

    def set_expanded(self, expanded):
        self.expandButton.blockSignals(True)
        self.expandButton.setChecked(expanded)
        self.expandButton.blockSignals(False)
        self.expandButton.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.expandButton.setAccessibleDescription('已展开' if expanded else '已收起')
        self.expandButton.setToolTip('收起详情' if expanded else '展开详情')
