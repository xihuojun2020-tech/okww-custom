# -*- coding: utf-8 -*-
"""下拉多选配置组件：按钮显示已选摘要，点击展开下拉面板，面板内为带勾选的选项列表。

用于「每周乐园检查日」等需要多选但希望界面紧凑的配置项。
与 LabelAndMultiSelection（横向一排勾选框）相比：不占横向空间，交互为下拉式。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton, QMenu, QWidgetAction, QVBoxLayout, QWidget
from qfluentwidgets import CheckBox

from ok import og
from ok.gui.tasks.ConfigLabelAndWidget import ConfigLabelAndWidget


class LabelAndDropDownMultiSelect(ConfigLabelAndWidget):

    def __init__(self, config_desc, options, config, key: str):
        super().__init__(config_desc, config, key)
        self.key = key
        self.tr_dict = {}
        self.user_action = True
        for option in options:
            tr = og.app.tr(option)
            self.tr_dict[tr] = option

        # 下拉按钮：显示已选摘要
        from qfluentwidgets import DropDownPushButton
        self.button = DropDownPushButton('', self)
        self.button.setMenu(self._build_menu())
        self.add_widget(self.button)

        self.update_value()

    def _build_menu(self):
        # DropDownPushButton 要求 RoundMenu（内部用 menu.view 做下拉动画）
        from qfluentwidgets import RoundMenu
        menu = RoundMenu(parent=self)
        for tr in self.tr_dict:
            checkbox = CheckBox(tr)
            checkbox.setParent(self)
            checkbox.toggled.connect(self.check_changed)
            action = QWidgetAction(menu)
            action.setDefaultWidget(checkbox)
            menu.addAction(action)
        return menu

    def _selected_values(self):
        selected = []
        for tr, checkbox in self._all_checkboxes().items():
            if checkbox.isChecked():
                selected.append(self.tr_dict[tr])
        return selected

    def _all_checkboxes(self):
        result = {}
        for action in self.button.menu().actions():
            w = action.defaultWidget()
            if isinstance(w, CheckBox):
                result[w.text()] = w
        return result

    def check_changed(self, checked):
        if self.user_action:
            self.update_config(self._selected_values())
            self._update_button_text()

    def _update_button_text(self):
        # 按钮文本用翻译后的选项（下拉里中文，选完展示也保持中文）
        selected = []
        for tr, checkbox in self._all_checkboxes().items():
            if checkbox.isChecked():
                selected.append(tr)
        if selected:
            self.button.setText(', '.join(selected))
        else:
            self.button.setText(og.app.tr('无') if og.app.tr('无') != '无' else '未选择')

    def update_value(self):
        self.user_action = False
        current = self.config[self.key] or []
        for tr, checkbox in self._all_checkboxes().items():
            checkbox.setChecked(self.tr_dict[tr] in current)
        self.user_action = True
        self._update_button_text()
