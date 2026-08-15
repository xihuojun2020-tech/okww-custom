# coding:utf-8
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import InfoBar, setTheme
from qfluentwidgets import (SettingCardGroup, ComboBoxSettingCard, OptionsSettingCard, PushSettingCard)

from ok import og
from ok.gui.common.config import cfg
from ok.gui.settings.GlobalConfigCard import GlobalConfigCard
from ok.gui.widget.Tab import Tab
from ok.util.GlobalConfig import APP_LAUNCHER_OPTION_NAME


class SettingTab(Tab):
    """ Setting interface """

    def __init__(self):
        super().__init__()
        self.basic_group = SettingCardGroup(
            self.tr('App Config'))
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
        # 数据设置：账号配置导出/导入
        self.data_group = SettingCardGroup(
            self.tr('Data Config'))
        self.vBoxLayout.addWidget(self.data_group)

        self.export_account_card = PushSettingCard(
            self.tr('导出账号配置'),
            FIF.DOWNLOAD,
            self.tr('账号配置'),
            self.tr('导出全部账号方案（含完成时间）与激活方案为 JSON 文件，便于备份或迁移到其他电脑'),
            parent=self.data_group
        )
        self.import_account_card = PushSettingCard(
            self.tr('导入账号配置'),
            FIF.UP,
            self.tr('账号配置'),
            self.tr('从 JSON 文件恢复账号方案（导入前自动备份现有配置）'),
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
        self.basic_group.addSettingCard(self.themeCard)
        self.basic_group.addSettingCard(self.languageCard)
        self.data_group.addSettingCard(self.export_account_card)
        self.data_group.addSettingCard(self.import_account_card)

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

        self.themeCard.optionChanged.connect(lambda ci: setTheme(cfg.get(ci)))
        self.export_account_card.clicked.connect(self.export_accounts)
        self.import_account_card.clicked.connect(self.import_accounts)
