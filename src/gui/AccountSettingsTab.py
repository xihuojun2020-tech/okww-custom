"""The single account-plan and sequence editor."""

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QLayout
from qfluentwidgets import FluentIcon

from ok.gui.widget.CustomTab import CustomTab
from src.gui.AccountConfigTab import AccountConfigTab
from src.gui.SequenceManagementTab import SequenceManagementTab
from src.gui.SectionPanel import SectionPanel
from src.gui.AccountChangeEvent import AccountChangeEvent


class AccountSettingsTab(CustomTab):
    account_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self.account_tab = AccountConfigTab()
        self.sequence_tab = SequenceManagementTab()
        self.account_tab.changed.connect(self._on_account_changed)
        self.sequence_tab.changed.connect(self._on_account_changed)
        section = SectionPanel('账号序列', parent=self.account_tab.settings_host)
        section.set_flat()
        section.title_label.hide()
        section.add_embedded_widget(self.sequence_tab)
        self.section_panels = [section]
        self.account_tab.settings_layout.addWidget(section)
        self.account_tab._sequence_panel = section
        section.hide()
        self.account_tab._refresh_sequence_views = self._refresh_sequence_views
        self.sequence_tab.account_requested.connect(self._select_account)
        self.add_widget(self.account_tab, stretch=1)
        self.vBoxLayout.setSizeConstraint(QLayout.SetDefaultConstraint)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        from src.gui.compact_settings import compact_settings
        compact_settings(self, account=True)

    def _refresh_sequence_views(self):
        self.sequence_tab.refresh()

    def _select_account(self, identity):
        index = self.account_tab.profile_combo.findData(identity)
        if index >= 0:
            self.account_tab.profile_combo.setCurrentIndex(index)
            self.account_tab._select_route('identity')

    def _on_account_changed(self, event: AccountChangeEvent):
        """Refresh sibling panels without destroying an unsaved account draft."""
        if not isinstance(event, AccountChangeEvent):
            return
        if event.choices_changed:
            self.account_tab.refresh_account_choices()
        if event.kind == "sequence_changed":
            self.account_tab.refresh_sequences()
        else:
            selected_sequence = self.sequence_tab._selected()
            self.sequence_tab.refresh(
                sequence_id=selected_sequence.sequence_id if selected_sequence else None)
        self.account_changed.emit(event)

    def refresh_all(self):
        """Reload both account panels after import/restore/repair operations."""
        self.account_tab.refresh(preserve_draft=True)
        self.sequence_tab.refresh()
        self.account_changed.emit(AccountChangeEvent("graph_refreshed"))

    @property
    def name(self): return "账号"

    @property
    def icon(self): return FluentIcon.PEOPLE


__all__ = ["AccountSettingsTab"]
