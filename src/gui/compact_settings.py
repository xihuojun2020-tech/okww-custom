"""Scoped density changes for account/tools pages, without touching task UI."""
from PySide6.QtWidgets import QGroupBox
from src.gui.FlatSettingRow import FlatSettingRow
from src.gui.SectionPanel import SectionPanel


def compact_settings(root, *, account=False):
    from ok.gui.tasks.ConfigCard import ConfigCard
    for card in root.findChildren(ConfigCard):
        card.setStyleSheet('QWidget#configSection { border: 0; }')
        card.rootLayout.setContentsMargins(0, 0, 0, 0)
        card.rootLayout.setSpacing(4)
        card.viewLayout.setContentsMargins(8, 4, 8, 8)
    for section in root.findChildren(SectionPanel):
        section.setStyleSheet('QWidget#codexSection { border: 0; }')
        section.layout().setContentsMargins(0, 4, 0, 8)
        section.layout().setSpacing(4)
        section.content_layout.setSpacing(4)
        if account:
            section.layout().setContentsMargins(0, 0, 0, 4)
            section.layout().setSpacing(2)
            section.content_layout.setSpacing(2)
            section.header.setMinimumHeight(40)
            section.header.layout_row.setContentsMargins(8, 4, 8, 4)
    for row in root.findChildren(FlatSettingRow):
        row.layout().setContentsMargins(8, 4, 8, 4)
        if account:
            row.layout().setContentsMargins(8, 3, 8, 3)
    for group in root.findChildren(QGroupBox):
        group.setStyleSheet('QGroupBox { border: 0; margin-top: 12px; padding-top: 8px; }')
