"""Apply the shared compact rhythm to embedded framework settings."""
from PySide6.QtWidgets import QGroupBox
from src.gui.FlatSettingRow import FlatSettingRow
from src.gui.SectionPanel import SectionPanel


def compact_settings(root, *, account=False):
    from ok.gui.tasks.ConfigCard import ConfigCard
    for card in root.findChildren(ConfigCard):
        card.rootLayout.setContentsMargins(0, 0, 0, 0)
        card.rootLayout.setSpacing(8)
        card.viewLayout.setContentsMargins(16, 8, 16, 16)
    for row in root.findChildren(FlatSettingRow):
        row.layout().setContentsMargins(0, 8, 0, 8)
    for group in root.findChildren(QGroupBox):
        group.setStyleSheet('QGroupBox { border: 0; margin-top: 12px; padding-top: 8px; }')
