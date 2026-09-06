"""One reentrant writer lock per configuration directory, shared across Windows processes."""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

_REGISTRY_GUARD = threading.Lock()
_LOCKS = {}


class AccountChangeLock:
    def __init__(self, directory):
        self._thread_lock = threading.RLock()
        self._local = threading.local()
        digest = hashlib.sha256(str(directory).encode('utf-8')).hexdigest()
        self._name = 'Local\\OKWW-AccountWrite-' + digest

    def __enter__(self):
        self._thread_lock.acquire()
        handle = None
        try:
            if os.name == 'nt':
                import win32event
                handle = win32event.CreateMutex(None, False, self._name)
                result = win32event.WaitForSingleObject(handle, 30000)
                if result not in (win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED):
                    raise TimeoutError('账号配置正在被其他进程修改，请稍后重试')
            if not hasattr(self._local, 'handles'):
                self._local.handles = []
            self._local.handles.append(handle)
            return self
        except BaseException:
            if handle is not None:
                handle.Close()
            self._thread_lock.release()
            raise

    def __exit__(self, *_args):
        handle = self._local.handles.pop()
        try:
            if handle is not None:
                import win32event
                try:
                    win32event.ReleaseMutex(handle)
                finally:
                    handle.Close()
        finally:
            self._thread_lock.release()


def get_account_change_lock(config_dir):
    key = os.path.normcase(str(Path(config_dir).resolve()))
    with _REGISTRY_GUARD:
        if key not in _LOCKS:
            _LOCKS[key] = AccountChangeLock(key)
        return _LOCKS[key]
