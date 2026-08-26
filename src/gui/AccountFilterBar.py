"""Compact account filtering controls shared by account/sequence pages."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLineEdit, QWidget


@dataclass(frozen=True)
class AccountFilter:
    text: str = ""
    sequence_id: str = ""
    incomplete_only: bool = False


class AccountFilterBar(QWidget):
    filter_changed = Signal(str, str, bool)

    def __init__(self, sequences=(), parent=None):
        super().__init__(parent)
        self.current_filter = AccountFilter()
        layout = QHBoxLayout(self)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("搜索账号短名、带星号手机号或 U…A 名称")
        self.sequence = QComboBox(self)
        self.sequence.addItem("全部序列", "")
        for value in sequences:
            self.sequence.addItem(str(value), str(value))
        self.incomplete = QCheckBox("仅显示未完成", self)
        layout.addWidget(self.search, 1)
        layout.addWidget(self.sequence)
        layout.addWidget(self.incomplete)
        self.search.textChanged.connect(self._emit)
        self.sequence.currentIndexChanged.connect(self._emit)
        self.incomplete.toggled.connect(self._emit)

    def set_text(self, text: str):
        self.search.setText(str(text))

    def _emit(self, *_args):
        self.current_filter = AccountFilter(self.search.text().strip(),
                                             str(self.sequence.currentData() or ""),
                                             self.incomplete.isChecked())
        self.filter_changed.emit(self.current_filter.text, self.current_filter.sequence_id,
                                 self.current_filter.incomplete_only)


__all__ = ["AccountFilter", "AccountFilterBar"]
