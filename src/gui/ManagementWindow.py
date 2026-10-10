# SPDX-License-Identifier: AGPL-3.0-or-later
"""Account and completion management UI; never owns capture or input."""

import json
import sys
import threading

from PySide6.QtCore import Signal, Qt, QProcess
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout,
                               QLabel, QMainWindow, QMessageBox, QPushButton,
                               QTabWidget, QVBoxLayout, QWidget)

from src.account_config_editor import sanitize_error
from src.evidence.service import get_evidence_service
from src.gui.AccountConfigTab import NewAccountDialog
from src.gui.AccountSettingsTab import AccountSettingsTab
from src.gui.BackgroundOperation import BackgroundOperation
from src.gui.CompletionCheckTab import CompletionCheckTab
from src.gui.ConfigIntegrityDialog import ConfigIntegrityDialog, ConfigIntegrityDialogController
from src.gui.DiagnosticStatusCard import DiagnosticStatusCard
from src.runtime.native_diagnostics import diagnostic_root


class ManagementWindow(QMainWindow):
    stop_requested = Signal()

    def __init__(self, service):
        super().__init__()
        self.service = service
        self.stop_requested.connect(self.close, Qt.QueuedConnection)
        self.setWindowTitle('鸣潮账号与完成证据管理')
        self.resize(1180, 780)
        body = QWidget(self)
        layout = QVBoxLayout(body)
        self.notice = QLabel('独立管理窗口：账号设置、序列与已有完成证据；读取特征码和游戏截图需在任务窗口操作。', body)
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        row = QHBoxLayout()
        self.first_button = QPushButton('建立首个账号', body)
        self.import_button = QPushButton('导入账号配置包', body)
        self.export_button = QPushButton('导出账号配置包', body)
        self.review_button = QPushButton('完整性检查 / 锚定旧配置', body)
        self.folder_button = QPushButton('打开本地资料目录', body)
        for button in (self.first_button, self.import_button, self.export_button,
                       self.review_button, self.folder_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.status = QLabel(body)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.tabs = QTabWidget(body)
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(body)
        self.account_tab = None
        self.evidence_tab = None
        self.diagnostics_tab = DiagnosticStatusCard(
            root=diagnostic_root(service.root), source_root=service.root,
            program_version=service.runtime.program_version, local_only=True, capture_enabled=False)
        self.tabs.addTab(self.diagnostics_tab, '日志与诊断')
        self.configuration_tab = None
        self.update_tab = None
        self.maintenance_tab = None
        self.schedule_tab = None
        self._pending_maintenance = False
        self._configuration_restart_message = None
        self._maintenance_committed_failure = False
        if service.package_root is not None:
            from src.native_maintenance import NativeMaintenanceService
            from src.gui.NativeMaintenanceTab import NativeMaintenanceTab
            from src.gui.NativeScheduleTab import NativeScheduleTab
            from src.gui.NativeConfigurationTab import NativeConfigurationTab
            self.configuration_tab = NativeConfigurationTab(
                service.root, service.runtime.program_version, service.package_root / 'manifest.json')
            self.tabs.addTab(self.configuration_tab, '任务与配置')
            self.configuration_tab.management_requested.connect(self._show_account_management)
            self.maintenance_tab = NativeMaintenanceTab(
                NativeMaintenanceService(service.root, service.runtime.program_version), self._maintain)
            self.tabs.addTab(self.maintenance_tab, '配置备份与恢复')
            self.schedule_tab = NativeScheduleTab(service.package_root, service.root)
            self.tabs.addTab(self.schedule_tab, '系统定时任务')
            self.configuration_tab.schema_changed.connect(self.schedule_tab.set_schema)
            self.configuration_tab.schema_changed.connect(self._configuration_ready)
            self.configuration_tab.lifecycle_failed.connect(self._configuration_failed)
            if (service.package_root / 'files.json').is_file():
                from src.gui.NativeGamePackUpdateCard import NativeGamePackUpdateCard
                self.update_tab = NativeGamePackUpdateCard(
                    package_root=service.package_root, data_dir=service.root)
                self.tabs.addTab(self.update_tab, '游戏包更新')
            else:
                description = QLabel('当前为源码工作目录，不能在管理窗口替换游戏包；请使用已安装且带文件清单的游戏包。')
                description.setWordWrap(True)
                self.tabs.addTab(description, '游戏包更新')
        self.evidence_service = get_evidence_service(
            root=service.root / 'okww监控室' / 'CompletionEvidence')
        self.operation = BackgroundOperation(self, (self.first_button, self.import_button,
                                                     self.export_button, self.review_button))
        self._closing = False
        self.operation.busy_changed.connect(self._operation_changed)
        self.diagnostics_tab.operation.busy_changed.connect(self._operation_changed)
        if self.update_tab is not None:
            self.update_tab.operation.busy_changed.connect(self._operation_changed)
        if self.maintenance_tab is not None:
            self.maintenance_tab.operation.busy_changed.connect(self._operation_changed)
        self.first_button.clicked.connect(self._create_first)
        self.import_button.clicked.connect(self._import)
        self.export_button.clicked.connect(self._export)
        self.review_button.clicked.connect(self._review)
        self.folder_button.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(service.root))))
        self.refresh()

    def refresh(self):
        result = self.service.runtime.integrity_service.check(record_incident=False)
        self.first_button.setVisible(self.service.first_account_available())
        self.export_button.setEnabled(result.ok)
        self.status.setText('账号配置已验证，可在任务窗口执行。' if result.ok else
                            '安全模式：请建立首账号、导入配置包或查看完整性检查。\n' +
                            self.service.runtime.integrity_service.describe(result))
        if result.ok and self.account_tab is None:
            self.account_tab = AccountSettingsTab()
            self.account_tab.account_tab.read_feature_button.setEnabled(False)
            self.account_tab.account_tab.read_feature_button.setToolTip('管理窗口未连接游戏，请在任务窗口读取特征码')
            self.tabs.addTab(self.account_tab, '账号与序列')
            if self.evidence_tab is None:
                self.evidence_tab = CompletionCheckTab(None)
                self.tabs.addTab(self.evidence_tab, '完成检查')
                self.evidence_tab.load_operation.busy_changed.connect(self._operation_changed)
            else:
                self.evidence_tab.reload_accounts()
            self.account_tab.account_changed.connect(lambda _: self.evidence_tab.reload_accounts())
            self.account_tab.account_tab.operation.busy_changed.connect(self._operation_changed)
            self.account_tab.sequence_tab.operation.busy_changed.connect(self._operation_changed)
            if self.configuration_tab is not None:
                self.account_tab.account_changed.connect(self._account_config_changed)
        elif result.ok:
            self.account_tab.refresh_all()
            self.evidence_tab.reload_accounts()
        if self.account_tab is not None:
            self.account_tab.setEnabled(result.ok)
        return result

    def _failed(self, error):
        self.status.setText('操作失败：' + sanitize_error(error))
        print(json.dumps({'type': 'management-error', 'error': sanitize_error(error)}, ensure_ascii=False), flush=True)

    def _show_account_management(self):
        self.refresh()
        if self.account_tab is not None:
            self.tabs.setCurrentWidget(self.account_tab)
        else:
            self.first_button.setFocus()

    def _done(self, _result):
        result = self.refresh()
        if result.ok and self.configuration_tab is not None:
            self._reload_configuration()

    def _account_config_changed(self, event):
        if event.kind != 'graph_refreshed':
            self._reload_configuration()

    def _reload_configuration(self):
        try:
            self.configuration_tab.reload()
        except RuntimeError as error:
            self._failed(error)

    def _configuration_ready(self, _schema):
        if self._configuration_restart_message is not None:
            self.status.setText(self._configuration_restart_message + ' 配置进程已重新加载。')
            self._configuration_restart_message = None

    def _configuration_failed(self, message):
        prefix = self._configuration_restart_message or '配置进程启动失败。'
        self._configuration_restart_message = None
        self._failed(RuntimeError(prefix + ' 配置进程未恢复：' + message))

    def _rebuild_accounts(self):
        if self.account_tab is not None:
            old = self.account_tab
            self.tabs.removeTab(self.tabs.indexOf(old))
            old.deleteLater()
            self.account_tab = None
        # CompletionCheckTab resolves the fresh default account repository.
        self.refresh()

    def _maintain(self, work, success, failure, rebind):
        if self._operations_busy() or self._closing or self._maintenance_committed_failure:
            failure(RuntimeError('已有操作正在进行，或账号运行时需要重新启动；暂不能维护配置'))
            return
        self._pending_maintenance = True
        controls = (self.tabs, self.first_button, self.import_button,
                    self.export_button, self.review_button)
        enabled = tuple(control.isEnabled() for control in controls)
        for control in controls:
            control.setEnabled(False)
        try:
            self.configuration_tab.shutdown()
        except RuntimeError as error:
            for control, state in zip(controls, enabled):
                control.setEnabled(state)
            self._pending_maintenance = False
            failure(error)
            return

        def finish(value=None, error=None):
            from src.native_maintenance import MaintenanceCommittedError
            committed_failure = isinstance(error, MaintenanceCommittedError)
            self._maintenance_committed_failure = committed_failure
            try:
                for control, state in zip(controls, enabled):
                    control.setEnabled(state)
                if error is None:
                    if rebind:
                        self.service.rebind(self.maintenance_tab.service.runtime)
                        self._rebuild_accounts()
                    success(value)
                    message = '配置维护已提交。' if rebind else '配置备份已创建。'
                else:
                    failure(error)
                    message = '维护失败：' + sanitize_error(error)
                self.status.setText(message)
                if committed_failure:
                    for control in controls[1:]:
                        control.setEnabled(False)
                    if self.account_tab is not None:
                        self.account_tab.setEnabled(False)
                    self.configuration_tab.setEnabled(False)
                    self.maintenance_tab.setEnabled(False)
                    self.status.setText(message + ' 磁盘已提交，请重启管理窗口以重新加载账号；旧账号编辑已停用。')
                elif not self._closing:
                    self._configuration_restart_message = message
                    self.status.setText(message + ' 正在重新加载配置进程…')
                    self._reload_configuration()
            finally:
                self._pending_maintenance = False
                if self._closing:
                    self.close()

        self.operation.start(work, lambda value: finish(value=value),
                             lambda error: finish(error=error))

    def _create_first(self):
        dialog = NewAccountDialog(('序列1', '序列2'), self)
        dialog.short_name.setText('A1')
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            source, preview = self.service.preview_first_account(**dialog.values())
        except (RuntimeError, ValueError, OSError) as error:
            self._failed(error)
            return
        label = next(iter(source['profiles']))
        if QMessageBox.question(self, '确认建立首账号',
                f'建立账号 {label} 的可信总配置？请确认手机号、昵称及所选序列。') != QMessageBox.Yes:
            return
        self.operation.start(lambda: self.service.create_first_account(source, preview, confirm=True),
                             self._done, self._failed)

    def _import(self):
        filename, _ = QFileDialog.getOpenFileName(self, '选择账号配置包', str(self.service.root), 'JSON 配置包 (*.json)')
        if not filename:
            return
        preview = self.service.bundles.preflight_import(filename)
        if preview.errors:
            self._failed(RuntimeError('; '.join(preview.errors)))
            return
        text = (f'将替换当前全部账号配置：{preview.account_count} 个账号，{preview.sequence_count} 个序列，'
                f'{preview.runtime_record_count} 条完成记录。\n导入前将保存事务备份。')
        if preview.trust_required:
            text += '\n配置包已被外部修改；确认将明确接受这些修改。'
        if QMessageBox.question(self, '确认导入', text) != QMessageBox.Yes:
            return
        self.operation.start(lambda: self.service.bundles.import_bundle(
            filename, confirm=True, trust_external=preview.trust_required, preflight=preview),
            self._done, self._failed)

    def _export(self):
        filename, _ = QFileDialog.getSaveFileName(self, '导出账号配置包',
            str(self.service.root / '账号配置.json'), 'JSON 配置包 (*.json)')
        if filename:
            self.operation.start(lambda: self.service.bundles.export_bundle(filename),
                                 lambda _: self.status.setText('账号配置包已导出。'), self._failed)

    def _review(self):
        controller = ConfigIntegrityDialogController(self.service.runtime.integrity_service)
        ConfigIntegrityDialog(controller, self).exec()
        result = self.refresh()
        if (result.ok and self.configuration_tab is not None
                and self.configuration_tab.process.state() == QProcess.NotRunning):
            self._reload_configuration()

    def _operation_changed(self, busy):
        if not self._operations_busy() and self._closing:
            self.close()

    def _operations_busy(self):
        operations = [self.operation, self.diagnostics_tab.operation]
        if self.update_tab is not None:
            operations.append(self.update_tab.operation)
        if self.maintenance_tab is not None:
            operations.append(self.maintenance_tab.operation)
        if self.account_tab is not None:
            operations.extend((self.account_tab.account_tab.operation,
                               self.account_tab.sequence_tab.operation))
        if self.evidence_tab is not None:
            operations.append(self.evidence_tab.load_operation)
        details = getattr(self.diagnostics_tab, '_details', None)
        if details is not None:
            operations.append(details.operation)
        return self._pending_maintenance or any(operation.busy for operation in operations)

    def closeEvent(self, event):
        if self._operations_busy():
            self._closing = True
            event.ignore()
            return
        if self.configuration_tab is not None:
            try:
                self.configuration_tab.shutdown()
            except RuntimeError as error:
                self._closing = False
                self._failed(error)
                event.ignore()
                return
        if self.evidence_tab is not None:
            self.evidence_tab._export_cancel.set()
        super().closeEvent(event)


def run_management_window(service):
    app = QApplication.instance() or QApplication([])
    from src.gui.CodexTheme import apply_codex_light_theme
    apply_codex_light_theme(app)
    window = ManagementWindow(service)

    def read_commands():
        for line in sys.stdin:
            try:
                message = json.loads(line)
            except ValueError as error:
                print(json.dumps({'type': 'management-error', 'error': str(error)}), flush=True)
                continue
            if message.get('command') == 'stop':
                window.stop_requested.emit()
                return

    threading.Thread(target=read_commands, name='ManagementCommands', daemon=True).start()
    window.show()
    print(json.dumps({'type': 'management-ready'}), flush=True)
    result = app.exec()
    window.evidence_service.close()
    return result
