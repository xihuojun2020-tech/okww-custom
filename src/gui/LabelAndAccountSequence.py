# -*- coding: utf-8 -*-
"""账号序列配置组件：为多账号每日任务设置「本轮要打的账号」列表。

交互：
  - 最多 10 个位置，每个位置一个下拉框（ComboBox）
  - 下拉选项 = 「无」 + 尚未被选中的账号（含本序列前面位置 + 其他序列已选的账号，
    保证一个账号在全部序列中只会出现一次）
  - 每次点开下拉都会重新计算选项（其他序列的账号配置变化后也能正确剔除）
  - 某位置选「无」表示该位置没有账号（序列到此结束）

存储：config 值 = ['账号A', '账号B', ...]，截断到第一个「无」之前；
「无」只是结束标记，不会被当作账号配置写入。
"""

import re

from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel
from qfluentwidgets import ComboBox

from ok import og
from ok.gui.tasks.ConfigLabelAndWidget import ConfigLabelAndWidget

NONE_LABEL = '无'
# 识别 key 是否为「序列 N 账号」格式（用于跨序列去重）
SEQ_KEY_PATTERN = re.compile(r'序列\s*(\d+)\s*账号')


class LabelAndAccountSequence(ConfigLabelAndWidget):

    def __init__(self, config_desc, options, config, key: str, max_count=10,
                 last_completed_provider=None):
        super().__init__(config_desc, config, key)
        self.key = key
        self.options = list(options)
        self.max_count = max_count
        self.user_action = True
        self.combos = []
        self.last_completed_labels = []
        # 上次完成时间提供者（callable：账号名 → 时间字符串），只读展示，不可修改
        self.last_completed_provider = last_completed_provider
        # 自己所属的序列号（「序列 N 账号」格式），用于排除自己算跨序列占用
        m = SEQ_KEY_PATTERN.search(key)
        self.own_seq_index = int(m.group(1)) - 1 if m else None

        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(2)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.add_layout(self.content_layout, stretch=1)

        for i in range(max_count):
            row = QHBoxLayout()
            row.setSpacing(6)
            label = QLabel(f'账号{i + 1}')
            label.setObjectName('titleLabel')
            label.setFixedWidth(46)
            combo = ComboBox()
            combo.setMinimumWidth(220)
            combo.currentIndexChanged.connect(lambda idx, pos=i: self._on_change(pos))
            # 点击下拉瞬间刷新选项（保证其他序列的账号配置变化后也能正确剔除）
            combo.pressed.connect(self._refresh_all)
            row.addWidget(label)
            row.addWidget(combo)
            # 上次完成时间（只读）
            last_label = QLabel('')
            last_label.setObjectName('contentLabel')
            last_label.setStyleSheet('color: gray;')
            row.addWidget(last_label)
            row.addStretch(1)
            self.content_layout.addLayout(row)
            self.combos.append(combo)
            self.last_completed_labels.append(last_label)

        self.update_value()

    # ---------- 上次完成时间（只读） ----------

    def _update_last_completed_labels(self):
        if self.last_completed_provider is None:
            return
        for i, combo in enumerate(self.combos):
            text = combo.currentText()
            if text and text != NONE_LABEL:
                time_str = self.last_completed_provider(text)
                if time_str:
                    self.last_completed_labels[i].setText(f'上次: {time_str}')
                else:
                    self.last_completed_labels[i].setText('')
            else:
                self.last_completed_labels[i].setText('')

    # ---------- 选项构建 ----------

    def _other_sequences_used(self):
        """其他序列（非本组件所属序列）已选的账号合集。"""
        if self.own_seq_index is None:
            return []
        used = set()
        for i in range(1, 6):
            if i - 1 == self.own_seq_index:
                continue
            seq = self.config.get(f'序列 {i} 账号') or []
            for acc in seq:
                if acc and acc != NONE_LABEL:
                    used.add(acc)
        return used

    def _used_before(self, pos):
        """前 pos 个位置已选的账号（非无）。"""
        used = []
        for i in range(pos):
            text = self.combos[i].currentText()
            if text and text != NONE_LABEL:
                used.append(text)
        return used

    def _build_items(self, pos):
        """位置 pos 的下拉选项：[无] + 尚未被选中的账号（本序列前面位置 + 其他序列已选）。"""
        used = set(self._used_before(pos)) | self._other_sequences_used()
        available = [o for o in self.options if o not in used]
        return [NONE_LABEL] + available

    def _refresh_all(self):
        """重建全部位置的选项（点开下拉时调用，保证跨序列去重最新）。"""
        self.user_action = False
        try:
            current_vals = [c.currentText() for c in self.combos]
            for i in range(self.max_count):
                combo = self.combos[i]
                items = self._build_items(i)
                combo.blockSignals(True)
                current = current_vals[i]
                combo.clear()
                combo.addItems(items)
                new_index = items.index(current) if current in items else 0
                combo.setCurrentIndex(new_index)
                combo.blockSignals(False)
        finally:
            self.user_action = True

    def _config_list(self):
        """从下拉状态提取 config 列表（截断到第一个「无」）。"""
        result = []
        for combo in self.combos:
            text = combo.currentText()
            if not text or text == NONE_LABEL:
                break
            result.append(text)
        return result

    # ---------- 事件 ----------

    def _on_change(self, pos):
        if not self.user_action:
            return
        self.update_config(self._config_list())
        # 后续位置重新构建选项（剔除本位置刚选的账号）
        self._refresh_from(pos + 1)
        self._update_last_completed_labels()

    def _refresh_from(self, start):
        self.user_action = False
        try:
            for i in range(start, self.max_count):
                combo = self.combos[i]
                current = combo.currentText()
                items = self._build_items(i)
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(items)
                new_index = items.index(current) if current in items else 0
                combo.setCurrentIndex(new_index)
                combo.blockSignals(False)
        finally:
            self.user_action = True

    def update_value(self):
        self.user_action = False
        try:
            current = self.config[self.key] or []
            for i in range(self.max_count):
                combo = self.combos[i]
                items = self._build_items(i)
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(items)
                if i < len(current) and current[i] in items:
                    combo.setCurrentIndex(items.index(current[i]))
                else:
                    combo.setCurrentIndex(0)
                combo.blockSignals(False)
        finally:
            self.user_action = True
        self._update_last_completed_labels()
