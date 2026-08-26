"""Standalone account-sequence management tab."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QListWidget, QMessageBox, QPushButton, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, FluentIcon

from ok.gui.widget.CustomTab import CustomTab
from src.account_repository import AccountRepository, get_default_repository
from src.account_config_editor import sanitize_error
from src.sequence_repository import SequenceRepository


class SequenceManagementTab(CustomTab):
    def __init__(self, service=None):
        super().__init__()
        repository = get_default_repository() or AccountRepository()
        self.service = service or SequenceRepository(repository)
        root = QWidget(self.view)
        layout = QVBoxLayout(root)
        layout.setAlignment(Qt.AlignTop)
        layout.addWidget(BodyLabel("序列配置（运行开始后使用不可变快照；此处删除的是整个序列）"))
        self.sequences = QListWidget(root)
        self.members = QListWidget(root)
        layout.addWidget(BodyLabel("当前序列"))
        layout.addWidget(self.sequences)
        layout.addWidget(BodyLabel("当前序列包含的账号（上下移动只调整账号顺序）"))
        layout.addWidget(self.members, 1)
        sequence_actions = QHBoxLayout()
        self.create_button = QPushButton("新建", root)
        self.copy_button = QPushButton("复制", root)
        self.rename_button = QPushButton("重命名", root)
        self.enable_button = QPushButton("启用/停用", root)
        self.delete_button = QPushButton("删除当前序列", root)
        for button in (self.create_button, self.copy_button, self.rename_button, self.enable_button,
                       self.delete_button):
            sequence_actions.addWidget(button)
        layout.addLayout(sequence_actions)
        member_actions = QHBoxLayout()
        self.up_button = QPushButton("上移账号", root)
        self.down_button = QPushButton("下移账号", root)
        member_actions.addWidget(self.up_button)
        member_actions.addWidget(self.down_button)
        layout.addLayout(member_actions)
        self.status = BodyLabel("等待操作")
        layout.addWidget(self.status)
        self.add_widget(root, stretch=1)
        self.sequences.currentRowChanged.connect(self._show_members)
        self.create_button.clicked.connect(self._create)
        self.copy_button.clicked.connect(self._copy)
        self.rename_button.clicked.connect(self._rename)
        self.enable_button.clicked.connect(self._toggle)
        self.delete_button.clicked.connect(self._delete)
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button.clicked.connect(lambda: self._move(1))
        self.refresh()

    @property
    def name(self):
        return "序列管理"

    @property
    def icon(self):
        return FluentIcon.ALIGNMENT

    @property
    def add_after_default_tabs(self):
        return True

    def refresh(self):
        selected = self._selected().sequence_id if getattr(self, "_drafts", None) and self._selected() else None
        self._drafts = list(self.service.list())
        self.sequences.clear()
        for item in self._drafts:
            self.sequences.addItem(f"{item.sequence_id}（{'启用' if item.enabled else '停用'}）")
        if self._drafts:
            names = [item.sequence_id for item in self._drafts]
            self.sequences.setCurrentRow(names.index(selected) if selected in names else 0)
        else:
            self.members.clear()

    def _selected(self):
        row = self.sequences.currentRow()
        return self._drafts[row] if 0 <= row < len(self._drafts) else None

    def _show_members(self, *_args):
        self.members.clear()
        item = self._selected()
        if not item:
            return
        profiles = {record.profile_id: record.account.get("display_name", "未命名账号")
                    for record in self.service.repository.list_profiles()}
        for profile_id in item.profile_ids:
            self.members.addItem(str(profiles.get(profile_id, "缺失账号")))

    def _name(self, title):
        return QInputDialog.getText(self.view, title, "序列名称")

    def _create(self):
        name, ok = self._name("新建序列")
        if ok and name.strip():
            self._run_action("新建序列", lambda: self.service.create(name.strip()))

    def _copy(self):
        item = self._selected()
        if item:
            name, ok = self._name("复制序列")
            if ok and name.strip():
                self._run_action("复制序列", lambda: self.service.copy(item.sequence_id, name.strip()))

    def _rename(self):
        item = self._selected()
        if item:
            name, ok = self._name("重命名序列")
            if ok and name.strip():
                self._run_action("重命名序列", lambda: self.service.rename(item.sequence_id, name.strip()))

    def _toggle(self):
        item = self._selected()
        if item:
            self._run_action("更新序列状态",
                             lambda: self.service.set_enabled(item.sequence_id, not item.enabled))

    def _delete(self):
        item = self._selected()
        if not item:
            return
        answer = QMessageBox.question(self.view, "删除序列", f"确认删除 {item.sequence_id}？")
        if answer == QMessageBox.StandardButton.Yes:
            self._run_action("删除序列", lambda: self.service.delete(item.sequence_id))

    def _move(self, offset):
        item = self._selected()
        row = self.members.currentRow()
        target = row + offset
        if not item or row < 0 or target < 0 or target >= len(item.profile_ids):
            return
        members = list(item.profile_ids)
        members[row], members[target] = members[target], members[row]
        if self._run_action("调整账号顺序", lambda: self.service.publish(
                item.scope, {"profile_ids": members, "enabled": item.enabled})) is not None:
            self.members.setCurrentRow(target)

    def _run_action(self, label, callback):
        try:
            self.status.setText(f"{label}中…")
            result = callback()
            self.refresh()
            self.status.setText(f"{label}成功")
            return result
        except Exception as exc:
            self.status.setText(f"{label}失败：{sanitize_error(exc)}")
            return None


__all__ = ["SequenceManagementTab"]
