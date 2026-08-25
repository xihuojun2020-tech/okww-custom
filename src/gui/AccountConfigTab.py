"""PC account task-configuration editor tab."""

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)
from qfluentwidgets import BodyLabel, FluentIcon

from ok.gui.widget.CustomTab import CustomTab
from src.account_config_editor import AccountConfigEditor, sanitize_error
from src.account_repository import AccountRepository, get_default_repository
from src.account_field_metadata import (account_field_metadata, localize_account_value,
                                        restore_account_value)


class ClickOnlyComboBox(QComboBox):
    """Keep wheel movement for the page; selection changes only from the menu."""

    def wheelEvent(self, event):
        event.ignore()


class AccountConfigTab(CustomTab):
    """Edit only non-identity task fields through a detached draft."""

    def __init__(self, editor=None):
        super().__init__()
        repository = get_default_repository() or AccountRepository()
        self.editor = editor or AccountConfigEditor(repository)
        self.draft = None
        root = QWidget(self.view)
        layout = QVBoxLayout(root)
        layout.setAlignment(Qt.AlignTop)
        layout.addWidget(BodyLabel("账号配置（登录身份与唯一编号只读）"))
        row = QHBoxLayout()
        row.addWidget(QLabel("账号"))
        self.profile_combo = QComboBox(root)
        row.addWidget(self.profile_combo, 1)
        layout.addLayout(row)
        self.metadata = BodyLabel("")
        self.metadata.setWordWrap(True)
        layout.addWidget(self.metadata)
        self.form_host = QWidget(root)
        self.form_layout = QFormLayout(self.form_host)
        self.form_widgets = {}
        form_scroll = QScrollArea(root)
        form_scroll.setWidgetResizable(True)
        form_scroll.setWidget(self.form_host)
        layout.addWidget(form_scroll, 1)
        layout.addWidget(BodyLabel("高级 JSON（复杂列表或兼容字段；常用字段请优先使用上方中文表单）"))
        self.task_editor = QPlainTextEdit(root)
        self.task_editor.setPlaceholderText("任务配置 JSON")
        layout.addWidget(self.task_editor, 1)
        actions = QHBoxLayout()
        self.preview_button = QPushButton("预览差异", root)
        self.save_button = QPushButton("确认保存", root)
        self.discard_button = QPushButton("丢弃草稿", root)
        self.delete_button = QPushButton("删除账号", root)
        for button in (self.preview_button, self.save_button, self.discard_button, self.delete_button):
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

    def refresh(self):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for record in self.editor.repository.list_profiles():
            label = str(record.account.get("display_name", "未命名账号"))
            self.profile_combo.addItem(label, record.profile_id)
        self.profile_combo.blockSignals(False)
        self._load_selected()

    def _load_selected(self, *_args):
        profile_id = self.profile_combo.currentData()
        if not profile_id:
            return
        self.draft = self.editor.load_draft(profile_id)
        label = self.draft.account.get("display_name", "未命名账号")
        self.metadata.setText(f"账号短名：{label}\n唯一编号：{self.draft.profile_id}\n登录身份：已锁定，不在页面显示")
        self.task_editor.setPlainText(json.dumps(self.draft.tasks, ensure_ascii=False, indent=2))
        self._render_form()
        self.status.setText("已载入独立草稿")

    def _apply_text(self):
        value = json.loads(self.task_editor.toPlainText())
        if not isinstance(value, dict):
            raise ValueError("任务配置必须是 JSON 对象")
        self.draft.tasks = value
        for key, widget in self.form_widgets.items():
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
            answer = QMessageBox.question(self.view, "确认账号", f"确认保存账号 {label} 的修改？")
            if answer != QMessageBox.Yes:
                return None
            result = self.editor.save_draft(self.draft.scope, self.draft, confirmed_account_label=label)
            self.status.setText("保存成功，已先创建账号备份")
            self._load_selected()
            return result
        except Exception as exc:
            self.status.setText(f"保存失败：{exc}")
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
            self.refresh()
            return result
        except Exception as exc:
            self.status.setText(f"账号删除失败：{sanitize_error(exc)}")
            return None


__all__ = ["AccountConfigTab", "ClickOnlyComboBox"]
