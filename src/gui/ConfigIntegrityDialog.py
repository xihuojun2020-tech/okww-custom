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
            self.result.master_valid and self.runtime_available and bool(self.result.master)
        )

    @property
    def can_rebuild_runtime(self) -> bool:
        return bool(self.state.acknowledged and not self.state.closed and not self.runtime_available)

    @property
    def event_dir(self) -> Optional[Path]:
        return self.result.event_dir

    def acknowledge(self) -> IntegrityResult:
        self.state.acknowledged = True
        self.result = self.service.check()
        return self.result

    def confirm_master_change(self) -> IntegrityResult:
        if not self.state.acknowledged:
            raise ConfigIntegrityBlocked("view the differences before confirming a master change")
        self.result = self.service.accept_master_change(result=self.result)
        self.state.master_change_confirmed = True
        return self.result

    def apply_master(self) -> IntegrityResult:
        if not self.state.acknowledged:
            raise ConfigIntegrityBlocked("view the differences before applying the master configuration")
        if not self.can_apply_master:
            raise ConfigIntegrityBlocked("the master configuration is invalid or runtime state is unavailable")
        self.result = self.service.apply_master_to_working(result=self.result)
        self.state.master_change_confirmed = True
        return self.result

    def rebuild_runtime_state(self) -> IntegrityResult:
        if not self.state.acknowledged:
            raise ConfigIntegrityBlocked("view the differences before rebuilding runtime state")
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
        self.result = self.service.check()
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
            self.apply_button = QPushButton("使用总配置覆盖全部账号配置")
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
            if not result.master_valid:
                message = f"总配置路径：{self.controller.service.master_path}\n{message}"
            self.message.setText(message)
            self.apply_button.setEnabled(self.controller.can_apply_master)
            self.runtime_button.setEnabled(self.controller.can_rebuild_runtime)

        def _acknowledge(self):
            self.controller.acknowledge()
            self._render()

        def _apply(self):
            try:
                self.controller.apply_master()
            except (ConfigIntegrityBlocked, OSError, ValueError) as exc:
                self.message.setText(str(exc))
            self._render()
            if self.controller.can_run:
                self.accept()

        def _rebuild_runtime(self):
            try:
                self.controller.rebuild_runtime_state()
            except (ConfigIntegrityBlocked, OSError, ValueError) as exc:
                self.message.setText(str(exc))
            self._render()

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
