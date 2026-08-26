# coding:utf-8
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import InfoBar, Theme
from qfluentwidgets import (SettingCardGroup, ComboBoxSettingCard, OptionsSettingCard, PushSettingCard)

from ok import og
from ok.gui.common.config import cfg
from ok.gui.settings.GlobalConfigCard import GlobalConfigCard
from ok.gui.widget.Tab import Tab
from ok.util.GlobalConfig import APP_LAUNCHER_OPTION_NAME


class SettingTab(Tab):
    """ Setting interface """

    def __init__(self, account_maintenance_only=False):
        super().__init__()
        self.is_bottom_auxiliary = True
        self.account_maintenance_only = account_maintenance_only
        self.basic_group = SettingCardGroup(
            self.tr('App Config'))
        if not account_maintenance_only:
            self.vBoxLayout.addWidget(self.basic_group)

        self.languageCard = ComboBoxSettingCard(
            cfg.language,
            FIF.LANGUAGE,
            self.tr('Language'),
            self.tr('Set your preferred language'),
            texts=['简体中文', '繁體中文', 'English', "Español", "日本語", "한국인", self.tr('Use system setting')],
            parent=self.basic_group
        )
        self.themeCard = OptionsSettingCard(
            cfg.themeMode,
            FIF.BRUSH,
            self.tr('Application Theme'),
            self.tr("Change the appearance of the application"),
            texts=[
                self.tr('Light'), self.tr('Dark'),
                self.tr('Use system setting')
            ],
            parent=self.basic_group
        )
        # The personal build uses a fixed light shell; keep the setting visible
        # as information but prevent a runtime switch to dark/auto mode.
        try:
            cfg.set(cfg.themeMode, Theme.LIGHT)
        except Exception:
            cfg.themeMode.value = Theme.LIGHT
        self.themeCard.setEnabled(False)
        # 数据设置：账号配置导出/导入
        self.data_group = SettingCardGroup(
            self.tr('Data Config'))
        if account_maintenance_only:
            self.vBoxLayout.addWidget(self.data_group)

        self.export_account_card = PushSettingCard(
            self.tr('导出账号配置'),
            FIF.DOWNLOAD,
            self.tr('账号配置'),
            self.tr('从已验证总配置导出账号配置包 v2（含序列、运行数据和清单）'),
            parent=self.data_group
        )
        self.import_account_card = PushSettingCard(
            self.tr('导入账号配置'),
            FIF.UP,
            self.tr('账号配置'),
            self.tr('导入账号配置包（先预检摘要，再二次确认并事务恢复）'),
            parent=self.data_group
        )
        self.verify_backup_card = PushSettingCard(
            self.tr('验证备份'), FIF.INFO,
            self.tr('配置备份'),
            self.tr('检查选定备份的文件缺失、额外文件和 SHA-256 差异'),
            parent=self.data_group
        )
        self.restore_backup_card = PushSettingCard(
            self.tr('恢复备份'), FIF.SYNC,
            self.tr('配置备份'),
            self.tr('预览恢复摘要并确认后事务恢复配置'),
            parent=self.data_group
        )
        self.repair_sequences_card = PushSettingCard(
            self.tr('恢复旧版遗漏序列'), FIF.SYNC,
            self.tr('账号序列'),
            self.tr('从旧版多账号任务文件恢复未锚定的序列'),
            parent=self.data_group
        )
        self.integrity_card = PushSettingCard(
            self.tr('检查账号完整性'), FIF.INFO,
            self.tr('账号完整性'),
            self.tr('检查总配置、工作投影和接受指纹，并打开安全审查'),
            parent=self.data_group
        )
        # 配置自动备份目录（每天首次启动自动备份所有配置）
        self.backup_config_card = GlobalConfigCard(
            og.executor.global_config.get_config('Config Backup'),
            __import__('config', fromlist=['config_backup_option']).config_backup_option,
        )
        self.backup_config_card.setParent(self.data_group)
        self.data_group.addSettingCard(self.backup_config_card)
        self.config_groups = []
        self.__initWidget()

    def __initWidget(self):
        self.__initLayout()
        self.add_global_config()
        self.__connectSignalToSlot()

    def __initLayout(self):
        if self.account_maintenance_only:
            self.data_group.addSettingCard(self.export_account_card)
            self.data_group.addSettingCard(self.import_account_card)
            self.data_group.addSettingCard(self.verify_backup_card)
            self.data_group.addSettingCard(self.restore_backup_card)
            self.data_group.addSettingCard(self.repair_sequences_card)
            self.data_group.addSettingCard(self.integrity_card)
        else:
            self.basic_group.addSettingCard(self.themeCard)
            self.basic_group.addSettingCard(self.languageCard)

    def _get_daily_task(self):
        """获取 DailyTask 实例（其方法负责读写 daily_profiles.json）。"""
        try:
            from src.task.DailyTask import DailyTask
            return og.executor.get_task_by_class(DailyTask)
        except Exception:
            return None

    def export_accounts(self):
        task = self._get_daily_task()
        if task is not None:
            task.export_account_config()
        else:
            InfoBar.warning(
                self.tr('Daily Task 未加载'),
                self.tr('无法找到每日任务实例，请稍后再试'),
                duration=2000,
                parent=self
            )

    def import_accounts(self):
        task = self._get_daily_task()
        if task is not None:
            task.import_account_config()
        else:
            InfoBar.warning(
                self.tr('Daily Task 未加载'),
                self.tr('无法找到每日任务实例，请稍后再试'),
                duration=2000,
                parent=self
            )

    def verify_backup(self):
        task = self._get_daily_task()
        if task is not None and hasattr(task, 'verify_backup'):
            task.verify_backup()
        else:
            InfoBar.warning(self.tr('备份服务不可用'), self.tr('请稍后再试'), duration=2000, parent=self)

    def restore_backup(self):
        task = self._get_daily_task()
        if task is not None and hasattr(task, 'restore_backup'):
            task.restore_backup()
        else:
            InfoBar.warning(self.tr('备份服务不可用'), self.tr('请稍后再试'), duration=2000, parent=self)

    def repair_legacy_sequences(self):
        task = self._get_daily_task()
        if task is not None and hasattr(task, 'repair_legacy_sequences'):
            task.repair_legacy_sequences()
        else:
            InfoBar.warning(self.tr('序列修复服务不可用'), self.tr('请稍后再试'), duration=2000, parent=self)

    def review_account_integrity(self):
        window = getattr(og, 'main_window', None)
        callback = getattr(window, 'review_account_integrity', None)
        if callable(callback):
            callback()
        else:
            InfoBar.warning(self.tr('完整性服务不可用'), self.tr('请稍后再试'), duration=2000, parent=self)

    def goto_config(self, key):
        to_scroll = None
        for config in self.config_groups:
            if config.has_key(key):
                config.setExpand(True)
                to_scroll = config
            else:
                config.setExpand(False)
        # if to_scroll:
        #     self.scroll()

    def add_global_config(self):
        if self.account_maintenance_only:
            return
        global_configs = og.executor.global_config.get_all_visible_configs()
        if global_configs:
            global_configs.sort(key=lambda item: item[0] != APP_LAUNCHER_OPTION_NAME)
            for name, config, option in global_configs:
                if getattr(option, 'show_at_tab', False):
                    continue
                card = GlobalConfigCard(config, option)
                if name == 'Basic Options':
                    card.setExpand(True)
                self.basic_group.addSettingCard(card)
                self.config_groups.append(card)

    def __showRestartTooltip(self):
        """ show restart tooltip """
        InfoBar.success(
            self.tr('Updated successfully'),
            self.tr('Configuration takes effect after restart'),
            duration=1500,
            parent=self
        )

    def __connectSignalToSlot(self):
        """ connect signal to slot """
        cfg.appRestartSig.connect(self.__showRestartTooltip)

        self.export_account_card.clicked.connect(self.export_accounts)
        self.import_account_card.clicked.connect(self.import_accounts)
        self.verify_backup_card.clicked.connect(self.verify_backup)
        self.restore_backup_card.clicked.connect(self.restore_backup)
        self.repair_sequences_card.clicked.connect(self.repair_legacy_sequences)
        self.integrity_card.clicked.connect(self.review_account_integrity)
