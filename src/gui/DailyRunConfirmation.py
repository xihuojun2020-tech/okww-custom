"""A cancellable, one-run confirmation; dialog access stays on the GUI thread."""

import threading
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Qt, Signal, Slot, QThread
from PySide6.QtWidgets import QMessageBox


@dataclass(eq=False)
class ConfirmationRequest:
    text: str
    done: threading.Event = field(default_factory=threading.Event)
    cancelled: threading.Event = field(default_factory=threading.Event)
    accepted: bool = False


class DailyRunConfirmation(QObject):
    requested = Signal(object)
    cancelled = Signal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self.dialogs = {}
        self.requested.connect(self._show, Qt.QueuedConnection)
        self.cancelled.connect(self._cancel, Qt.QueuedConnection)

    def confirm(self, task, text, timeout=60):
        if QThread.currentThread() == self.thread():
            return False
        request = ConfirmationRequest(text)
        deadline = time.monotonic() + timeout
        try:
            self.requested.emit(request)
            while not request.done.is_set():
                task.executor.check_enabled()
                if task.executor.exit_event.is_set() or time.monotonic() >= deadline:
                    return False
                # No combat sleep_check before the user has agreed to this run.
                request.done.wait(min(0.1, max(0, deadline - time.monotonic())))
            task.executor.check_enabled()
            return request.accepted and not request.cancelled.is_set() and not task.executor.exit_event.is_set()
        finally:
            request.cancelled.set()
            try:
                self.cancelled.emit(request)
            except RuntimeError:  # Parent destroyed while awaiting input.
                pass

    @Slot(object)
    def _show(self, request):
        if request.cancelled.is_set():
            request.done.set()
            return
        dialog = QMessageBox(self.parent())
        dialog.setWindowTitle(self.tr('Confirm daily account'))
        dialog.setTextFormat(Qt.PlainText)
        dialog.setText(request.text)
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        dialog.setDefaultButton(QMessageBox.Cancel)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        self.dialogs[request] = dialog

        def finished(result):
            request.accepted = result == QMessageBox.Yes and not request.cancelled.is_set()
            request.done.set()
            self.dialogs.pop(request, None)

        dialog.finished.connect(finished)
        dialog.destroyed.connect(lambda: request.done.set())
        dialog.open()

    @Slot(object)
    def _cancel(self, request):
        dialog = self.dialogs.get(request)
        if dialog is not None:
            dialog.reject()
