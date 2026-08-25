"""Standalone account-sequence management tab."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QListWidget, QMessageBox, QPushButton, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, FluentIcon

from ok.gui.widget.CustomTab import CustomTab
from src.account_repository import AccountRepository, get_default_repository
from src.sequence_repository import SequenceRepository


class SequenceManagementTab(CustomTab):
    def __init__(self, service=None):
        super().__init__()
        repository = get_default_repository() or AccountRepository()
        self.service = service or SequenceRepository(repository)
        root = QWidget(self.view)
        layout = QVBoxLayout(root)
        layout.setAlignment(Qt.AlignTop)
        layout.addWidget(BodyLabel("账号序列管理（运行开始后使用不可变快照）"))
        self.sequences = QListWidget(root)
        self.members = QListWidget(root)
        layout.addWidget(self.sequences)
        layout.addWidget(self.members, 1)
        actions = QHBoxLayout()
        self.create_button = QPushButton("新建", root)
        self.copy_button = QPushButton("复制", root)
        self.rename_button = QPushButton("重命名", root)
        self.enable_button = QPushButton("启用/停用", root)
        self.delete_button = QPushButton("删除", root)
        self.up_button = QPushButton("上移", root)
        self.down_button = QPushButton("下移", root)
        for button in (self.create_button, self.copy_button, self.rename_button, self.enable_button,
                       self.delete_button, self.up_button, self.down_button):
            actions.addWidget(button)
        layout.addLayout(actions)
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
        self._drafts = list(self.service.list())
        self.sequences.clear()
        for item in self._drafts:
            self.sequences.addItem(f"{item.sequence_id}（{'启用' if item.enabled else '停用'}）")
        if self._drafts:
            self.sequences.setCurrentRow(0)
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
            self.service.create(name.strip())
            self.refresh()

    def _copy(self):
        item = self._selected()
        if item:
            name, ok = self._name("复制序列")
            if ok and name.strip():
                self.service.copy(item.sequence_id, name.strip())
                self.refresh()

    def _rename(self):
        item = self._selected()
        if item:
            name, ok = self._name("重命名序列")
            if ok and name.strip():
                self.service.rename(item.sequence_id, name.strip())
                self.refresh()

    def _toggle(self):
        item = self._selected()
        if item:
            self.service.set_enabled(item.sequence_id, not item.enabled)
            self.refresh()

    def _delete(self):
        item = self._selected()
        if item and QMessageBox.question(self.view, "删除序列", f"确认删除 {item.sequence_id}？") == QMessageBox.Yes:
            self.service.delete(item.sequence_id)
            self.refresh()

    def _move(self, offset):
        item = self._selected()
        row = self.members.currentRow()
        target = row + offset
        if not item or row < 0 or target < 0 or target >= len(item.profile_ids):
            return
        members = list(item.profile_ids)
        members[row], members[target] = members[target], members[row]
        self.service.publish(item.scope, {"profile_ids": members, "enabled": item.enabled})
        self.refresh()
        self.members.setCurrentRow(target)


__all__ = ["SequenceManagementTab"]
