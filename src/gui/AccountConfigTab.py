"""PC account task-configuration editor tab."""

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, FluentIcon

from ok.gui.widget.CustomTab import CustomTab
from src.account_config_editor import AccountConfigEditor
from src.account_repository import AccountRepository, get_default_repository


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
        self.task_editor = QPlainTextEdit(root)
        self.task_editor.setPlaceholderText("任务配置 JSON")
        layout.addWidget(self.task_editor, 1)
        actions = QHBoxLayout()
        self.preview_button = QPushButton("预览差异", root)
        self.save_button = QPushButton("确认保存", root)
        self.discard_button = QPushButton("丢弃草稿", root)
        for button in (self.preview_button, self.save_button, self.discard_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.status = BodyLabel("等待操作")
        layout.addWidget(self.status)
        self.add_widget(root, stretch=1)
        self.profile_combo.currentIndexChanged.connect(self._load_selected)
        self.preview_button.clicked.connect(self.preview)
        self.save_button.clicked.connect(self.save)
        self.discard_button.clicked.connect(self._load_selected)
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
        self.status.setText("已载入独立草稿")

    def _apply_text(self):
        value = json.loads(self.task_editor.toPlainText())
        if not isinstance(value, dict):
            raise ValueError("任务配置必须是 JSON 对象")
        self.draft.tasks = value

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


__all__ = ["AccountConfigTab"]
