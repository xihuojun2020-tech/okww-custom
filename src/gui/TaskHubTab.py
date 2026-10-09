from qfluentwidgets import FluentIcon
from ok.gui.widget.CustomTab import CustomTab
from ok.gui.tasks.OneTimeTaskTab import OneTimeTaskTab
from src.gui.navigation_sections import TASKS
from src.gui.SectionPanel import SectionPanel
from PySide6.QtCore import QSignalBlocker
from ok import og
from ok.gui.Communicate import communicate
from src.gui.ChoiceControls import QtComboBox
from src.account_display import account_option_items
from src.config_integrity import ConfigIntegrityBlocked
from src.task.MultiAccountDailyTask import CURRENT_SEQUENCE, CURRENT_ACCOUNT, UNREGISTERED_ACCOUNT


class TaskHubTab(CustomTab):
    def __init__(self):
        super().__init__()
        self.account_panel = SectionPanel('当前账号', parent=self.view, collapsible=True)
        self.sequence_combo = QtComboBox(self.account_panel)
        self.account_combo = QtComboBox(self.account_panel)
        self.account_panel.add_row('序列', self.sequence_combo)
        self.account_panel.add_row('账号', self.account_combo)
        self.sequence_combo.currentIndexChanged.connect(self._select_sequence)
        self.account_combo.currentIndexChanged.connect(self._select_account)
        self.add_widget(self.account_panel)
        self.task_tab = OneTimeTaskTab(section=TASKS, group_tasks=True, fluent_sample=True)
        self.section_panels = [SectionPanel("任务", parent=self.view)]
        self.section_panels[0].add_embedded_widget(self.task_tab)
        self.section_panels[0].title_label.setProperty('role', 'pageTitle')
        self.section_panels[0].set_flat()
        self.add_widget(self.section_panels[0])
        communicate.task.connect(self.refresh_account_choices)
        communicate.task_list_updated.connect(self.refresh_account_choices)
        self.task_tab.timer.timeout.connect(self.refresh_account_choices)
        self.refresh_account_choices()

    def _account_owner(self):
        # Reuse the saved multi-daily selection as the single source. Upgrades
        # retain it even when the old standalone daily selection was different.
        return next((task for task in og.executor.onetime_tasks
                     if type(task).__name__ == 'MultiAccountDailyTask'), None)

    def refresh_account_choices(self, *_):
        owner = self._account_owner()
        if owner is None:
            self.account_panel.set_summary('暂无账号配置')
            self.sequence_combo.setEnabled(False)
            self.account_combo.setEnabled(False)
            return
        busy = any(task.enabled for task in og.executor.onetime_tasks)
        self.sequence_combo.setEnabled(not busy)
        self.account_combo.setEnabled(not busy)
        try:
            sequences = owner.get_sequence_names()
            sequence = owner.get_current_sequence()
            accounts = owner.get_sequence_accounts(sequence)
            selected = owner.config.get(CURRENT_ACCOUNT) or ''
            verification = getattr(og.executor, '_account_feature_run', None)
            if busy and verification is not None:
                profiles = owner._load_profiles()
                selected = next(name for name, profile in profiles.items()
                                if profile['profile_id'] == verification.profile_id)
                sequence = next((name for name in sequences if selected in owner.get_sequence_accounts(name)), sequence)
                accounts = owner.get_sequence_accounts(sequence)
            items = account_option_items(['', UNREGISTERED_ACCOUNT] + accounts)
        except ConfigIntegrityBlocked as error:
            self.account_panel.set_summary(str(error))
            self.sequence_combo.setEnabled(False)
            self.account_combo.setEnabled(False)
            return
        # The task-page timer also updates the running account. Rebuild only
        # when values/labels change so an open dropdown stays usable.
        for combo, choices, value in (
                (self.sequence_combo, [(name, name) for name in sequences], sequence),
                (self.account_combo, items, selected)):
            with QSignalBlocker(combo):
                if [(combo.itemData(i), combo.itemText(i)) for i in range(combo.count())] != choices:
                    combo.clear()
                    for key, label in choices:
                        combo.addItem(label or '请选择账号', key)
                combo.setCurrentIndex(combo.findData(value))
        label = dict(items).get(selected, '')
        self.account_panel.set_summary('无序列 · 不认证、不写入账号进度（每日、海墟、深塔及多账号任务除外）'
                                       if selected == UNREGISTERED_ACCOUNT else
                                       f'{sequence} · {label}' if label else f'{sequence} · 请选择账号')

    def _select_sequence(self, index):
        if index < 0:
            return
        owner = self._account_owner()
        owner.config[CURRENT_SEQUENCE] = self.sequence_combo.itemData(index)
        if owner.config.get(CURRENT_ACCOUNT) != UNREGISTERED_ACCOUNT and owner.config.get(CURRENT_ACCOUNT) not in owner.get_sequence_accounts():
            owner.config[CURRENT_ACCOUNT] = ''
        self.refresh_account_choices()

    def _select_account(self, index):
        if index >= 0:
            self._account_owner().config[CURRENT_ACCOUNT] = self.account_combo.itemData(index)
            self.refresh_account_choices()

    @property
    def name(self): return "任务"

    @property
    def icon(self): return FluentIcon.BOOK_SHELF
