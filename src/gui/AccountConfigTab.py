"""PC account task-configuration editor tab."""

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QPushButton, QInputDialog,
                               QVBoxLayout, QWidget, QLineEdit)
from qfluentwidgets import BodyLabel, FluentIcon

from ok.gui.widget.CustomTab import CustomTab
from src.account_config_editor import AccountConfigEditor, sanitize_error
from src.account_rebind_service import AccountRebindService
from src.account_repository import AccountRepository, AccountRepositoryError, get_default_repository
from src.account_field_metadata import (account_field_metadata, localize_account_value,
                                        restore_account_value)
from src.gui.AccountChangeEvent import AccountChangeEvent


class ClickOnlyComboBox(QComboBox):
    """Keep wheel movement for the page; selection changes only from the menu."""

    def wheelEvent(self, event):
        event.ignore()


class AccountConfigTab(CustomTab):
    """Edit only non-identity task fields through a detached draft."""

    changed = Signal(object)

    def __init__(self, editor=None):
        super().__init__()
        repository = get_default_repository() or AccountRepository()
        self.editor = editor or AccountConfigEditor(repository)
        self.rebind_service = AccountRebindService(self.editor.repository)
        self.draft = None
        root = QWidget(self.view)
        layout = QVBoxLayout(root)
        layout.setAlignment(Qt.AlignTop)
        layout.addWidget(BodyLabel("账号配置（登录身份与唯一编号只读；删除操作仅针对当前账号）"))
        row = QHBoxLayout()
        row.addWidget(QLabel("账号"))
        self.profile_combo = QComboBox(root)
        row.addWidget(self.profile_combo, 1)
        layout.addLayout(row)
        self.metadata = BodyLabel("")
        self.metadata.setWordWrap(True)
        layout.addWidget(self.metadata)
        self.identity_group = QGroupBox("账号识别信息", root)
        self.identity_layout = QFormLayout(self.identity_group)
        self.identity_widgets = {}
        for key, label in (("phone", "完整手机号"), ("masked_phone", "带星号手机号（切换关键依据）"),
                           ("nickname", "游戏昵称"), ("alternate_login_name", "U…A 备用识别名")):
            widget = QLineEdit(self.identity_group)
            widget.setReadOnly(True)
            widget.setToolTip("身份字段由重新绑定流程修改，普通账号配置保存不会覆盖它")
            self.identity_widgets[key] = widget
            self.identity_layout.addRow(label, widget)
        self.feature_code_label = QLabel("未记录（当前不参与任务）", self.identity_group)
        self.feature_code_label.setToolTip("来自游戏防 OLED 烧屏遮罩区域；当前只记录，不参与任务")
        self.identity_layout.addRow("游戏内特征码（只读）", self.feature_code_label)
        layout.addWidget(self.identity_group)
        self.sequence_group = QGroupBox("所属序列（勾选后保存即可调整当前账号归属）", root)
        self.sequence_layout = QVBoxLayout(self.sequence_group)
        self.sequence_widgets = {}
        layout.addWidget(self.sequence_group)
        self.form_host = QWidget(root)
        self.form_layout = QFormLayout(self.form_host)
        self.form_widgets = {}
        layout.addWidget(self.form_host)
        layout.addWidget(BodyLabel("高级 JSON（复杂列表或兼容字段；常用字段请优先使用上方中文表单）"))
        self.task_editor = QPlainTextEdit(root)
        self.task_editor.setPlaceholderText("任务配置 JSON")
        layout.addWidget(self.task_editor, 1)
        actions = QHBoxLayout()
        self.preview_button = QPushButton("预览差异", root)
        self.save_button = QPushButton("确认保存", root)
        self.discard_button = QPushButton("丢弃草稿", root)
        self.delete_button = QPushButton("删除当前账号", root)
        self.rebind_button = QPushButton("重新绑定身份", root)
        for button in (self.preview_button, self.save_button, self.discard_button,
                       self.rebind_button, self.delete_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.status = BodyLabel("等待操作")
        layout.addWidget(self.status)
        self.add_widget(root, stretch=1)
        self.profile_combo.currentIndexChanged.connect(self._load_selected)
        self.preview_button.clicked.connect(self.preview)
        self.save_button.clicked.connect(self.save)
        self.discard_button.clicked.connect(self._load_selected)
        self.delete_button.clicked.connect(self.delete_account)
        self.rebind_button.clicked.connect(self.rebind_identity)
        self.refresh()

    @property
    def name(self):
        return "账号配置"

    @property
    def icon(self):
        return FluentIcon.SETTING

    @property
    def add_after_default_tabs(self):
        return True

    def refresh(self, profile_id=None):
        selected_id = profile_id or self.profile_combo.currentData()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        try:
            records = self.editor.repository.list_profiles()
            for record in records:
                label = str(record.account.get("display_name", "未命名账号"))
                self.profile_combo.addItem(label, record.profile_id)
        except AccountRepositoryError as exc:
            # A missing master is a safe-mode state during first launch or
            # after an incomplete import.  Keep the shell visible so the
            # integrity dialog can explain/recover it instead of crashing UI.
            self.status.setText(f"账号仓库暂不可用：{sanitize_error(exc)}")
        finally:
            self.profile_combo.blockSignals(False)
        if selected_id:
            index = self.profile_combo.findData(selected_id)
            self.profile_combo.setCurrentIndex(index if index >= 0 else 0)
        self._load_selected()

    def refresh_sequences(self):
        """Refresh membership checkboxes without discarding an unsaved draft."""
        self._render_sequences()

    def _load_selected(self, *_args):
        profile_id = self.profile_combo.currentData()
        if not profile_id:
            return
        self.draft = self.editor.load_draft(profile_id)
        label = self.draft.account.get("display_name", "未命名账号")
        masked_phone = self.draft.account.get("masked_phone") or "未记录"
        alternate = self.draft.account.get("alternate_login_name") or "未记录"
        feature_code = self.draft.account.get("game_feature_code") or "未记录（当前不参与任务）"
        self.metadata.setText(
            f"账号短名：{label}\n唯一编号：{self.draft.profile_id}\n"
            f"切换关键识别：{masked_phone}\n备用识别名：{alternate}\n"
            f"游戏内特征码：{feature_code}"
        )
        self._render_sequences()
        self._render_identity()
        self.task_editor.setPlainText(json.dumps(self.draft.tasks, ensure_ascii=False, indent=2))
        self._render_form()
        self.status.setText("已载入独立草稿")

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
                self.draft.tasks[key] = widget.currentData()
            else:
                text = widget.text()
                original = self.draft.tasks.get(key)
                if isinstance(original, int):
                    self.draft.tasks[key] = int(text)
                elif isinstance(original, float):
                    self.draft.tasks[key] = float(text)
                elif isinstance(original, (list, dict)):
                    self.draft.tasks[key] = restore_account_value(json.loads(text))
                else:
                    self.draft.tasks[key] = restore_account_value(text)

    def _render_identity(self):
        if self.draft is None:
            return
        for key, widget in self.identity_widgets.items():
            widget.setText(str(self.draft.account.get(key) or ""))
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
            self.sequence_widgets[sequence_id] = box
            self.sequence_layout.addWidget(box)
        if not self.sequence_widgets:
            self.sequence_layout.addWidget(QLabel("暂无序列；请先在序列配置页新建序列。", self.sequence_group))

    def _render_form(self):
        while self.form_layout.rowCount():
            self.form_layout.removeRow(0)
        self.form_widgets.clear()
        for field in account_field_metadata(self.draft.tasks):
            value = self.draft.tasks.get(field.key)
            label = QLabel(f"{field.label}\n{field.help_text}", self.form_host)
            label.setWordWrap(True)
            if field.editor_type == "bool":
                widget = QCheckBox(self.form_host)
                widget.setChecked(bool(value))
            elif field.editor_type == "choice":
                widget = (ClickOnlyComboBox(self.form_host)
                          if field.key == "Which to Farm" else QComboBox(self.form_host))
                for option, option_label in zip(field.options, field.option_labels):
                    widget.addItem(option_label, option)
                index = widget.findData(value)
                widget.setCurrentIndex(max(index, 0))
            else:
                from PySide6.QtWidgets import QLineEdit
                widget = QLineEdit(self.form_host)
                display_value = localize_account_value(value)
                widget.setText(json.dumps(display_value, ensure_ascii=False)
                               if isinstance(display_value, (list, dict)) else str(display_value))
            widget.setEnabled(not field.read_only)
            widget.setToolTip(field.help_text)
            self.form_widgets[field.key] = widget
            self.form_layout.addRow(label, widget)

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
        try:
            self._apply_text()
            label = str(self.draft.account.get("display_name", self.draft.profile_id))
            sequence_ids = tuple(name for name, box in self.sequence_widgets.items() if box.isChecked())
            answer = QMessageBox.question(self.view, "确认账号", f"确认保存账号 {label} 的修改？")
            if answer != QMessageBox.Yes:
                return None
            result = self.editor.save_draft(self.draft.scope, self.draft,
                                            confirmed_account_label=label,
                                            sequence_ids=sequence_ids)
            self.status.setText("保存成功，已先创建账号备份")
            profile_id = self.draft.profile_id
            revision = str(getattr(result, "revision", ""))
            self.refresh(profile_id=profile_id)
            self.changed.emit(AccountChangeEvent(
                "profile_saved", revision, (profile_id,), tuple(sequence_ids)))
            return result
        except Exception as exc:
            self.status.setText(f"保存失败：{exc}")
            return None

    def rebind_identity(self):
        """Run the explicit identity re-bind flow for the selected account."""
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
                f"账号 {self.draft.account.get('display_name', self.draft.profile_id)} 将修改：{changes}\n"
                "旧身份会先备份，是否继续？")
            if answer != QMessageBox.StandardButton.Yes:
                return None
            result = self.rebind_service.rebind(
                self.draft.profile_id, current_identity=current,
                new_identity=requested, confirmed=True)
            self.status.setText("身份重新绑定成功，已创建旧身份备份")
            profile_id = self.draft.profile_id
            self.refresh(profile_id=profile_id)
            self.changed.emit(AccountChangeEvent("identity_rebound", str(getattr(result, "revision", "")),
                                                 (profile_id,), ()))
            return result
        except Exception as exc:
            self.status.setText(f"身份重新绑定失败：{sanitize_error(exc)}")
            return None

    def delete_account(self):
        if self.draft is None:
            return None
        label = str(self.draft.account.get("display_name") or
                    self.draft.account.get("short_name") or "未命名账号")
        preview = self.editor.repository.preview_profile_deletion(self.draft.profile_id)
        first = QMessageBox.question(self.view, "删除账号", f"确认删除账号 {label}？")
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
            result = self.editor.delete_profile(self.draft.scope, confirmed_account_label=label)
            self.status.setText("账号删除成功，序列引用已同步移除")
            profile_id = self.draft.profile_id
            self.refresh()
            self.changed.emit(AccountChangeEvent(
                "profile_deleted", "", (profile_id,), tuple(preview.sequence_ids)))
            return result
        except Exception as exc:
            self.status.setText(f"账号删除失败：{sanitize_error(exc)}")
            return None


__all__ = ["AccountConfigTab", "ClickOnlyComboBox"]
