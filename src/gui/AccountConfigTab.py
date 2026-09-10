"""PC account task-configuration editor tab."""

import json
import copy
import logging
from time import perf_counter
from functools import partial

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QPushButton, QInputDialog, QDialog,
                               QDialogButtonBox,
                               QVBoxLayout, QWidget, QLineEdit, QSizePolicy, QScrollArea)
from qfluentwidgets import BodyLabel, FluentIcon

from ok.gui.widget.CustomTab import CustomTab
from src.account_config_editor import AccountConfigEditor, ProfileDraft, sanitize_error
from src.account_display import account_display_label
from src.account_rebind_service import AccountRebindService
from src.account_repository import AccountRepository, AccountRepositoryError, get_default_repository
from src.account_field_metadata import (account_field_metadata, localize_account_value,
                                        restore_account_value, normalize_weekday)
from src.gui.AccountChangeEvent import AccountChangeEvent
from src.gui.BackgroundOperation import BackgroundOperation
from src.gui.FlatSettingRow import FlatSettingRow


from src.gui.ChoiceControls import QtComboBox as QComboBox
ClickOnlyComboBox = QComboBox


def _select_account_choice(widget, key, value):
    if key == 'Weekly Garden Check Day':
        try:
            value = normalize_weekday(value)
        except ValueError:
            widget.setPlaceholderText('检查日无效，请重新选择')
            widget.setCurrentIndex(-1)
            return
    widget.setCurrentIndex(max(widget.findData(value), 0))


def _read_account_choice(widget, key):
    value = widget.currentData()
    if key == 'Weekly Garden Check Day':
        if widget.currentIndex() < 0:
            raise ValueError('周常乐园检查日无效，请重新选择星期')
        return normalize_weekday(value)
    return value


class AccountTemplateDialog(QDialog):
    """Edit the shared task-only template with the same field metadata as account editing."""

    def __init__(self, tasks, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑新账号模板")
        self._tasks = dict(tasks)
        self._widgets = {}
        layout = QVBoxLayout(self)
        layout.addWidget(BodyLabel("模板只复制每日任务设置，不复制账号身份、序列或完成记录。"))
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget(scroll)
        form = QVBoxLayout(content)
        for field in account_field_metadata(self._tasks):
            if field.affects_identity or field.key in ("备用识别名称", "备用识别名称内容"):
                continue
            value = self._tasks.get(field.key)
            if field.editor_type == "bool":
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
            form.addWidget(FlatSettingRow(field.label, widget, field.help_text, content))
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
            if isinstance(widget, QCheckBox):
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
        repository = get_default_repository() or AccountRepository()
        self.editor = editor or AccountConfigEditor(repository)
        self.rebind_service = AccountRebindService(self.editor.repository)
        self.draft = None
        self._failed_drafts = {}
        root = QWidget(self.view)
        root.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(root)
        layout.setAlignment(Qt.AlignTop)
        layout.addWidget(BodyLabel("账号配置（登录身份与唯一编号只读；删除操作仅针对当前账号）"))
        row = QHBoxLayout()
        row.addWidget(QLabel("账号"))
        self.profile_combo = ClickOnlyComboBox(root)
        row.addWidget(self.profile_combo, 1)
        layout.addLayout(row)
        self.metadata = BodyLabel("")
        self.metadata.setWordWrap(True)
        layout.addWidget(self.metadata)
        self.draft_status = QLabel('尚未编辑', root)
        self.draft_status.setProperty('role', 'description')
        from src.gui.SectionPanel import SectionPanel
        self.identity_group = SectionPanel("账号识别信息", "登录身份只读；普通保存不会修改身份。", root, collapsible=True)
        self.identity_layout = QFormLayout()
        self.identity_group.content_layout.addLayout(self.identity_layout)
        self.identity_widgets = {}
        for key, label in (("phone", "完整手机号"), ("masked_phone", "带星号手机号（切换关键依据）"),
                           ("nickname", "游戏昵称"), ("alternate_login_name", "U…A 备用识别名")):
            widget = QLineEdit(self.identity_group)
            widget.setReadOnly(True)
            widget.setToolTip("身份字段由重新绑定流程修改，普通账号配置保存不会覆盖它")
            self.identity_widgets[key] = widget
            self.identity_layout.addRow(FlatSettingRow(label, widget, parent=self.identity_group))
        self.feature_code_label = QLabel("未记录（当前不参与任务）", self.identity_group)
        self.reveal_phone = QCheckBox('显示完整手机号', self.identity_group)
        self.reveal_phone.toggled.connect(self._render_identity)
        self.identity_layout.addRow(self.reveal_phone)
        self.feature_code_label.setToolTip("来自游戏防 OLED 烧屏遮罩区域；当前只记录，不参与任务")
        self.identity_layout.addRow(FlatSettingRow("游戏内特征码（只读）", self.feature_code_label, parent=self.identity_group))
        self.identity_task_fields = QWidget(self.identity_group)
        self.identity_task_layout = QVBoxLayout(self.identity_task_fields)
        self.identity_task_layout.setContentsMargins(0, 0, 0, 0)
        self.identity_group.content_layout.addWidget(self.identity_task_fields)
        layout.addWidget(self.identity_group)
        self.sequence_group = QGroupBox("所属序列（勾选后保存即可调整当前账号归属）", root)
        self.sequence_layout = QVBoxLayout(self.sequence_group)
        self.sequence_widgets = {}
        layout.addWidget(self.sequence_group)
        self.form_host = QWidget(root)
        self.form_layout = QFormLayout(self.form_host)
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
        self.new_button = QPushButton("新建账号配置", root)
        self.save_button.setProperty('role', 'primary')
        self.delete_button.setProperty('role', 'danger')
        row.addWidget(self.new_button)
        for button in (self.preview_button, self.save_button, self.discard_button):
            actions.addWidget(button)
        actions.addWidget(self.draft_status, 1)
        layout.insertLayout(3, actions)
        maintenance = SectionPanel('高级账号操作', '模板、JSON、身份重新绑定与删除。', root, collapsible=True)
        for button in (self.json_button, self.template_button, self.rebind_button, self.delete_button):
            maintenance.add_widget(button)
        layout.addWidget(maintenance)
        self.status = BodyLabel("等待操作")
        layout.insertWidget(4, self.status)
        self.add_widget(root, stretch=1)
        self.profile_combo.currentIndexChanged.connect(self._load_selected)
        self.preview_button.clicked.connect(self.preview)
        self.save_button.clicked.connect(self.save)
        self.discard_button.clicked.connect(self._load_selected)
        self.delete_button.clicked.connect(self.delete_account)
        self.rebind_button.clicked.connect(self.rebind_identity)
        self.template_button.clicked.connect(self.edit_template)
        self.new_button.clicked.connect(self.create_account)
        self.operation = BackgroundOperation(self, (
            self.save_button, self.delete_button, self.rebind_button, self.template_button,
            self.new_button, self.discard_button, self.preview_button,
            self.form_host, self.task_editor, self.sequence_group, self.json_button))
        self.refresh()

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
            return (self.draft.tasks != self._loaded_tasks or members != self._loaded_sequences)
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

    def _load_selected(self, *_args):
        profile_id = self.profile_combo.currentData()
        if not profile_id:
            return
        self.draft = self._failed_drafts.pop(profile_id, None) or self.editor.load_draft(profile_id)
        self.reveal_phone.setChecked(False)
        label = account_display_label(self.draft.account)
        masked_phone = self.draft.account.get("masked_phone") or "未记录"
        alternate = self.draft.account.get("alternate_login_name") or "未记录"
        feature_code = self.draft.account.get("game_feature_code") or "未记录（当前不参与任务）"
        self.metadata.setText(
            f"账号：{label} · 唯一编号：{self.draft.profile_id}"
        )
        self._render_sequences()
        self._render_identity()
        self.task_editor.setPlainText(json.dumps(self.draft.tasks, ensure_ascii=False, indent=2))
        self._render_form()
        self._loaded_tasks = copy.deepcopy(self.draft.tasks)
        self._loaded_sequences = tuple(name for name, box in self.sequence_widgets.items() if box.isChecked())
        self.status.setText("已载入独立草稿")
        self.draft_status.setText('尚未编辑')

    def _mark_draft_edited(self, *_):
        self.draft_status.setText('草稿已编辑，尚未保存')

    def _apply_text(self):
        # Identity widgets are intentionally read-only.  Identity changes use
        # AccountRebindService so they cannot be mixed into task edits.
        value = json.loads(self.task_editor.toPlainText())
        if not isinstance(value, dict):
            raise ValueError("任务配置必须是 JSON 对象")
        self.draft.tasks = value
        for key, widget in self.form_widgets.items():
            if not widget.isEnabled():
                continue
            if isinstance(widget, QCheckBox):
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
                                            or "未记录（当前不参与任务）"))

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
        if not self.sequence_widgets:
            self.sequence_layout.addWidget(QLabel("暂无序列；请先在序列配置页新建序列。", self.sequence_group))

    def _render_form(self):
        from src.gui.SectionPanel import SectionPanel
        states = {key: panel.toggle_button.isChecked()
                  for key, panel in getattr(self, 'form_sections', {}).items()}
        while self.form_layout.rowCount():
            self.form_layout.removeRow(0)
        self.form_sections = {}
        self.form_widgets.clear()
        while self.identity_task_layout.count():
            item = self.identity_task_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        stamina = {'Which to Farm', 'Which Tacet Suppression to Farm', 'Which Forgery Challenge to Farm',
                   'Material Selection'}
        daily = {'Farm Nightmare Nest for Daily Echo', 'Nightmare Which to Farm', 'Tacet Discord Nests to Farm',
                 'Auto Farm all Nightmare Nest'}
        weekly = {'Weekly Garden Check Day', 'Merge Echo on Sunday'}
        def group(field):
            if field.key == 'Weekly Boss Target': return 2
            if field.key in stamina: return 1
            if field.key in daily: return 0
            if field.key in weekly: return 3
            if field.key == 'Logout After Daily Task': return 4
            return 5
        last_group = None
        fields = sorted(account_field_metadata(self.draft.tasks), key=group)
        for field in fields:
            identity_field = field.key in ('备用识别名称', '备用识别名称内容')
            if not identity_field and group(field) != last_group:
                last_group = group(field)
                heading = SectionPanel(('日常与声骸', '清理体力', '周本挑战', '周常安排', '收尾行为', '高级任务参数')[last_group],
                                       parent=self.form_host, collapsible=True,
                                       expanded=states.get(last_group, False))
                self.form_sections[last_group] = heading
                self.form_layout.addRow(heading)
            value = self.draft.tasks.get(field.key)
            if field.editor_type == "bool":
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
            else:
                heading.add_row(field.label, widget, field.help_text)
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(self._mark_draft_edited)
            elif isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._mark_draft_edited)
            else:
                widget.textEdited.connect(self._mark_draft_edited)
            if field.key == 'Weekly Boss Target':
                self._render_weekly_status()
        target = self.form_widgets.get('Weekly Boss Target')
        if target is not None and 2 in self.form_sections:
            def update_summary(*_):
                value = target.currentText()
                self.form_sections[2].set_summary('已关闭' if target.currentData() == '无' else f'目标：{value}；周一检查，周二至周六补检，周日复检')
            target.currentTextChanged.connect(update_summary)
            update_summary()
        for key, field_key in ((3, 'Weekly Garden Check Day'), (1, 'Which to Farm')):
            widget = self.form_widgets.get(field_key)
            if key in self.form_sections and isinstance(widget, QComboBox):
                def update_group_summary(*_, key=key, widget=widget):
                    self.form_sections[key].set_summary(widget.currentText())
                widget.currentTextChanged.connect(update_group_summary)
                update_group_summary()

    def _render_weekly_status(self):
        from src.config_integrity import get_default_service
        from src.task.weekly_boss import WEEKLY_MONDAY, WEEKLY_SUNDAY, weekly_check_window
        from datetime import datetime
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
                    self.form_sections[2].add_row(title, QLabel(f'{text}；最近：{stamp or "无"}', self.form_host))
                outcome = service.get_progress(f'weekly_boss:{self.draft.profile_id}', {})
                self.form_sections[2].add_row('最近周本结果', QLabel(str(outcome.get('status', '尚未执行')), self.form_host))
            except Exception:
                self.form_sections[2].add_row('周本记录', QLabel('记录暂不可读取', self.form_host))
        else:
            self.form_sections[2].add_row('周本记录', QLabel('记录服务未就绪', self.form_host))

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
                partial(self.rebind_service.rebind, profile_id, current_identity=current,
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
        for key, widget in self.form_widgets.items():
            if self.draft.tasks.get(key) == submitted.tasks.get(key):
                continue
            value = self.draft.tasks.get(key)
            if isinstance(widget, QCheckBox):
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
        self._loaded_sequences = tuple(sequence_ids)
        self.draft_status.setText('尚未编辑')

    def _submit_action(self, work, success_text, event=None, *, submitted=None, refresh=True,
                       saved_sequences=None):
        origin_id = self.selected_profile_id
        self.status.setText('正在保存配置…')
        def completed(result):
            started = perf_counter()
            self._failed_drafts.pop(origin_id, None)
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
