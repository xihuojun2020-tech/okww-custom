# -*- coding: utf-8 -*-
"""Integrity review controller and optional Qt dialog.

The controller is intentionally independent from Qt.  This keeps the safety
semantics testable in headless/command-line runs and makes it impossible for a
button labelled "acknowledge" to accidentally unlock task execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from src.config_integrity import ConfigIntegrityBlocked, ConfigIntegrityService, IntegrityResult


@dataclass
class IntegrityDialogState:
    acknowledged: bool = False
    master_change_confirmed: bool = False
    manual_review: bool = False
    closed: bool = False


class ConfigIntegrityDialogController:
    """State machine backing the review dialog.

    ``acknowledge`` only permits viewing details.  The primary action then
    applies the valid master to the complete working copy; there is no separate
    fingerprint-confirmation step and no ignore/continue transition.
    """

    def __init__(self, service: ConfigIntegrityService, *, on_exit: Optional[Callable[[], None]] = None):
        self.service = service
        self.state = IntegrityDialogState()
        self.on_exit = on_exit
        self.result: IntegrityResult = service.check()

    @property
    def can_run(self) -> bool:
        return bool(self.result.ok and not self.state.manual_review and not self.state.closed)

    @property
    def blocked(self) -> bool:
        return not self.can_run

    @property
    def runtime_available(self) -> bool:
        return not any(str(error).startswith('runtime state invalid:') for error in self.result.errors)

    @property
    def can_apply_master(self) -> bool:
        """Whether the acknowledged primary action may repair all accounts."""
        return bool(
            self.state.acknowledged and not self.state.manual_review and not self.state.closed and
            not self.result.master_missing and self.result.master_valid and
            self.runtime_available and bool(self.result.master)
        )

    @property
    def can_bootstrap_master(self) -> bool:
        """Whether a legacy working copy can be explicitly anchored."""
        return bool(
            self.state.acknowledged and not self.state.manual_review and not self.state.closed and
            self.result.master_missing and self.result.working_valid and self.runtime_available and
            not self.bootstrap_error
        )

    @property
    def bootstrap_error(self) -> str:
        if not self.result.master_missing:
            return ""
        return self.service.bootstrap_preflight_error(self.result)

    @property
    def primary_action_label(self) -> str:
        if self.result.master_missing:
            return "将当前账号配置锚定为总配置"
        return "使用总配置覆盖全部账号配置"

    @property
    def can_rebuild_runtime(self) -> bool:
        return bool(self.state.acknowledged and not self.state.closed and not self.runtime_available)

    @property
    def event_dir(self) -> Optional[Path]:
        return self.result.event_dir

    @staticmethod
    def _result_signature(result: IntegrityResult) -> tuple[Any, ...]:
        """Fields whose change requires the user to review the action again."""
        return (
            result.master_missing,
            result.master_fingerprint,
            result.working_fingerprint,
            result.accepted_fingerprint,
            result.errors,
            result.differences,
        )

    def acknowledge(self) -> IntegrityResult:
        previous_signature = self._result_signature(self.result)
        self.result = self.service.check()
        self.state.acknowledged = self._result_signature(self.result) == previous_signature
        return self.result

    def _refresh_before_action(self) -> None:
        expected_signature = self._result_signature(self.result)
        self.result = self.service.check()
        if self._result_signature(self.result) != expected_signature:
            self.state.acknowledged = False
            raise ConfigIntegrityBlocked("configuration changed after review; review and acknowledge it again")

    def confirm_master_change(self) -> IntegrityResult:
        if not self.state.acknowledged:
            raise ConfigIntegrityBlocked("view the differences before confirming a master change")
        self.result = self.service.accept_master_change(result=self.result)
        self.state.master_change_confirmed = True
        return self.result

    def apply_master(self) -> IntegrityResult:
        if not self.state.acknowledged:
            raise ConfigIntegrityBlocked("view the differences before applying the master configuration")
        self._refresh_before_action()
        if not self.can_apply_master:
            raise ConfigIntegrityBlocked("the master configuration is invalid or runtime state is unavailable")
        self.result = self.service.apply_master_to_working(result=self.result)
        self.state.master_change_confirmed = True
        return self.result

    def bootstrap_master(self) -> IntegrityResult:
        if not self.state.acknowledged:
            raise ConfigIntegrityBlocked("view the migration explanation before anchoring the legacy configuration")
        self._refresh_before_action()
        if not self.can_bootstrap_master:
            raise ConfigIntegrityBlocked(
                "first anchoring requires a missing master, valid working configuration and valid runtime state"
            )
        self.result = self.service.bootstrap_master_from_working(confirm=True)
        self.state.master_change_confirmed = True
        return self.result

    def rebuild_runtime_state(self) -> IntegrityResult:
        if not self.state.acknowledged:
            raise ConfigIntegrityBlocked("view the differences before rebuilding runtime state")
        self._refresh_before_action()
        if not self.can_rebuild_runtime:
            raise ConfigIntegrityBlocked("runtime state is no longer corrupt; review the current integrity result")
        self.result = self.service.rebuild_runtime_state(confirm=True)
        return self.result

    def restore_from_master(self) -> IntegrityResult:
        if not self.state.acknowledged:
            raise ConfigIntegrityBlocked("view the differences before restoring the working copy")
        # A valid changed master must be explicitly acknowledged first.
        if self.result.master_changed:
            raise ConfigIntegrityBlocked("confirm the master configuration change before restoring")
        self.result = self.service.restore_working_from_master(result=self.result)
        return self.result

    def choose_manual_review(self) -> None:
        self.state.manual_review = True
        self.state.closed = True
        if self.on_exit:
            self.on_exit()

    def recheck(self) -> IntegrityResult:
        previous_signature = self._result_signature(self.result)
        self.result = self.service.check()
        current_signature = self._result_signature(self.result)
        if not self.result.ok and current_signature != previous_signature:
            # A recheck can switch from the legacy-bootstrap branch to an
            # externally supplied master.  The earlier acknowledgement must
            # not authorize a materially different action.
            self.state.acknowledged = False
        if self.result.ok:
            self.state.manual_review = False
            self.state.closed = False
        return self.result

    def close(self) -> None:
        # Closing is equivalent to manual review and leaves the safety gate on.
        self.choose_manual_review()

    def summary(self) -> list[dict[str, Any]]:
        return list(self.result.differences)


try:  # Qt is optional for validator/CLI tests.
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QPushButton, QVBoxLayout

    class ConfigIntegrityDialog(QDialog):
        """Small blocking review dialog; all actions delegate to the controller."""

        def __init__(self, controller: ConfigIntegrityDialogController, parent=None):
            super().__init__(parent)
            self.controller = controller
            self.setWindowTitle("账号配置完整性检查")
            self.setModal(True)
            self.setMinimumWidth(620)
            layout = QVBoxLayout(self)
            self.message = QLabel()
            self.message.setWordWrap(True)
            layout.addWidget(self.message)
            self.diff_list = QListWidget()
            layout.addWidget(self.diff_list)
            self.view_button = QPushButton("已知晓并查看差异")
            self.apply_button = QPushButton(self.controller.primary_action_label)
            self.runtime_button = QPushButton("确认重建损坏的运行状态（可能重复执行）")
            self.manual_button = QPushButton("退出并保持安全模式")
            self.recheck_button = QPushButton("重新检查")
            for button in (self.view_button, self.apply_button, self.manual_button, self.recheck_button):
                layout.addWidget(button)
            layout.addWidget(self.runtime_button)
            self.view_button.clicked.connect(self._acknowledge)
            self.apply_button.clicked.connect(self._apply)
            self.manual_button.clicked.connect(self._manual)
            self.recheck_button.clicked.connect(self._recheck)
            self.runtime_button.clicked.connect(self._rebuild_runtime)
            self._render()

        def _render(self):
            result = self.controller.result
            self.diff_list.clear()
            for diff in result.differences:
                profile = diff.get("profile_id") or "全局"
                self.diff_list.addItem(f"{profile} / {diff.get('field')} ({diff.get('kind')})")
            message = self.controller.service.describe(result)
            if result.master_missing:
                bootstrap_error = self.controller.bootstrap_error
                message = (
                    "检测到旧版本账号配置：总配置尚不存在。程序不会自动创建总配置。\n"
                    "请先核对下方说明与账号配置；点击“已知晓”后，可明确选择将当前账号配置首次锚定为"
                    "只读总配置。该操作会为缺少 ID 的账号生成稳定 UUID，保留现有任务设置、账号顺序、"
                    "序列、完成记录和运行进度，并在失败时回滚。关闭窗口或选择安全模式不会写入任何配置。\n"
                    f"总配置将创建于：{self.controller.service.master_path}\n{message}"
                )
                if bootstrap_error:
                    message += f"\n当前不能锚定：{bootstrap_error}"
            elif not result.master_valid:
                message = f"总配置路径：{self.controller.service.master_path}\n{message}"
            self.message.setText(message)
            self.view_button.setText("已知晓并查看迁移说明" if result.master_missing else "已知晓并查看差异")
            self.apply_button.setText(self.controller.primary_action_label)
            self.apply_button.setEnabled(
                self.controller.can_bootstrap_master if result.master_missing else self.controller.can_apply_master
            )
            self.runtime_button.setEnabled(self.controller.can_rebuild_runtime)

        def _acknowledge(self):
            self.controller.acknowledge()
            self._render()

        def _apply(self):
            action_error = None
            try:
                if self.controller.result.master_missing:
                    self.controller.bootstrap_master()
                else:
                    self.controller.apply_master()
            except (ConfigIntegrityBlocked, OSError, ValueError) as exc:
                action_error = str(exc)
            self._render()
            if action_error:
                self.message.setText(f"操作未执行：{action_error}\n\n{self.message.text()}")
            if self.controller.can_run:
                self.accept()

        def _rebuild_runtime(self):
            action_error = None
            try:
                self.controller.rebuild_runtime_state()
            except (ConfigIntegrityBlocked, OSError, ValueError) as exc:
                action_error = str(exc)
            self._render()
            if action_error:
                self.message.setText(f"操作未执行：{action_error}\n\n{self.message.text()}")

        def _manual(self):
            self.controller.choose_manual_review()
            self.reject()

        def _recheck(self):
            self.controller.recheck()
            self._render()
            if self.controller.can_run:
                self.accept()

        def closeEvent(self, event):
            self.controller.close()
            event.accept()

except ImportError:  # pragma: no cover - exercised only without Qt installed.
    ConfigIntegrityDialog = None


__all__ = ["IntegrityDialogState", "ConfigIntegrityDialogController", "ConfigIntegrityDialog"]
