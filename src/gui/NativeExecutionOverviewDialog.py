# SPDX-License-Identifier: AGPL-3.0-or-later
"""Select a verified worker and inspect existing account state without writes."""

from PySide6.QtCore import QFileSystemWatcher, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout)

from src.account_display import account_display_label, account_sort_key
from src.gui.AccountTaskOverview import AccountTaskOverview
from src.gui.DailyTimingDialog import DailyTimingDialog
from src.runtime.diagnostic_export import sanitize_text

from src.runtime.native_language import translate


class NativeExecutionOverviewDialog(QDialog):
    changed = Signal()

    def __init__(self, repository, live_reader, profile_id=None, timing_repository=None, parent=None):
        super().__init__(parent)
        self.repository, self.live_reader = repository, live_reader
        self.timing_repository = timing_repository
        self.setWindowTitle(translate('执行状态与每日耗时（只读）'))
        self.resize(1060, 760)
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel(translate('账号'), self))
        self.accounts = QComboBox(self)
        profiles = sorted(repository.list_profiles(), key=lambda p: account_sort_key(p.account, p.profile_id))
        for profile in profiles:
            self.accounts.addItem(account_display_label(profile.account), profile.profile_id)
        controls.addWidget(self.accounts, 1)
        controls.addWidget(QLabel(translate('执行进程'), self))
        self.workers = QComboBox(self)
        controls.addWidget(self.workers, 1)
        self.timings_button = QPushButton(translate('每日耗时记录'), self)
        controls.addWidget(self.timings_button)
        self.refresh_button = QPushButton(translate('刷新'), self)
        controls.addWidget(self.refresh_button)
        layout.addLayout(controls)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.overview = AccountTaskOverview(repository, self.live, self, readonly=True)
        layout.addWidget(self.overview, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.accounts.currentIndexChanged.connect(self._select_profile)
        self.workers.currentIndexChanged.connect(self._select_worker)
        self.timings_button.clicked.connect(self.show_timings)
        self.refresh_button.clicked.connect(self.reload)
        self.changed.connect(lambda: self.overview.refresh(force=True))
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.reload)
        self._watch_directory()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self._owners_signature = None
        self._read_error = ''
        self._timing_dialogs = []
        self._refresh_owners()
        self.set_profile(profile_id or self.accounts.currentData())

    def _watch_directory(self):
        # Watch an existing ancestor until the first worker creates its directory.
        path = self.live_reader.directory
        while not path.exists():
            path = path.parent
        wanted = str(path)
        if self.watcher.directories() != [wanted]:
            self.watcher.removePaths(self.watcher.directories())
            self.watcher.addPath(wanted)

    def reload(self, *_):
        try:
            self.live_reader.reload()
            self._read_error = ''
            self._watch_directory()
            self._refresh_owners()
            self._status()
            self.changed.emit()
            for dialog in self._timing_dialogs:
                dialog.refresh()
        except Exception as error:
            self._read_error = translate('执行状态读取失败：') + sanitize_text(error)
            self.status.setText(self._read_error)

    def _refresh_owners(self):
        owners = self.live_reader.owners()
        signature = tuple((o['process_session'], o['worker_pid']) for o in owners)
        if signature == self._owners_signature:
            return
        self._owners_signature = signature
        selected = self.workers.currentData()
        self.workers.blockSignals(True)
        self.workers.clear()
        self.workers.addItem(translate('无执行进程') if not owners else translate('请选择执行进程'), None)
        for owner in owners:
            self.workers.addItem(f"PID {owner['worker_pid']} · {owner['process_session'][:8]}",
                                 owner['process_session'])
        index = self.workers.findData(selected) if selected is not None else -1
        self.workers.setCurrentIndex(index if index > 0 else 1 if len(owners) == 1 else 0)
        self.workers.blockSignals(False)
        self.changed.emit()

    def _tick(self):
        if not self.isVisible():
            return
        try:
            self._refresh_owners()
            self._status()
        except Exception as error:
            self._read_error = translate('执行状态读取失败：') + sanitize_text(error)
            self.status.setText(self._read_error)

    def _status(self):
        if self._read_error:
            self.status.setText(self._read_error)
            return
        session = self.workers.currentData()
        owner = next((o for o in self.live_reader.owners() if o['process_session'] == session), None)
        if owner is None:
            self.status.setText(translate('未选择执行进程；展示已保存记录。'))
            return
        live = self.live_reader.live(session)
        label = translate('已暂停') if owner['paused'] else translate('执行中') if owner['running'] else translate('空闲 / 后台服务')
        detail = live.get('stage') or owner['foreground_task_id']
        self.status.setText(f"PID {owner['worker_pid']} · {label} · {detail}".rstrip(' ·'))

    def live(self):
        if self._read_error:
            return {}
        session = self.workers.currentData()
        return self.live_reader.live(session) if session is not None else {}

    def _select_worker(self, *_):
        self._status()
        self.changed.emit()

    def set_profile(self, profile_id):
        index = self.accounts.findData(profile_id) if profile_id is not None else -1
        if index >= 0:
            self.accounts.setCurrentIndex(index)
        self._select_profile()

    def _select_profile(self, *_):
        identity = self.accounts.currentData()
        self.timings_button.setEnabled(identity is not None and self.timing_repository is not None)
        if identity is not None:
            self.overview.set_profile(identity)

    def show_timings(self):
        identity = self.accounts.currentData()
        if identity is None or self.timing_repository is None:
            return
        dialog = DailyTimingDialog(self.timing_repository, identity, self,
                                   live_provider=self.live_reader.timings, readonly=True)
        self._timing_dialogs.append(dialog)
        dialog.finished.connect(lambda _: self._timing_dialogs.remove(dialog))
        dialog.show()
