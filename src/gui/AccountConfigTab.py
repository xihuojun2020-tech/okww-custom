"""PC account task-configuration editor tab."""

import json
import copy
import logging
from time import perf_counter
from functools import partial

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QPushButton, QInputDialog, QDialog,
                               QDialogButtonBox,
                               QVBoxLayout, QWidget, QLineEdit, QSizePolicy, QScrollArea,
                               QTreeWidget, QTreeWidgetItem, QStackedWidget, QLayout, QMenu)
from qfluentwidgets import BodyLabel, FluentIcon

from ok.gui.widget.CustomTab import CustomTab
from src.account_config_editor import AccountConfigEditor, ProfileDraft, sanitize_error
from src.account_display import account_display_label
from src.account_rebind_service import AccountRebindService, rebind_confirmation_identity
from src.account_repository import AccountRepository, AccountRepositoryError, get_default_repository
from src.gui.ForgeryQuotaWidget import ForgeryQuotaWidget
from src.task.forgery_quota_plan import FORGERY_GOALS
from src.gui.WorldBossMaterialPlanWidget import WorldBossMaterialPlanWidget
from src.task.world_boss_material_plan import MATERIAL_TARGETS, material_plan
from src.gui.WeeklyBossPlanWidget import WeeklyBossPlanWidget
from src.task.weekly_boss_plan import WEEKLY_PLAN, weekly_plan, plan_enabled
from src.account_field_metadata import (account_field_metadata, localize_account_value,
                                        restore_account_value, normalize_weekday,
                                        GARDEN_MODE_DAILY, GARDEN_EXECUTION_MODES)
from src.gui.AccountChangeEvent import AccountChangeEvent
from src.gui.BackgroundOperation import BackgroundOperation
from src.gui.FlatSettingRow import FlatSettingRow


from src.gui.ChoiceControls import QtComboBox as QComboBox
ClickOnlyComboBox = QComboBox


class _AccountStatusLabel(BodyLabel):
    def setText(self, text):
        super().setText(text)
        self.setVisible(bool(text) and text not in ('等待操作', '已载入独立草稿'))


def recording_defaults():
    from ok import og
    task = next((task for task in getattr(getattr(og, 'executor', None), 'onetime_tasks', [])
                 if type(task).__name__ == 'DailyTask'), None)
    config = getattr(task, 'config', None) or {}
    return {'Screenshot After Daily Task': config.get('Screenshot After Daily Task', True),
            'Record After Daily Task': config.get('Record After Daily Task', True),
            'Record Duration': config.get('Record Duration', 1.5)}


class NestSelection(QWidget):
    changed = Signal()

    def __init__(self, value, nightmare_value=None, parent=None):
        super().__init__(parent)
        from src.nightmare_nests import NEST_NAMES, NIGHTMARE_NAMES
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(4)
        self.residual_heading = QLabel('残象聚落', self)
        self.nightmare_heading = QLabel('梦魇聚落（补充）', self)
        self.boxes = {}
        self.nightmare_boxes = {}
        for row, name in enumerate(NEST_NAMES, 1):
            box = QCheckBox(name, self)
            box.toggled.connect(lambda *_: self.changed.emit())
            self.boxes[name] = box
        for row, name in enumerate(NIGHTMARE_NAMES, 1):
            box = QCheckBox(name, self)
            box.toggled.connect(lambda *_: self.changed.emit())
            self.nightmare_boxes[name] = box
        self.set_values(value)
        self.set_nightmare_values(nightmare_value or [])
        self._arrange()

    def _arrange(self):
        while self.grid.count():
            self.grid.takeAt(0)
        if self.width() >= 620:
            self.grid.addWidget(self.residual_heading, 0, 0)
            self.grid.addWidget(self.nightmare_heading, 0, 1)
            for row, box in enumerate(self.boxes.values(), 1):
                self.grid.addWidget(box, row, 0)
            for row, box in enumerate(self.nightmare_boxes.values(), 1):
                self.grid.addWidget(box, row, 1)
        else:
            self.grid.addWidget(self.residual_heading, 0, 0)
            for row, box in enumerate(self.boxes.values(), 1):
                self.grid.addWidget(box, row, 0)
            start = len(self.boxes) + 1
            self.grid.addWidget(self.nightmare_heading, start, 0)
            for row, box in enumerate(self.nightmare_boxes.values(), start + 1):
                self.grid.addWidget(box, row, 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange()

    def set_values(self, value):
        selected = set(self.boxes if value is None else value)
        for name, box in self.boxes.items():
            box.blockSignals(True)
            box.setChecked(name in selected)
            box.blockSignals(False)

    def values(self):
        return [name for name, box in self.boxes.items() if box.isChecked()]

    def set_nightmare_values(self, value):
        selected = set(value or [])
        for name, box in self.nightmare_boxes.items():
            box.blockSignals(True)
            box.setChecked(name in selected)
            box.blockSignals(False)

    def nightmare_values(self):
        return [name for name, box in self.nightmare_boxes.items() if box.isChecked()]


class FixedRecordingPages(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        from src.recording_policy import RECORDING_PAGES
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for page in RECORDING_PAGES:
            control = QCheckBox(page, self)
            control.setChecked(True)
            layout.addWidget(control)
        self.setEnabled(False)


def _select_account_choice(widget, key, value):
    if key in ('Which Tacet Suppression to Farm', 'Which Forgery Challenge to Farm') and value is None:
        value = 1
    if key == 'Which Tacet Suppression to Farm':
        from src.task.tacet_targets import tacet_serial
        try:
            tacet_serial(value)
        except ValueError:
            widget.setCurrentIndex(-1)
            widget.setToolTip('无音区目标无效，请重新选择')
            return
    if key == 'Weekly Garden Check Day':
        try:
            value = normalize_weekday(value)
        except ValueError:
            widget.setPlaceholderText('检查日无效，请重新选择')
            widget.setToolTip('旧乐园检查日无效；选择“随每日执行”后重新选择星期才能保存。')
            widget.setCurrentIndex(-1)
            return
    index = widget.findData(value)
    if index < 0 and key in ('Weekly Garden Check Day', 'Garden Execution Mode', 'Which Tacet Suppression to Farm', 'Which Forgery Challenge to Farm'):
        widget.setCurrentIndex(-1)
        widget.setToolTip('选项无效，请重新选择')
    else:
        widget.setCurrentIndex(max(index, 0))


def _read_account_choice(widget, key):
    value = widget.currentData()
    if key == 'Which Tacet Suppression to Farm':
        from src.task.tacet_targets import tacet_serial
        tacet_serial(value)
    if key == 'Which Forgery Challenge to Farm' and value not in range(1, 21):
        raise ValueError('凝素领域目标无效，请重新选择')
    if key == 'Weekly Garden Check Day':
        if widget.currentIndex() < 0:
            raise ValueError('周常乐园检查日无效，请重新选择星期')
        return normalize_weekday(value)
    if key == 'Garden Execution Mode' and value not in GARDEN_EXECUTION_MODES:
        raise ValueError('乐园执行安排无效，请重新选择')
    return value


def _link_garden_controls(widgets):
    mode = widgets.get('Garden Execution Mode')
    check_day = widgets.get('Weekly Garden Check Day')
    if mode is None or check_day is None:
        return
    update = lambda *_: check_day.setEnabled(mode.currentData() == GARDEN_MODE_DAILY)
    mode.currentIndexChanged.connect(update)
    update()


def _link_material_controls(widgets):
    material = widgets.get(MATERIAL_TARGETS)
    target = widgets.get('Which to Farm')
    planner = widgets.get('Material Planner Enabled')
    if material is None:
        return
    def update(*_):
        material.set_fallback(target.currentData() if target else material.fallback,
                              planner.isChecked() if planner else material.planner_enabled)
    if target is not None:
        target.currentIndexChanged.connect(update)
    if planner is not None:
        planner.toggled.connect(update)
    update()


class AccountTemplateDialog(QDialog):
    """Edit the shared task-only template with the same field metadata as account editing."""

    def __init__(self, tasks, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑新账号模板")
        self._tasks = dict(tasks)
        self._tasks.setdefault(WEEKLY_PLAN, [])
        self._tasks.setdefault(MATERIAL_TARGETS, [])
        self._tasks.setdefault(FORGERY_GOALS, [])
        self._tasks.setdefault('Garden Execution Mode', 'closed')
        from src.recording_policy import RECORDING_PAGES
        self._tasks['Record Pages'] = list(RECORDING_PAGES)
        for key, value in recording_defaults().items():
            self._tasks.setdefault(key, value)
        self._widgets = {}
        layout = QVBoxLayout(self)
        layout.addWidget(BodyLabel("模板只复制每日任务设置，不复制账号身份、序列或完成记录。"))
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget(scroll)
        form = QVBoxLayout(content)
        for field in account_field_metadata(self._tasks):
            if field.key in ('Nightmare Which to Farm', 'Nightmare Settlements to Farm', 'Weekly Boss Target',
                             'Material Planner Enabled', 'Auto Farm all Nightmare Nest', 'Farm Nightmare Nest for Daily Echo'):
                continue
            if field.affects_identity or field.key in ("备用识别名称", "备用识别名称内容"):
                continue
            value = self._tasks.get(field.key)
            if field.key == FORGERY_GOALS:
                widget = ForgeryQuotaWidget(self._tasks, parent=self)
            elif field.key == MATERIAL_TARGETS:
                widget = WorldBossMaterialPlanWidget(self._tasks, parent=self)
            elif field.key == WEEKLY_PLAN:
                widget = WeeklyBossPlanWidget(self._tasks, parent=self)
            elif field.key == 'Record Pages':
                widget = FixedRecordingPages(self)
            elif field.key == "Tacet Discord Nests to Farm":
                widget = NestSelection(value, self._tasks.get('Nightmare Settlements to Farm', []), self)
            elif field.editor_type == "bool":
                widget = QCheckBox(self)
                widget.setChecked(bool(value))
            elif field.editor_type == "choice":
                widget = ClickOnlyComboBox(self)
                for option, label in zip(field.options, field.option_labels):
                    widget.addItem(label, option)
                _select_account_choice(widget, field.key, value)
            else:
                widget = QLineEdit(self)
                display = localize_account_value(value)
                widget.setText(json.dumps(display, ensure_ascii=False)
                               if isinstance(display, (list, dict)) else str(display))
            self._widgets[field.key] = widget
            if isinstance(widget, (ForgeryQuotaWidget, WeeklyBossPlanWidget, WorldBossMaterialPlanWidget)):
                form.addWidget(QLabel(field.label, content))
                form.addWidget(widget)
            else:
                form.addWidget(FlatSettingRow(field.label, widget, field.help_text, content))
        _link_garden_controls(self._widgets)
        _link_material_controls(self._widgets)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, parent=self)
        buttons.button(QDialogButtonBox.Save).setText('保存')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        from src.gui.CodexTheme import size_dialog
        size_dialog(self, 680, 560)

    def tasks(self):
        result = dict(self._tasks)
        for key, widget in self._widgets.items():
            if isinstance(widget, ForgeryQuotaWidget):
                result[key] = widget.values()
            elif isinstance(widget, WorldBossMaterialPlanWidget):
                rows = widget.values()
                if result.get(key) != [] or rows != material_plan(result):
                    result[key] = rows
            elif isinstance(widget, WeeklyBossPlanWidget):
                rows = widget.values()
                if result.get(key) != [] or rows != weekly_plan(result):
                    result[key] = rows
                    active = [r['boss'] for r in rows if r['boss'] != '无' and r['limit'] != 0]
                    result['Weekly Boss Target'] = active[0] if active else '无'
            elif key == 'Record Pages':
                continue
            elif isinstance(widget, NestSelection):
                result[key] = widget.values()
                result['Nightmare Settlements to Farm'] = widget.nightmare_values()
            elif isinstance(widget, QCheckBox):
                result[key] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                result[key] = _read_account_choice(widget, key)
            else:
                text = widget.text()
                original = result.get(key)
                if isinstance(original, int):
                    result[key] = int(text)
                elif isinstance(original, float):
                    result[key] = float(text)
                elif isinstance(original, (list, dict)):
                    result[key] = restore_account_value(json.loads(text))
                else:
                    result[key] = restore_account_value(text)
        return result


class NewAccountDialog(QDialog):
    def __init__(self, sequence_ids, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建账号配置")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.short_name = QLineEdit(self)
        self.phone = QLineEdit(self)
        self.nickname = QLineEdit(self)
        self.feature_code = QLineEdit(self)
        self.alias_enable = ClickOnlyComboBox(self)
        self.alias_enable.addItem("无", False)
        self.alias_enable.addItem("使用", True)
        self.alias_text = QLineEdit(self)
        for label, widget in (("账号编号（例如 A5）", self.short_name), ("完整手机号", self.phone),
                              ("游戏昵称", self.nickname), ("游戏内特征码", self.feature_code),
                              ("使用备用识别名称", self.alias_enable),
                              ("备用识别名称内容", self.alias_text)):
            form.addRow(label, widget)
        layout.addLayout(form)
        self.name_preview = QLabel(self)
        self.name_preview.setWordWrap(True)
        layout.addWidget(self.name_preview)
        for field in (self.short_name, self.nickname, self.phone):
            field.textChanged.connect(self.update_name_preview)
        self.update_name_preview()
        group = QGroupBox("加入账号序列", self)
        group_layout = QVBoxLayout(group)
        self.sequence_boxes = {}
        for sequence_id in sequence_ids:
            box = QCheckBox(sequence_id, group)
            self.sequence_boxes[sequence_id] = box
            group_layout.addWidget(box)
        layout.addWidget(group)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, parent=self)
        buttons.button(QDialogButtonBox.Save).setText('创建账号')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        from src.gui.CodexTheme import size_dialog
        size_dialog(self, 560, 420)

    def update_name_preview(self):
        self.name_preview.setText('显示名称：' + account_display_label({
            'display_name': self.short_name.text().strip().upper(),
            'nickname': self.nickname.text().strip(), 'phone': self.phone.text().strip()}))

    def values(self):
        return {
            "display_name": self.short_name.text(),
            "phone": self.phone.text(),
            "nickname": self.nickname.text(),
            "game_feature_code": self.feature_code.text(),
            "alias_enabled": bool(self.alias_enable.currentData()),
            "alias_text": self.alias_text.text(),
            "sequence_ids": tuple(name for name, box in self.sequence_boxes.items() if box.isChecked()),
        }


class AccountConfigTab(CustomTab):
    """Edit only non-identity task fields through a detached draft."""

    changed = Signal(object)

    def __init__(self, editor=None):
        super().__init__()
        repository = editor.repository if editor is not None else (get_default_repository() or AccountRepository())
        self.editor = editor or AccountConfigEditor(repository)
        self.rebind_service = AccountRebindService(self.editor.repository)
        self.draft = None
        self._failed_drafts = {}
        self._draft_cache = {}
        root = QWidget(self.view)
        root.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(root)
        layout.setAlignment(Qt.AlignTop)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        row = QHBoxLayout()
        row.addWidget(QLabel("账号"))
        self.profile_combo = ClickOnlyComboBox(root)
        row.addWidget(self.profile_combo, 1)
        layout.addLayout(row)
        self.metadata = BodyLabel("")
        self.metadata.setWordWrap(True)
        self.draft_status = QLabel('尚未编辑', root)
        self.draft_status.setProperty('role', 'description')
        from src.gui.SectionPanel import SectionPanel
        self.identity_group = SectionPanel("账号识别信息", "登录身份只读；所属序列可勾选调整，保存后生效。", root, collapsible=True)
        self.identity_layout = QFormLayout()
        self.identity_group.content_layout.addLayout(self.identity_layout)
        self.identity_layout.addRow(self.metadata)
        self.identity_widgets = {}
        for key, label in (("phone", "完整手机号"), ("masked_phone", "带星号手机号（切换关键依据）"),
                           ("nickname", "游戏昵称"), ("alternate_login_name", "U…A 备用识别名")):
            widget = QLineEdit(self.identity_group)
            widget.setReadOnly(True)
            widget.setToolTip("身份字段由重新绑定流程修改，普通账号配置保存不会覆盖它")
            self.identity_widgets[key] = widget
            self.identity_layout.addRow(FlatSettingRow(label, widget, parent=self.identity_group))
        self.feature_code_label = QLabel("未绑定（初露峥嵘执行前需核验）", self.identity_group)
        self.reveal_phone = QCheckBox('显示完整手机号', self.identity_group)
        self.reveal_phone.toggled.connect(self._render_identity)
        self.identity_layout.addRow(self.reveal_phone)
        self.feature_code_label.setToolTip("读取游戏右下角特征码并确认绑定；初露峥嵘执行前后核验真实账号")
        self.identity_layout.addRow(FlatSettingRow("游戏内特征码（只读）", self.feature_code_label, parent=self.identity_group))
        self.read_feature_button = QPushButton('读取并绑定特征码', self.identity_group)
        self.read_feature_button.clicked.connect(self.read_feature_code)
        self.identity_layout.addRow(self.read_feature_button)
        self.identity_task_fields = QWidget(self.identity_group)
        self.identity_task_layout = QVBoxLayout(self.identity_task_fields)
        self.identity_task_layout.setContentsMargins(0, 0, 0, 0)
        self.identity_group.content_layout.addWidget(self.identity_task_fields)
        layout.addWidget(self.identity_group)
        from src.gui.AccountReminderPanel import AccountReminderPanel
        self.reminder_panel = AccountReminderPanel(root)
        self.reminder_panel.edited.connect(self._mark_draft_edited)
        layout.addWidget(self.reminder_panel)
        self.sequence_group = QGroupBox("所属序列（勾选后保存即可调整当前账号归属）", self.identity_group)
        self.sequence_layout = QVBoxLayout(self.sequence_group)
        self.sequence_widgets = {}
        self.identity_group.add_widget(self.sequence_group)
        self.form_host = QWidget(root)
        self.form_layout = QFormLayout(self.form_host)
        self.form_layout.setContentsMargins(0, 0, 0, 0)
        self.form_layout.setVerticalSpacing(4)
        self.form_widgets = {}
        layout.addWidget(self.form_host)
        self.task_editor = QPlainTextEdit(root)
        self.task_editor.setPlaceholderText("任务配置 JSON")
        self.task_editor.hide()
        self.json_button = QPushButton("高级 JSON…", root)
        self.json_button.clicked.connect(self.edit_json)
        actions = QHBoxLayout()
        self.preview_button = QPushButton("预览差异", root)
        self.save_button = QPushButton("确认保存", root)
        self.discard_button = QPushButton("丢弃草稿", root)
        self.delete_button = QPushButton("删除当前账号", root)
        self.rebind_button = QPushButton("重新绑定身份", root)
        self.template_button = QPushButton("编辑新账号模板", root)
        self.new_button = QPushButton("新建账号", root)
        self.save_button.setProperty('role', 'primary')
        self.delete_button.setProperty('role', 'danger')
        row.addWidget(self.new_button)
        self.more_button = QPushButton('更多', root)
        menu = QMenu(self.more_button)
        menu.addAction('账号识别信息', lambda: self._select_route('identity'))
        menu.addAction('高级账号操作', lambda: self._select_route('advanced'))
        self.more_button.setMenu(menu)
        row.addWidget(self.more_button)
        for button in (self.preview_button, self.save_button, self.discard_button):
            actions.addWidget(button)
        actions.addWidget(self.draft_status, 1)
        self.draft_actions = QWidget(root)
        self.draft_actions.setLayout(actions)
        layout.insertWidget(1, self.draft_actions)
        self.draft_actions.hide()
        maintenance = SectionPanel('高级账号操作', '模板、JSON、身份重新绑定与删除。', root, collapsible=True)
        for button in (self.json_button, self.template_button, self.rebind_button, self.delete_button):
            maintenance.add_widget(button)
        layout.addWidget(maintenance)
        self.status = _AccountStatusLabel("等待操作")
        layout.insertWidget(3, self.status)
        # Keep the existing account header; move only lower settings into the routed body.
        self.maintenance = maintenance
        self.settings_host = QWidget(root)
        self.settings_layout = QVBoxLayout(self.settings_host)
        self.settings_layout.setContentsMargins(0, 0, 0, 0)
        self.settings_layout.setAlignment(Qt.AlignTop)
        for widget in (self.identity_group, self.reminder_panel, self.form_host, maintenance):
            layout.removeWidget(widget)
            self.settings_layout.addWidget(widget)
        self.settings_scroll = QScrollArea(root)
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.settings_scroll.setWidget(self.settings_host)
        self.daily_help = QLabel('每日活跃度：开头读取一次并领取已完成小任务积分；按账号选择执行周本、全部聚落、首领材料、凝素／无音区；所有耗体力安排结束后领取宝箱并复核。\n实际不足 100 或无法确认时保留错误，由你处理；未选择模块不会被推断为活跃度不足。', self.settings_host)
        self.daily_help.setWordWrap(True)
        self.settings_layout.addWidget(self.daily_help)
        self.daily_help.hide()
        body = QHBoxLayout()
        self.navigation = QTreeWidget(root)
        self.navigation.setHeaderHidden(True)
        self.navigation.setMinimumWidth(180)
        self.navigation.setMaximumWidth(220)
        self.navigation.setObjectName('accountTaskNavigation')
        self.navigation.setIndentation(16)
        body.addWidget(self.navigation)
        self.content_stack = QStackedWidget(root)
        from src.gui.AccountTaskOverview import AccountTaskOverview
        self.overview = AccountTaskOverview(repository, self._overview_live, root)
        from src.gui.AccountSlotEditor import AccountSlotEditor
        self.slot_editor = AccountSlotEditor(self.overview)
        self.overview.layout().insertWidget(0, self.slot_editor)
        self.slot_editor.edited.connect(self._mark_draft_edited)
        self.slot_editor.order_requested.connect(lambda: self._select_route('sequence_order'))
        self.content_stack.addWidget(self.overview)
        self.content_stack.addWidget(self.settings_scroll)
        body.addWidget(self.content_stack, 1)
        layout.addLayout(body, 1)
        root.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.vBoxLayout.setSizeConstraint(QLayout.SetDefaultConstraint)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._route = 'overview'
        self._nav_items = {}
        for route, title, children in (
                ('overview', '任务总览', ()), ('sequences', '账号序列', ()),
                ('sequence_order', '账号执行顺序', ()),
                ('identity', '账号识别信息', ()), ('reminders', '待办提醒', ()),
                ('daily', '日常与声骸', (('nightmare_nest', '残像聚落'), ('world_boss', '讨伐强敌'),
                                       ('forgery', '凝素领域'), ('tacet', '无音区'), ('daily_activity', '活跃度与奖励'))),
                ('weekly', '周常安排', (('weekly_boss', '战歌重奏'), ('weekly_garden', '每周乐园'), ('merge_echo', '声骸合成'))),
                ('adversity_tower', '深塔（单独启动）', ()), ('manual', '海墟与活动提醒', ()),
                ('closing', '收尾行为', ()),
                ('recording', '截图与录像', ()), ('advanced', '高级设置', ())):
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.UserRole, route)
            self.navigation.addTopLevelItem(item)
            self._nav_items[route] = item
            for key, label in children:
                child = QTreeWidgetItem(item, [label])
                child.setData(0, Qt.UserRole, key)
                self._nav_items[key] = child
        from src.account_reminders import TASK_REMINDERS
        for key, label in TASK_REMINDERS.items():
            if key != 'adversity_tower':
                item = QTreeWidgetItem(self._nav_items['manual'], [label])
                item.setData(0, Qt.UserRole, 'reminder:' + key)
                self._nav_items['reminder:' + key] = item
        self.navigation.currentItemChanged.connect(lambda item, _: self._navigate(item.data(0, Qt.UserRole)) if item else None)
        self.overview.navigate.connect(self._select_route)
        self.overview.records.connect(self._open_records)
        self.overview.launch_page.connect(self._open_task_page)
        self.add_widget(root, stretch=1)
        self.profile_combo.currentIndexChanged.connect(self._load_selected)
        self.preview_button.clicked.connect(self.preview)
        self.save_button.clicked.connect(self.save)
        self.discard_button.clicked.connect(lambda: self._load_selected(discard=True))
        self.delete_button.clicked.connect(self.delete_account)
        self.rebind_button.clicked.connect(self.rebind_identity)
        self.template_button.clicked.connect(self.edit_template)
        self.new_button.clicked.connect(self.create_account)
        self.operation = BackgroundOperation(self, (
            self.save_button, self.delete_button, self.rebind_button, self.read_feature_button, self.template_button,
            self.new_button, self.discard_button, self.preview_button,
            self.form_host, self.task_editor, self.sequence_group, self.json_button, self.reminder_panel,
            self.slot_editor))
        self.refresh()
        self.navigation.setCurrentItem(self._nav_items['overview'])

    def _overview_live(self):
        import time
        from ok import og
        executor = getattr(og, 'executor', None) or self.executor
        task = getattr(executor, 'current_task', None)
        if task is None or not getattr(task, 'running', False):
            return {}
        info = dict(getattr(task, 'info', {}) or {})
        return {'profile_id': str(info.get('Status Profile ID') or ''),
                'task_id': str(info.get('Status Task ID') or ''),
                'run_id': str(info.get('Status Run ID') or ''),
                'detail': str(info.get('Status Detail') or ''),
                'elapsed': max(0, int(time.time() - getattr(task, 'start_time', time.time())))}

    def _select_route(self, route):
        route = route if route in self._nav_items else 'daily'
        item = self._nav_items[route]
        if item.parent():
            item.parent().setExpanded(True)
        self.navigation.setCurrentItem(item)
        self._navigate(route)

    def _navigate(self, route):
        self._route = route
        self.content_stack.setCurrentWidget(self.overview if route == 'overview' else self.settings_scroll)
        self.identity_group.setVisible(route == 'identity')
        reminder_route = route in ('reminders', 'manual', 'adversity_tower') or route.startswith('reminder:')
        self.reminder_panel.setVisible(reminder_route)
        if reminder_route:
            self.reminder_panel.set_expanded(True)
            self.reminder_panel.deep_settings.setVisible(route in ('reminders', 'adversity_tower'))
            for widget in (self.reminder_panel.host, self.reminder_panel.note_label, self.reminder_panel.note):
                widget.setVisible(route == 'reminders')
            key_filter = 'adversity_tower' if route == 'adversity_tower' else route.partition(':')[2] if route.startswith('reminder:') else None
            for key, (box, rule, date) in self.reminder_panel.task_choices.items():
                visible = key == key_filter if key_filter else (key != 'adversity_tower' if route == 'manual' else True)
                box.setVisible(visible)
                rule.setVisible(visible)
                date.setVisible(visible and rule.currentData() == 'custom')
        if route == 'identity':
            self.identity_group.set_expanded(True)
        self.maintenance.setVisible(route == 'advanced')
        if hasattr(self, '_sequence_panel'):
            self._sequence_panel.setVisible(route == 'sequences')
        if hasattr(self, '_order_panel'):
            self._order_panel.setVisible(route == 'sequence_order')
        if route in ('sequences', 'sequence_order') and hasattr(self, '_refresh_sequence_views'):
            self._refresh_sequence_views()
        if route == 'advanced':
            self.maintenance.set_expanded(True)
        groups = {'daily': 0, 'weekly': 1, 'closing': 2, 'advanced': 3, 'recording': 4,
                  'nightmare_nest': 0, 'world_boss': 0, 'forgery': 0, 'tacet': 0, 'daily_activity': 0,
                  'weekly_boss': 1, 'weekly_garden': 1, 'merge_echo': 1}
        filters = {'nightmare_nest': {'Tacet Discord Nests to Farm'}, 'world_boss': {MATERIAL_TARGETS},
                   'forgery': {FORGERY_GOALS, 'Which to Farm', 'Which Forgery Challenge to Farm'},
                   'tacet': {'Which to Farm', 'Which Tacet Suppression to Farm'},
                   'weekly_boss': {WEEKLY_PLAN},
                   'weekly_garden': {'Garden Execution Mode', 'Weekly Garden Check Day'},
                   'merge_echo': {'Merge Echo on Sunday'}, 'daily_activity': set()}
        group = groups.get(route)
        self.form_host.setVisible(group is not None)
        for key, section in getattr(self, 'form_sections', {}).items():
            section.setVisible(key == group)
            if key == group:
                section.set_expanded(True)
        for key, widget in getattr(self, 'form_rows', {}).items():
            widget.setVisible(key in filters[route] if route in filters else True)
        self.daily_help.setVisible(route == 'daily_activity')
        if hasattr(self, '_weekly_status_host'):
            self._weekly_status_host.setVisible(route in ('weekly', 'weekly_boss'))
        if route == 'overview':
            self.overview.refresh(force=True)

    def _open_records(self, key):
        from ok import og
        page = getattr(getattr(og, 'main_window', None), 'completion_check_tab', None)
        if page is None:
            self.status.setText('完成检查页尚未就绪')
            return
        page.select_account_project(self.selected_profile_id, key)
        og.main_window.switchTo(page)

    def _open_task_page(self, class_name):
        from ok import og
        window = getattr(og, 'main_window', None)
        task = next((task for task in getattr(getattr(og, 'executor', None), 'onetime_tasks', [])
                     if type(task).__name__ == class_name), None)
        if window is not None and task is not None and hasattr(window, 'edit_task_tab'):
            window.edit_task_tab.load_task(task)
            window.switchTo(window.edit_task_tab)
        else:
            self.status.setText('请在“任务 → 每周任务”打开自动深塔；本页不会直接启动。')

    def edit_json(self):
        if self.operation.busy or self.draft is None:
            return
        try:
            self._apply_text()
        except (ValueError, TypeError) as error:
            self.status.setText(sanitize_error(error))
            return
        dialog = QDialog(self.view)
        dialog.setWindowTitle('高级 JSON（应用到草稿后仍需确认保存）')
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit(dialog)
        editor.setPlainText(json.dumps(self.draft.tasks, ensure_ascii=False, indent=2))
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dialog)
        buttons.button(QDialogButtonBox.Ok).setText('应用到草稿')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        from src.gui.CodexTheme import size_dialog
        size_dialog(dialog, 700, 540)
        if dialog.exec() == QDialog.Accepted:
            try:
                value = json.loads(editor.toPlainText())
                if not isinstance(value, dict):
                    raise ValueError('任务配置必须是 JSON 对象')
                self.draft.tasks = value
                self.task_editor.setPlainText(editor.toPlainText())
                self._render_form()
                self._mark_draft_edited()
            except (ValueError, TypeError) as error:
                self.status.setText(sanitize_error(error))
        dialog.deleteLater()

    @property
    def name(self):
        return "账号配置"

    @property
    def dirty(self):
        if self.draft is None:
            return False
        try:
            self._apply_text()
            members = tuple(name for name, box in self.sequence_widgets.items() if box.isChecked())
            return (self.draft.tasks != self._loaded_tasks or self.draft.account != self._loaded_account
                    or members != self._loaded_sequences)
        except Exception:
            return True

    @property
    def selected_profile_id(self):
        return self.draft.profile_id if self.draft is not None else None

    def show_redacted_diff(self):
        if self.draft is None:
            return ""
        diff = self.editor.preview_diff(self.draft)
        return "\n".join(f"{item.path}: {item.before!r} → {item.after!r}" for item in diff.changes)

    def reset_task_field(self, key):
        if self.draft is None:
            return False
        fresh = self.editor.load_draft(self.draft.profile_id)
        if key not in fresh.tasks:
            return False
        self.draft.tasks[key] = fresh.tasks[key]
        self.task_editor.setPlainText(json.dumps(self.draft.tasks, ensure_ascii=False, indent=2))
        self._render_form()
        return True

    @property
    def icon(self):
        return FluentIcon.SETTING

    @property
    def add_after_default_tabs(self):
        return True

    def refresh(self, profile_id=None, *, preserve_draft=False):
        if self.operation.busy or (preserve_draft and self.dirty):
            self.status.setText('账号配置已更新；当前草稿已保留，保存时将检查版本冲突')
            return
        selected_id = profile_id or self.profile_combo.currentData()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        try:
            records = self.editor.repository.list_profiles()
            for record in records:
                label = account_display_label(record.account)
                self.profile_combo.addItem(label, record.profile_id)
        except AccountRepositoryError as exc:
            # A missing master is a safe-mode state during first launch or
            # after an incomplete import.  Keep the shell visible so the
            # integrity dialog can explain/recover it instead of crashing UI.
            self.status.setText(f"账号仓库暂不可用：{sanitize_error(exc)}")
        finally:
            if selected_id:
                index = self.profile_combo.findData(selected_id)
                self.profile_combo.setCurrentIndex(index if index >= 0 else 0)
            self.profile_combo.blockSignals(False)
        self._load_selected()

    def refresh_sequences(self):
        """Refresh membership checkboxes without discarding an unsaved draft."""
        if self.operation.busy or self.dirty:
            return
        self._render_sequences()
        self._loaded_sequences = tuple(name for name, box in self.sequence_widgets.items() if box.isChecked())

    def _load_selected(self, *_args, discard=False):
        profile_id = self.profile_combo.currentData()
        if not profile_id:
            return
        if self.draft is not None and self.draft.profile_id != profile_id:
            try:
                if self.operation.busy or self.dirty:
                    if not self.operation.busy:
                        self._apply_text()
                    self._draft_cache[self.draft.profile_id] = (
                        copy.deepcopy(self.draft), copy.deepcopy(self._loaded_account),
                        copy.deepcopy(self._loaded_tasks), self._loaded_sequences,
                        tuple(name for name, box in self.sequence_widgets.items() if box.isChecked()))
            except (ValueError, TypeError) as error:
                self.profile_combo.blockSignals(True)
                self.profile_combo.setCurrentIndex(self.profile_combo.findData(self.draft.profile_id))
                self.profile_combo.blockSignals(False)
                self.status.setText(f'请先修正当前草稿：{sanitize_error(error)}')
                return
        if discard:
            self._draft_cache.pop(profile_id, None)
            self._failed_drafts.pop(profile_id, None)
        cached = self._draft_cache.pop(profile_id, None)
        failed = self._failed_drafts.pop(profile_id, None)
        self.draft = failed or self.editor.load_draft(profile_id)
        if cached and failed is None:
            self.draft = cached[0]
        self.reveal_phone.setChecked(False)
        label = account_display_label(self.draft.account)
        masked_phone = self.draft.account.get("masked_phone") or "未记录"
        alternate = self.draft.account.get("alternate_login_name") or "未记录"
        feature_code = self.draft.account.get("game_feature_code") or "未绑定（初露峥嵘执行前需核验）"
        self.metadata.setText(
            f"唯一编号：{self.draft.profile_id}"
        )
        self._render_sequences()
        self._render_identity()
        self.task_editor.setPlainText(json.dumps(self.draft.tasks, ensure_ascii=False, indent=2))
        self.reminder_panel.load_account(self.draft.account)
        self._render_form()
        self._loaded_tasks = copy.deepcopy(self.draft.tasks)
        self._loaded_account = copy.deepcopy(self.draft.account)
        self.task_editor.setPlainText(json.dumps(self.draft.tasks, ensure_ascii=False, indent=2))
        self._loaded_sequences = tuple(name for name, box in self.sequence_widgets.items() if box.isChecked())
        self._load_slot_editor()
        if cached:
            self._loaded_account, self._loaded_tasks, self._loaded_sequences = cached[1:4]
            for name, box in self.sequence_widgets.items():
                box.setChecked(name in cached[4])
        self._load_slot_editor()
        self.status.setText("已载入独立草稿")
        self.draft_status.setText('尚未编辑')
        self.draft_actions.setVisible(bool(cached))
        if cached:
            self.draft_status.setText('已恢复未保存草稿')
        self.overview.set_profile(profile_id)

    def _load_slot_editor(self):
        self.slot_editor.load(self.draft.account,
                              {r.profile_id: r.account for r in self.editor.repository.list_profiles()},
                              self.draft.profile_id,
                              tuple(name for name, box in self.sequence_widgets.items() if box.isChecked()))

    def _mark_draft_edited(self, *_):
        self.draft_status.setText('草稿已编辑，尚未保存')
        self.draft_actions.show()

    def _apply_text(self):
        self.draft.account = self.reminder_panel.apply_account(self.draft.account)
        self.slot_editor.apply(self.draft.account, self.sequence_widgets)
        # Identity widgets are intentionally read-only.  Identity changes use
        # AccountRebindService so they cannot be mixed into task edits.
        value = json.loads(self.task_editor.toPlainText())
        if not isinstance(value, dict):
            raise ValueError("任务配置必须是 JSON 对象")
        self.draft.tasks = value
        from src.recording_policy import RECORDING_PAGES
        self.draft.tasks['Record Pages'] = list(RECORDING_PAGES)
        self.draft.tasks.setdefault('Garden Execution Mode', 'closed')
        for key, widget in self.form_widgets.items():
            if not widget.isEnabled():
                continue
            if isinstance(widget, ForgeryQuotaWidget):
                self.draft.tasks[key] = widget.values()
            elif isinstance(widget, WorldBossMaterialPlanWidget):
                rows = widget.values()
                if self.draft.tasks.get(key) != [] or rows != material_plan(self.draft.tasks):
                    self.draft.tasks[key] = rows
            elif isinstance(widget, WeeklyBossPlanWidget):
                rows = widget.values()
                if self.draft.tasks.get(key) != [] or rows != weekly_plan(self.draft.tasks):
                    self.draft.tasks[key] = rows
                    active = [r['boss'] for r in rows if r['boss'] != '无' and r['limit'] != 0]
                    self.draft.tasks['Weekly Boss Target'] = active[0] if active else '无'
            elif isinstance(widget, NestSelection):
                self.draft.tasks[key] = widget.values()
                nightmare_values = widget.nightmare_values()
                if nightmare_values or 'Nightmare Settlements to Farm' in self.draft.tasks:
                    self.draft.tasks['Nightmare Settlements to Farm'] = nightmare_values
            elif isinstance(widget, QCheckBox):
                self.draft.tasks[key] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                self.draft.tasks[key] = _read_account_choice(widget, key)
            else:
                text = widget.text()
                original = self.draft.tasks.get(key)
                row = widget.parentWidget()
                if isinstance(row, FlatSettingRow):
                    row.set_error(None)
                try:
                    if isinstance(original, int):
                        self.draft.tasks[key] = int(text)
                    elif isinstance(original, float):
                        self.draft.tasks[key] = float(text)
                    elif isinstance(original, (list, dict)):
                        self.draft.tasks[key] = restore_account_value(json.loads(text))
                    else:
                        self.draft.tasks[key] = restore_account_value(text)
                except (ValueError, TypeError):
                    message = '请输入有效的数字' if isinstance(original, (int, float)) else '请输入有效的 JSON'
                    if isinstance(row, FlatSettingRow):
                        row.set_error(message)
                    raise ValueError(f'{widget.accessibleName()}：{message}') from None

    def _render_identity(self):
        if self.draft is None:
            return
        for key, widget in self.identity_widgets.items():
            value = str(self.draft.account.get(key) or "")
            if key == 'phone' and value and not self.reveal_phone.isChecked():
                from src.account_identity import masked_phone
                value = masked_phone(value)
            widget.setText(value)
        self.feature_code_label.setText(str(self.draft.account.get("game_feature_code")
                                            or "未绑定（初露峥嵘执行前需核验）"))

    def _render_sequences(self):
        while self.sequence_layout.count():
            item = self.sequence_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.sequence_widgets.clear()
        if self.draft is None:
            return
        for sequence_id in self.editor.repository.list_sequence_ids():
            box = QCheckBox(sequence_id, self.sequence_group)
            box.setChecked(self.draft.profile_id in self.editor.repository.load_sequence(sequence_id).profile_ids)
            box.toggled.connect(self._mark_draft_edited)
            self.sequence_widgets[sequence_id] = box
            self.sequence_layout.addWidget(box)
            from src.account_slots import FIXED_SEQUENCES
            if sequence_id in FIXED_SEQUENCES:
                box.hide()
        if not self.sequence_widgets:
            self.sequence_layout.addWidget(QLabel("暂无序列；请先在序列配置页新建序列。", self.sequence_group))

    def _render_form(self):
        from src.gui.SectionPanel import SectionPanel
        from src.recording_policy import RECORDING_PAGES
        self.draft.tasks.setdefault(WEEKLY_PLAN, [])
        self.draft.tasks.setdefault(MATERIAL_TARGETS, [])
        self.draft.tasks['Record Pages'] = list(RECORDING_PAGES)
        for key, value in recording_defaults().items():
            self.draft.tasks.setdefault(key, value)
        states = {key: panel.toggle_button.isChecked()
                  for key, panel in getattr(self, 'form_sections', {}).items()}
        while self.form_layout.rowCount():
            self.form_layout.removeRow(0)
        self.form_sections = {}
        self.form_widgets.clear()
        self.form_rows = {}
        while self.identity_task_layout.count():
            item = self.identity_task_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        stamina = {FORGERY_GOALS, MATERIAL_TARGETS, 'Material Planner Enabled', 'Which to Farm', 'Which Tacet Suppression to Farm', 'Which Forgery Challenge to Farm',
                   'Material Selection'}
        daily = {'Farm Nightmare Nest for Daily Echo', 'Nightmare Which to Farm', 'Tacet Discord Nests to Farm',
                 'Nightmare Settlements to Farm', 'Auto Farm all Nightmare Nest'}
        weekly = {'Garden Execution Mode', 'Weekly Garden Check Day', 'Merge Echo on Sunday'}
        def group(field):
            if field.key in ('Record Pages', 'Screenshot After Daily Task', 'Record After Daily Task', 'Record Duration'): return 4
            if field.key in ('Weekly Boss Target', WEEKLY_PLAN): return 1
            if field.key in stamina: return 0
            if field.key in daily: return 0
            if field.key in weekly: return 1
            if field.key == 'Logout After Daily Task': return 2
            return 3
        last_group = None
        fields = sorted(account_field_metadata(self.draft.tasks), key=group)
        for field in fields:
            if field.key in ('Nightmare Which to Farm', 'Nightmare Settlements to Farm', 'Weekly Boss Target',
                             'Material Planner Enabled', 'Auto Farm all Nightmare Nest', 'Farm Nightmare Nest for Daily Echo'):
                continue
            identity_field = field.key in ('备用识别名称', '备用识别名称内容')
            if not identity_field and group(field) != last_group:
                last_group = group(field)
                heading = SectionPanel(('日常与声骸', '周常安排', '收尾行为', '高级任务参数', '截图与录像')[last_group],
                                       parent=self.form_host, collapsible=True,
                                       expanded=states.get(last_group, False))
                self.form_sections[last_group] = heading
                self.form_layout.addRow(heading)
            value = self.draft.tasks.get(field.key)
            if field.key == FORGERY_GOALS:
                widget = ForgeryQuotaWidget(self.draft.tasks, self.editor.repository.integrity_service,
                                            self.draft.profile_id, self.form_host)
            elif field.key == MATERIAL_TARGETS:
                widget = WorldBossMaterialPlanWidget(self.draft.tasks, self.editor.repository.integrity_service,
                                                     self.draft.profile_id, self.form_host)
            elif field.key == WEEKLY_PLAN:
                widget = WeeklyBossPlanWidget(self.draft.tasks, self.editor.repository.integrity_service,
                                              self.draft.profile_id, self.form_host)
                widget.changed.connect(self._mark_draft_edited)
            elif field.key == 'Record Pages':
                widget = FixedRecordingPages(self.form_host)
            elif field.key == "Tacet Discord Nests to Farm":
                widget = NestSelection(value, self.draft.tasks.get('Nightmare Settlements to Farm', []), self.form_host)
            elif field.editor_type == "bool":
                widget = QCheckBox(self.form_host)
                widget.setChecked(bool(value))
            elif field.editor_type == "choice":
                widget = ClickOnlyComboBox(self.form_host)
                for option, option_label in zip(field.options, field.option_labels):
                    widget.addItem(option_label, option)
                _select_account_choice(widget, field.key, value)
            else:
                from PySide6.QtWidgets import QLineEdit
                widget = QLineEdit(self.form_host)
                display_value = localize_account_value(value)
                widget.setText(json.dumps(display_value, ensure_ascii=False)
                               if isinstance(display_value, (list, dict)) else str(display_value))
            widget.setEnabled(not field.read_only)
            widget.setToolTip(field.help_text)
            self.form_widgets[field.key] = widget
            if identity_field:
                self.identity_task_layout.addWidget(FlatSettingRow(field.label, widget, field.help_text,
                                                                  self.identity_task_fields))
            elif isinstance(widget, (ForgeryQuotaWidget, WeeklyBossPlanWidget, WorldBossMaterialPlanWidget)):
                heading.add_widget(widget)
                self.form_rows[field.key] = widget
            else:
                self.form_rows[field.key] = heading.add_row(field.label, widget, field.help_text)
            if isinstance(widget, (NestSelection, ForgeryQuotaWidget, WeeklyBossPlanWidget, WorldBossMaterialPlanWidget)):
                widget.changed.connect(self._mark_draft_edited)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(self._mark_draft_edited)
            elif isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._mark_draft_edited)
            elif isinstance(widget, QLineEdit):
                widget.textEdited.connect(self._mark_draft_edited)
            if field.key == WEEKLY_PLAN:
                self._render_weekly_status()
        _link_material_controls(self.form_widgets)
        target = self.form_widgets.get(WEEKLY_PLAN)
        if target is not None and 1 in self.form_sections:
            def update_summary(*_):
                try:
                    text = '三个周本按优先级领取 · 跨周累计' if plan_enabled(target.values()) else '周本已关闭'
                except ValueError:
                    text = '周本配置待核对'
                self.form_sections[1].set_summary(text)
            target.changed.connect(update_summary)
            update_summary()
        for key, field_key in ((0, 'Which to Farm'),):
            widget = self.form_widgets.get(field_key)
            if key in self.form_sections and isinstance(widget, QComboBox):
                def update_group_summary(*_, key=key, widget=widget):
                    self.form_sections[key].set_summary(widget.currentText())
                widget.currentTextChanged.connect(update_group_summary)
                update_group_summary()
        _link_garden_controls(self.form_widgets)
        from src.gui.compact_settings import compact_settings
        compact_settings(self, account=True)
        self._navigate(self._route)

    def _render_weekly_status(self):
        from src.config_integrity import get_default_service
        from src.task.weekly_boss import WEEKLY_MONDAY, WEEKLY_SUNDAY, weekly_check_window
        from datetime import datetime
        rows = []
        service = get_default_service()
        if service is not None:
            try:
                for key, title in ((WEEKLY_MONDAY, '周一检查'), (WEEKLY_SUNDAY, '周日复检')):
                    stamp = service.get_completion(self.draft.profile_id, key)
                    done = False
                    if stamp:
                        try:
                            done = weekly_check_window(datetime.fromisoformat(stamp)) == (weekly_check_window()[0], key)
                        except ValueError:
                            pass
                    text = '本周已完成' if done else '待检查'
                    rows.append((title, text, stamp or '无'))
                outcome = service.get_progress(f'weekly_boss:{self.draft.profile_id}', {})
                rows.append(('最近结果', str(outcome.get('status', '尚未执行')), ''))
            except Exception:
                rows = [('周本记录', '暂不可读取', '')]
        else:
            rows = [('周本记录', '服务未就绪', '')]
        host = QWidget(self.form_host)
        self._weekly_status_host = host
        grid = QGridLayout(host)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(5)
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                label = QLabel(value, host)
                label.setWordWrap(column == 2)
                grid.addWidget(label, row, column)
        grid.setColumnStretch(2, 1)
        self.form_sections[1].add_widget(host)

    def edit_template(self):
        if self.operation.busy:
            return None
        try:
            template = self.editor.load_template(self.selected_profile_id)
            dialog = AccountTemplateDialog(template.tasks, self.view)
            if dialog.exec() != QDialog.Accepted:
                return None
            return self._submit_action(
                partial(self.editor.save_template, copy.deepcopy(dialog.tasks()), expected_revision=str(template.revision)),
                '新账号模板保存成功', refresh=False)
        except Exception as exc:
            self.status.setText(f"模板保存失败：{sanitize_error(exc)}")
            return None

    def create_account(self):
        if self.operation.busy:
            return None
        try:
            template = self.editor.load_template(self.selected_profile_id)
            sequence_ids = self.editor.repository.list_sequence_ids()
            dialog = NewAccountDialog(sequence_ids, self.view)
            from src.account_identity import short_profile_name
            records = self.editor.repository.list_profiles()
            occupied = {short_profile_name(record.account.get('display_name')) for record in records}
            number = 1
            while f'A{number}' in occupied:
                number += 1
            dialog.short_name.setText(f'A{number}')
            if dialog.exec() != QDialog.Accepted:
                return None
            values = dialog.values()
            phone = ''.join(str(values['phone']).split())
            duplicates = [account_display_label(record.account) for record in records
                          if str(record.account.get('phone') or '') == phone and phone]
            warning = ('\n注意：手机号与以下账号重复：' + '、'.join(duplicates) + '\n不会合并账号。') if duplicates else ''
            answer = QMessageBox.question(
                self.view, "确认新建账号",
                f"确认使用新账号模板创建 {account_display_label(values)}？{warning}",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return None
            return self._submit_action(
                partial(self.editor.create_profile, copy.deepcopy(template), **copy.deepcopy(values)),
                '新账号创建成功', lambda result: AccountChangeEvent(
                    'profile_created', str(result.revision), (result.profile_id,), values['sequence_ids']))
        except Exception as exc:
            self.status.setText(f"新建账号失败：{sanitize_error(exc)}")
            return None

    def preview(self):
        try:
            self._apply_text()
            diff = self.editor.preview_diff(self.draft)
            text = "\n".join(f"{item.path}: {item.before!r} → {item.after!r}" for item in diff.changes) or "无修改"
            QMessageBox.information(self.view, "差异预览", text)
            return diff
        except Exception as exc:
            self.status.setText(f"预览失败：{exc}")
            return None

    def save(self):
        if self.operation.busy:
            return None
        try:
            self._apply_text()
            label = str(self.draft.account.get("display_name", self.draft.profile_id))
            sequence_ids = tuple(name for name, box in self.sequence_widgets.items() if box.isChecked())
            answer = QMessageBox.question(self.view, "确认账号", f"确认保存账号 {account_display_label(self.draft.account)} 的修改？")
            if answer != QMessageBox.Yes:
                return None
            submitted = copy.deepcopy(self.draft)
            profile_id = submitted.profile_id
            membership_changed = sequence_ids != self._loaded_sequences
            return self._submit_action(
                partial(self.editor.save_draft, submitted.scope, submitted,
                        confirmed_account_label=label, sequence_ids=sequence_ids),
                '保存成功，已先创建账号备份', lambda result: AccountChangeEvent(
                    'profile_saved', str(getattr(result, 'revision', '')), (profile_id,), sequence_ids,
                    choices_changed=membership_changed or dict(result.account) != submitted.account),
                submitted=submitted, saved_sequences=sequence_ids)
        except Exception as exc:
            self.status.setText(f"保存失败：{exc}")
            return None

    def read_feature_code(self):
        if self.operation.busy or self.draft is None:
            return
        from ok import og
        from src.evidence.service import request_capture
        submitted = copy.deepcopy(self.draft)
        try:
            self.status.setText('正在读取特征码，请保持游戏右下角完整可见…')
            future = request_capture(og.executor, feature_code=True)
        except Exception as error:
            self.status.setText('读取失败：' + sanitize_error(error))
            logging.getLogger(__name__).warning('feature_code_capture_failed: %s', type(error).__name__)
            return

        def received(value):
            if self.draft is None or self.draft.profile_id != submitted.profile_id:
                self.status.setText('所选账号已变化，请重新读取特征码')
                return
            requested = {'game_feature_code': value['code']}
            try:
                self.rebind_service.preview(submitted.profile_id, requested)
                label = account_display_label(submitted.account)
                answer = QMessageBox.question(self.view, '确认特征码绑定',
                    f'已连续读取到一致的特征码。确认当前游戏账号是 {label} 并绑定？\n'
                    f'特征码：{value["code"]}\n'
                    '该绑定将用于初露峥嵘首尾核验，旧身份会备份。')
                if answer != QMessageBox.StandardButton.Yes:
                    return
                current = rebind_confirmation_identity(submitted.account)
                self._submit_action(partial(self.rebind_service.rebind, submitted.profile_id,
                    current_identity=current, new_identity=requested, confirmed=True,
                    expected_revision=submitted.revision), '特征码已绑定',
                    lambda result: AccountChangeEvent('identity_rebound', str(result.revision),
                                                     (submitted.profile_id,), ()), submitted=submitted)
            except Exception as error:
                self.status.setText('特征码绑定失败：' + sanitize_error(error))
        def failed(error):
            future.cancel()
            message = ('读取超时，请确认游戏窗口可用后重试' if isinstance(error, TimeoutError)
                       else sanitize_error(error))
            self.status.setText('读取失败：' + message)
            logging.getLogger(__name__).warning('feature_code_capture_failed: %s', type(error).__name__)
        self.operation.start(lambda: future.result(timeout=12), received, failed)

    def rebind_identity(self):
        """Run the explicit identity re-bind flow for the selected account."""
        if self.operation.busy:
            return None
        if self.draft is None:
            return None
        current = str(self.draft.account.get("masked_phone") or "")
        masked, ok = QInputDialog.getText(
            self.view, "重新绑定身份", "新的带星号手机号（切换关键依据）：",
            QLineEdit.Normal, current)
        if not ok:
            return None
        alternate, ok = QInputDialog.getText(
            self.view, "重新绑定身份", "新的 U…A 备用识别名（可留空）：",
            QLineEdit.Normal, str(self.draft.account.get("alternate_login_name") or ""))
        if not ok:
            return None
        requested = {"masked_phone": masked.strip()}
        if alternate.strip():
            requested["alternate_login_name"] = alternate.strip()
        try:
            preview = self.rebind_service.preview(self.draft.profile_id, requested)
            changes = "、".join(preview.changes) or "无"
            answer = QMessageBox.question(
                self.view, "确认重新绑定",
                f"账号 {account_display_label(self.draft.account)} 将修改：{changes}\n"
                "旧身份会先备份，是否继续？")
            if answer != QMessageBox.StandardButton.Yes:
                return None
            submitted = copy.deepcopy(self.draft)
            profile_id = submitted.profile_id
            return self._submit_action(
                partial(self.rebind_service.rebind, profile_id,
                        current_identity=rebind_confirmation_identity(submitted.account),
                        new_identity=copy.deepcopy(requested), confirmed=True, expected_revision=submitted.revision),
                '身份重新绑定成功，已创建旧身份备份', lambda result: AccountChangeEvent(
                    'identity_rebound', str(getattr(result, 'revision', '')), (profile_id,), ()),
                submitted=submitted)
        except Exception as exc:
            self.status.setText(f"身份重新绑定失败：{sanitize_error(exc)}")
            return None

    def delete_account(self):
        if self.operation.busy:
            return None
        if self.draft is None:
            return None
        label = str(self.draft.account.get("display_name") or
                    self.draft.account.get("short_name") or "未命名账号")
        preview = self.editor.repository.preview_profile_deletion(self.draft.profile_id)
        first = QMessageBox.question(self.view, "删除账号", f"确认删除账号 {account_display_label(self.draft.account)}？")
        if first != QMessageBox.StandardButton.Yes:
            return None
        sequences = "、".join(preview.sequence_ids) or "无"
        message = (f"账号将从以下序列移除：{sequences}\n"
                   f"账号运行状态：{'将删除' if preview.runtime_present else '无'}\n"
                   "删除前会创建备份。是否继续？")
        second = QMessageBox.question(self.view, "再次确认删除", message)
        if second != QMessageBox.StandardButton.Yes:
            return None
        try:
            submitted = copy.deepcopy(self.draft)
            profile_id = submitted.profile_id
            return self._submit_action(
                partial(self.editor.delete_profile, submitted.scope, confirmed_account_label=label),
                '账号删除成功，序列引用已同步移除', lambda result: AccountChangeEvent(
                    'profile_deleted', '', (profile_id,), tuple(preview.sequence_ids)), submitted=submitted)
        except Exception as exc:
            self.status.setText(f"账号删除失败：{sanitize_error(exc)}")
            return None


    def _accept_saved_profile(self, result, submitted, sequence_ids):
        """Accept the published record without rebuilding an unchanged editor."""
        self.draft = ProfileDraft(result.profile_id, str(result.revision),
                                  copy.deepcopy(dict(result.account)), copy.deepcopy(dict(result.tasks)))
        self.reminder_panel.load_account(self.draft.account)
        for key, widget in self.form_widgets.items():
            if key == 'Record Pages':
                continue
            if self.draft.tasks.get(key) == submitted.tasks.get(key):
                continue
            value = self.draft.tasks.get(key)
            if isinstance(widget, NestSelection):
                widget.set_values(value)
                widget.set_nightmare_values(self.draft.tasks.get('Nightmare Settlements to Farm', []))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QComboBox):
                _select_account_choice(widget, key, value)
            else:
                display = localize_account_value(value)
                widget.setText(json.dumps(display, ensure_ascii=False)
                               if isinstance(display, (list, dict)) else str(display))
        self.task_editor.setPlainText(json.dumps(self.draft.tasks, ensure_ascii=False, indent=2))
        self._render_identity()
        self._loaded_tasks = copy.deepcopy(self.draft.tasks)
        self._loaded_account = copy.deepcopy(self.draft.account)
        self._loaded_sequences = tuple(sequence_ids)
        self.draft_status.setText('尚未编辑')
        self.draft_actions.hide()
        self._draft_cache.pop(result.profile_id, None)
        self._load_slot_editor()

        self.overview.refresh(force=True)
        self._navigate(self._route)

    def _submit_action(self, work, success_text, event=None, *, submitted=None, refresh=True,
                       saved_sequences=None):
        origin_id = self.selected_profile_id
        self.status.setText('正在保存配置…')
        def completed(result):
            started = perf_counter()
            self._failed_drafts.pop(origin_id, None)
            self._draft_cache.pop(origin_id, None)
            if self.selected_profile_id == origin_id:
                if saved_sequences is not None:
                    self._accept_saved_profile(result, submitted, saved_sequences)
                elif refresh:
                    self.refresh(profile_id=getattr(result, 'profile_id', origin_id))
                self._commit_status(success_text)
            if event:
                self.changed.emit(event(result))
            logging.getLogger(__name__).info('account_save_ui_refresh_ms=%.1f',
                                             (perf_counter() - started) * 1000)
        def failed(error):
            if submitted is not None and self.selected_profile_id != origin_id:
                self._failed_drafts[origin_id] = submitted
            self.status.setText(f'配置保存失败，草稿已保留：{sanitize_error(error)}')
        return self.operation.start(work, completed, failed)

    def _commit_status(self, success):
        result = getattr(self.editor.repository, 'last_publish_result', None)
        errors = getattr(result, 'maintenance_errors', ())
        self.status.setText(('配置已生效，维护待恢复：' + sanitize_error('; '.join(errors))) if errors else success)


__all__ = ["AccountConfigTab", "AccountTemplateDialog", "ClickOnlyComboBox", "NewAccountDialog"]
