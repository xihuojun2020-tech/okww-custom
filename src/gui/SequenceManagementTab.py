"""Standalone account-sequence management tab."""

from functools import partial
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractScrollArea, QHBoxLayout, QInputDialog, QListWidget,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)
from PySide6.QtWidgets import QSizePolicy
from qfluentwidgets import BodyLabel, FluentIcon

from ok.gui.widget.CustomTab import CustomTab
from src.account_repository import AccountRepository, AccountRepositoryError, get_default_repository
from src.account_config_editor import sanitize_error
from src.sequence_repository import SequenceRepository
from src.gui.AccountChangeEvent import AccountChangeEvent
from src.gui.BackgroundOperation import BackgroundOperation


class SequenceManagementTab(CustomTab):
    changed = Signal(object)

    def __init__(self, service=None):
        super().__init__()
        repository = get_default_repository() or AccountRepository()
        self.service = service or SequenceRepository(repository)
        root = QWidget(self.view)
        root.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(root)
        layout.setAlignment(Qt.AlignTop)
        layout.addWidget(BodyLabel("序列配置（运行开始后使用不可变快照；此处删除的是整个序列）"))
        self.sequences = QListWidget(root)
        self.members = QListWidget(root)
        # The account-settings hub embeds this page flat; keep both short
        # lists visible instead of creating another scroll surface.
        self.sequences.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sequences.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sequences.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.sequences.setMinimumHeight(32)
        self.members.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.members.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.members.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.members.setMinimumHeight(32)
        layout.addWidget(BodyLabel("当前序列"))
        layout.addWidget(self.sequences)
        layout.addWidget(BodyLabel("当前序列包含的账号（上下移动只调整账号顺序）"))
        layout.addWidget(self.members, 1)
        sequence_actions = QHBoxLayout()
        self.create_button = QPushButton("新建序列", root)
        self.delete_button = QPushButton("删除当前序列", root)
        for button in (self.create_button, self.delete_button):
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
        self.delete_button.clicked.connect(self._delete)
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button.clicked.connect(lambda: self._move(1))
        self.operation = BackgroundOperation(self, (self.create_button, self.delete_button,
                                                    self.up_button, self.down_button))
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

    def refresh(self, sequence_id=None):
        selected = sequence_id or (
            self._selected().sequence_id if getattr(self, "_drafts", None) and self._selected() else None)
        try:
            self._drafts = list(self.service.list())
        except AccountRepositoryError as exc:
            self._drafts = []
            self.sequences.clear()
            self.members.clear()
            self.status.setText(f"序列仓库暂不可用：{sanitize_error(exc)}")
            return
        self.sequences.clear()
        for item in self._drafts:
            self.sequences.addItem(item.sequence_id)
        row_height = self.sequences.sizeHintForRow(0) if self.sequences.count() else 24
        self.sequences.setFixedHeight(max(32, row_height * self.sequences.count() + 8))
        if self._drafts:
            names = [item.sequence_id for item in self._drafts]
            self.sequences.setCurrentRow(names.index(selected) if selected in names else 0)
            self._show_members()
        else:
            self.members.clear()

    def _selected(self):
        row = self.sequences.currentRow()
        return self._drafts[row] if 0 <= row < len(self._drafts) else None

    def _show_members(self, *_args):
        self.members.clear()
        item = self._selected()
        if not item:
            self.members.setFixedHeight(32)
            return
        profiles = {record.profile_id: record.account.get("display_name", "未命名账号")
                    for record in self.service.repository.list_profiles()}
        for profile_id in item.profile_ids:
            self.members.addItem(str(profiles.get(profile_id, "缺失账号")))
        # Keep every member row visible at once.  The list is deliberately
        # content-sized instead of relying on a nested scroll area.
        row_height = self.members.sizeHintForRow(0) if self.members.count() else 24
        self.members.setFixedHeight(max(32, row_height * self.members.count() + 8))

    def _name(self, title):
        return QInputDialog.getText(self.view, title, "序列名称")

    def _create(self):
        if self.operation.busy:
            return
        name, ok = self._name("新建序列")
        if ok and name.strip():
            revision = self._drafts[0].revision if self._drafts else 0
            self._run_action("新建序列", partial(self.service.create, name.strip(), expected_revision=revision))

    def _delete(self):
        if self.operation.busy:
            return
        item = self._selected()
        if not item:
            return
        answer = QMessageBox.question(self.view, "删除序列", f"确认删除 {item.sequence_id}？")
        if answer == QMessageBox.StandardButton.Yes:
            self._run_action("删除序列", partial(self.service.delete, item.sequence_id, expected_revision=item.revision))

    def _move(self, offset):
        if self.operation.busy:
            return
        item = self._selected()
        row = self.members.currentRow()
        target = row + offset
        if not item or row < 0 or target < 0 or target >= len(item.profile_ids):
            return
        members = list(item.profile_ids)
        members[row], members[target] = members[target], members[row]
        self._run_action("调整账号顺序", partial(self.service.publish,
                item.scope, {"profile_ids": members, "enabled": item.enabled}), selected_row=target)

    def _run_action(self, label, callback, *, selected_row=None):
        if self.operation.busy:
            return None
        original = self._selected()
        original_id = original.sequence_id if original else None
        self.status.setText(f"{label}中…")
        def completed(result):
            sequence_id = str(getattr(result, "sequence_id", "")) or None
            revision = str(getattr(result, "revision", ""))
            current = self._selected()
            same_selection = (current.sequence_id if current else None) == original_id
            self.refresh(sequence_id=sequence_id if same_selection else current.sequence_id if current else None)
            if same_selection and selected_row is not None:
                self.members.setCurrentRow(selected_row)
            self.status.setText(f"{label}成功")
            if sequence_id:
                self.changed.emit(AccountChangeEvent(
                    "sequence_changed", revision, (), (sequence_id,)))
        def failed(exc):
            self.status.setText(f"{label}失败：{sanitize_error(exc)}")
        return self.operation.start(callback, completed, failed)


__all__ = ["SequenceManagementTab"]
