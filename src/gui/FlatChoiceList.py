"""List-compatible short choices with real radio buttons and no scroll viewport."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QRadioButton, QButtonGroup


class FlatChoiceList(QWidget):
    itemSelectionChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source = QListWidget(self)
        self.source.hide()
        self.rows = QVBoxLayout(self)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(8)
        self.group = QButtonGroup(self)
        self.group.idClicked.connect(self.setCurrentRow)
        self.source.itemSelectionChanged.connect(self._selection_changed)
        model = self.source.model()
        model.rowsInserted.connect(self.refresh_choices)
        model.rowsRemoved.connect(self.refresh_choices)
        model.dataChanged.connect(self.refresh_choices)

    def refresh_choices(self, *_):
        while self.rows.count():
            widget = self.rows.takeAt(0).widget()
            self.group.removeButton(widget)
            widget.hide()
            widget.deleteLater()
        for index in range(self.count()):
            item = self.item(index)
            if item.isHidden():
                continue
            button = QRadioButton(item.text(), self)
            button.setToolTip(item.text())
            self.group.addButton(button, index)
            button.setChecked(index == self.currentRow())
            self.rows.addWidget(button)
        self.updateGeometry()

    def _selection_changed(self):
        button = self.group.button(self.currentRow())
        if button:
            button.setChecked(True)
        self.itemSelectionChanged.emit()

    def count(self): return self.source.count()
    def item(self, index): return self.source.item(index)
    def addItem(self, item): self.source.addItem(item)
    def takeItem(self, index): return self.source.takeItem(index)
    def currentRow(self): return self.source.currentRow()
    def setCurrentRow(self, index): self.source.setCurrentRow(index)
    def setSelectionMode(self, mode): self.source.setSelectionMode(mode)
