"""One in-flight disk operation, with results delivered on the owner's Qt thread."""

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot


class _ResultSignals(QObject):
    finished = Signal(int, object, object)


class _Work(QRunnable):
    def __init__(self, request_id, callback):
        super().__init__()
        self.request_id = request_id
        self.callback = callback
        self.signals = _ResultSignals()

    def run(self):
        try:
            value, error = self.callback(), None
        except Exception as exception:
            value, error = None, exception
        self.signals.finished.emit(self.request_id, value, error)


class BackgroundOperation(QObject):
    """Work callbacks receive captured data/services, never QWidget objects."""

    busy_changed = Signal(bool)

    def __init__(self, parent, controls=()):
        super().__init__(parent)
        self.controls = tuple(controls)
        self.busy = False
        self.request_id = 0
        self._worker = None
        self._callbacks = None

    def start(self, work, success, failure):
        if self.busy:
            return None
        self.request_id += 1
        self.busy = True
        self._enabled = [control.isEnabled() for control in self.controls]
        for control in self.controls:
            control.setEnabled(False)
        self._callbacks = (success, failure)
        self._worker = _Work(self.request_id, work)
        # Qt disconnects this bound receiver when its parent is destroyed;
        # late results cannot call callbacks that touch deleted widgets.
        self._worker.signals.finished.connect(self._finish, Qt.QueuedConnection)
        self.busy_changed.emit(True)
        QThreadPool.globalInstance().start(self._worker)
        return self.request_id

    @Slot(int, object, object)
    def _finish(self, request_id, value, error):
        if request_id != self.request_id or not self.busy:
            return
        success, failure = self._callbacks
        self._callbacks = None
        self._worker = None
        self.busy = False
        for control, enabled in zip(self.controls, self._enabled):
            control.setEnabled(enabled)
        self.busy_changed.emit(False)
        if error is None:
            success(value)
        else:
            failure(error)
