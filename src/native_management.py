"""Management requests delegated to the launcher's existing live owner."""

from concurrent.futures import Future
import json
from uuid import uuid4

from PySide6.QtCore import QObject, Signal, Qt


class NativeLiveBridge(QObject):
    response_received = Signal(dict)
    disconnected = Signal(str)

    def __init__(self, parent=None, *, emit=None):
        super().__init__(parent)
        self._emit = emit or self._stdout
        self._pending = {}
        self._disconnect_error = None
        self.response_received.connect(self.receive, Qt.QueuedConnection)
        self.disconnected.connect(self.fail_pending, Qt.QueuedConnection)

    @staticmethod
    def _stdout(message):
        print(json.dumps(message, ensure_ascii=False), flush=True)

    def request(self, command, **values):
        future = Future()
        future.request_id = str(uuid4())
        if self._disconnect_error is not None:
            future.set_exception(RuntimeError(self._disconnect_error))
            return future
        self._pending[future.request_id] = future
        try:
            self._emit({'event': 'live-request', 'request_id': future.request_id,
                        'command': command, **values})
        except Exception as error:
            self._pending.pop(future.request_id)
            future.set_exception(error)
        return future

    def receive(self, response):
        future = self._pending.pop(response.get('request_id'), None)
        if future is None or future.done():
            return
        if response['ok']:
            future.set_result(response.get('result', response))
        else:
            future.set_exception(RuntimeError(response['error']['message']))

    def fail_pending(self, message):
        self._disconnect_error = message
        pending, self._pending = self._pending, {}
        for future in pending.values():
            if not future.done():
                future.set_exception(RuntimeError(message))


def read_management_commands(window, stream):
    """The stdin thread only emits queued Qt signals."""
    for line in stream:
        try:
            message = json.loads(line)
        except ValueError as error:
            print(json.dumps({'type': 'management-error', 'error': str(error)}), flush=True)
            continue
        if message.get('command') == 'stop':
            window.live_bridge.disconnected.emit('管理窗口正在关闭')
            window.stop_requested.emit()
            return
        if message.get('command') == 'live-response':
            window.live_bridge.response_received.emit(message['response'])
    window.live_bridge.disconnected.emit('启动器连接已关闭')
