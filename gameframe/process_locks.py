"""Kernel-owned package and input leases shared by independent processes.

Callers acquire package, data and device leases in that order and keep them until
device cleanup completes. ADB and MuMu identities are backend-specific: an ADB
serial is not currently mapped to the corresponding MuMu installation/instance.
"""

from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import tempfile


class LeaseUnavailable(RuntimeError):
    """Another process currently owns an incompatible lease."""


def _canonical_path(path):
    return os.path.normcase(str(Path(path).resolve()))


def _digest(identity):
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode('utf-8')).hexdigest()


def _kernel32():
    from ctypes import wintypes
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    api.CreateMutexW.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    api.ReleaseMutex.restype = wintypes.BOOL
    api.CloseHandle.argtypes = (wintypes.HANDLE,)
    api.CloseHandle.restype = wintypes.BOOL
    api.GetCurrentThreadId.argtypes = ()
    api.GetCurrentThreadId.restype = wintypes.DWORD
    return api


def _windows_desktop_identity():
    """Name the current process window station and executing thread desktop."""
    from ctypes import wintypes
    api = ctypes.WinDLL('user32', use_last_error=True)
    api.GetProcessWindowStation.argtypes = ()
    api.GetProcessWindowStation.restype = wintypes.HANDLE
    api.GetThreadDesktop.argtypes = (wintypes.DWORD,)
    api.GetThreadDesktop.restype = wintypes.HANDLE
    api.GetUserObjectInformationW.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                              ctypes.c_void_p, wintypes.DWORD,
                                              ctypes.POINTER(wintypes.DWORD))
    api.GetUserObjectInformationW.restype = wintypes.BOOL

    def name(handle):
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        needed = wintypes.DWORD()
        # UOI_NAME=2: the first call obtains the required byte count.
        api.GetUserObjectInformationW(handle, 2, None, 0, ctypes.byref(needed))
        if not needed.value:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_unicode_buffer(needed.value // ctypes.sizeof(ctypes.c_wchar))
        if not api.GetUserObjectInformationW(handle, 2, buffer, needed.value, ctypes.byref(needed)):
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer.value.casefold()

    return (name(api.GetProcessWindowStation()),
            name(api.GetThreadDesktop(_kernel32().GetCurrentThreadId())))


@contextmanager
def _mutex_lease(name):
    api = _kernel32()
    handle = api.CreateMutexW(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    acquired = False
    try:
        status = api.WaitForSingleObject(handle, 0)
        if status == 0x102:  # WAIT_TIMEOUT: do not wait for another input owner.
            raise LeaseUnavailable('Device input is already owned by another process')
        if status not in (0, 0x80):  # WAIT_OBJECT_0 and WAIT_ABANDONED both grant ownership.
            raise ctypes.WinError(ctypes.get_last_error())
        acquired = True
        yield
    finally:
        try:
            if acquired and not api.ReleaseMutex(handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            if not api.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())


@contextmanager
def _file_lease(path, exclusive):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            from ctypes import wintypes

            class Overlapped(ctypes.Structure):
                _fields_ = [('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
                            ('Offset', wintypes.DWORD), ('OffsetHigh', wintypes.DWORD),
                            ('hEvent', wintypes.HANDLE)]

            api = _kernel32()
            api.LockFileEx.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                       wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped))
            api.LockFileEx.restype = wintypes.BOOL
            api.UnlockFileEx.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                         wintypes.DWORD, ctypes.POINTER(Overlapped))
            api.UnlockFileEx.restype = wintypes.BOOL
            handle = msvcrt.get_osfhandle(stream.fileno())
            overlapped = Overlapped()
            # FAIL_IMMEDIATELY=1; EXCLUSIVE_LOCK=2. Shared reads omit the latter.
            if not api.LockFileEx(handle, 1 | (2 if exclusive else 0), 0, 1, 0, ctypes.byref(overlapped)):
                error = ctypes.get_last_error()
                if error == 33:  # ERROR_LOCK_VIOLATION
                    raise LeaseUnavailable('Resource is in use by another process')
                raise ctypes.WinError(error)
            try:
                yield
            finally:
                if not api.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped)):
                    raise ctypes.WinError(ctypes.get_last_error())
        else:
            import errno
            import fcntl
            try:
                fcntl.flock(stream.fileno(), (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            except OSError as error:
                if error.errno in (errno.EACCES, errno.EAGAIN):
                    raise LeaseUnavailable('Resource is in use by another process') from error
                raise
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def device_input_lease(device_options):
    """Exclusively own one real input scope without constructing a device."""
    kind = device_options['type']
    if kind == 'replay':
        yield
        return
    if kind == 'windows':
        if os.name != 'nt':
            raise OSError('Windows desktop input requires Windows')
        identity = [kind, *_windows_desktop_identity()]
        namespace = 'Local'
    elif kind == 'adb':
        identity = [kind, device_options['serial']]
        namespace = 'Global'
    elif kind == 'mumu':
        identity = [kind, _canonical_path(device_options['install_dir']), device_options['instance_index']]
        namespace = 'Global'
    else:
        raise ValueError(f'Unknown device type: {kind}')
    digest = _digest(identity)
    if os.name == 'nt':
        with _mutex_lease(namespace + '\\GameFrameInput-' + digest):
            yield
    else:
        path = Path(tempfile.gettempdir()) / '.gameframe-locks' / ('input-' + digest + '.lock')
        with _file_lease(path, True):
            yield


@contextmanager
def package_lease(package_root, exclusive=False):
    """Share a package while executing, or exclude all owners while replacing it."""
    root = Path(package_root).resolve()
    path = root.parent / '.gameframe-locks' / ('package-' + _digest(_canonical_path(root)) + '.lock')
    with _file_lease(path, exclusive):
        yield


@contextmanager
def data_lease(data_dir, exclusive=False):
    """Share active configuration data, or exclude owners while restoring/moving it."""
    root = Path(data_dir).resolve()
    path = root.parent / '.gameframe-locks' / ('data-' + _digest(_canonical_path(root)) + '.lock')
    with _file_lease(path, exclusive):
        yield
