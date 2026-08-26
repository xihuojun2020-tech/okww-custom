"""Integrated account configuration, sequences, and maintenance page."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QSizePolicy
from qfluentwidgets import FluentIcon

from ok.gui.widget.CustomTab import CustomTab
from src.gui.AccountConfigTab import AccountConfigTab
from src.gui.SequenceManagementTab import SequenceManagementTab
from src.gui.SectionPanel import SectionPanel
from src.gui.AccountChangeEvent import AccountChangeEvent


class AccountSettingsTab(CustomTab):
    account_changed = Signal(object)

    def __init__(self, maintenance_tab=None):
        super().__init__()
        from ok.gui.settings.SettingTab import SettingTab
        self.account_tab = AccountConfigTab()
        self.sequence_tab = SequenceManagementTab()
        self.account_tab.changed.connect(self._on_account_changed)
        self.sequence_tab.changed.connect(self._on_account_changed)
        self.maintenance_tab = maintenance_tab or SettingTab(account_maintenance_only=True)
        self.section_panels = []
        for title, widget in (
                ("账号配置", self.account_tab),
                ("序列配置", self.sequence_tab),
                ("导入导出、备份与完整性", self.maintenance_tab)):
            section = SectionPanel(title, parent=self.view)
            # Account/sequence editors are CustomTab scroll areas for
            # standalone use. In this hub, embed their content widget directly
            # so the three sections render as one flat page without nested
            # scroll regions.
            content = getattr(widget, "view", widget)
            if content is not widget:
                # QScrollArea keeps resizing its widget even after a direct
                # reparent. Detach it first so the section layout becomes the
                # sole geometry owner; otherwise the view remains at its old
                # size hint (about 640 px) and leaves the right side blank.
                take_widget = getattr(widget, "takeWidget", None)
                if callable(take_widget):
                    take_widget()
                content.setParent(section)
            # A CustomTab's view is normally sized by its own QScrollArea.
            # Once embedded here that owner is gone, so preserve the vertical
            # policy but explicitly make the content consume the section width.
            content_policy = content.sizePolicy()
            content_policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
            content.setSizePolicy(content_policy)
            section.add_widget(content, stretch=1)
            self.section_panels.append(section)
            self.add_widget(section, stretch=1)

    def _on_account_changed(self, event: AccountChangeEvent):
        """Refresh sibling panels without destroying an unsaved account draft."""
        if not isinstance(event, AccountChangeEvent):
            return
        if event.kind == "sequence_changed":
            self.account_tab.refresh_sequences()
        else:
            selected_sequence = self.sequence_tab._selected()
            self.sequence_tab.refresh(
                sequence_id=selected_sequence.sequence_id if selected_sequence else None)
        self.account_changed.emit(event)

    def refresh_all(self):
        """Reload both account panels after import/restore/repair operations."""
        self.account_tab.refresh()
        self.sequence_tab.refresh()
        self.account_changed.emit(AccountChangeEvent("graph_refreshed"))

    @property
    def name(self): return "账号设置"

    @property
    def icon(self): return FluentIcon.PEOPLE


__all__ = ["AccountSettingsTab"]
