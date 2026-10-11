# SPDX-License-Identifier: MIT
"""Standalone stdlib bootstrap copied outside all versioned environments."""
from contextlib import contextmanager, ExitStack
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


class LeaseBusy(RuntimeError):
    pass


@contextmanager
def file_lease(path, exclusive):
    """Same one-byte shared/exclusive file protocol as gameframe.process_locks."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            from ctypes import wintypes
            class Overlapped(ctypes.Structure):
                _fields_ = [('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
                            ('Offset', wintypes.DWORD), ('OffsetHigh', wintypes.DWORD),
                            ('hEvent', wintypes.HANDLE)]
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            signature = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                         wintypes.DWORD, ctypes.POINTER(Overlapped))
            api.LockFileEx.argtypes, api.LockFileEx.restype = signature, wintypes.BOOL
            api.UnlockFileEx.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                        wintypes.DWORD, ctypes.POINTER(Overlapped))
            api.UnlockFileEx.restype = wintypes.BOOL
            handle, overlapped = msvcrt.get_osfhandle(stream.fileno()), Overlapped()
            if not api.LockFileEx(handle, 1 | (2 if exclusive else 0), 0, 1, 0, ctypes.byref(overlapped)):
                error = ctypes.get_last_error()
                if error == 33:
                    raise LeaseBusy('Managed environment is in use')
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
                    raise LeaseBusy('Managed environment is in use') from error
                raise
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.name, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def environment_path(root, value):
    relative = value['environment']
    if (not isinstance(relative, str) or Path(relative).is_absolute()
            or '\\' in relative or ':' in relative or '..' in Path(relative).parts):
        raise ValueError('Invalid managed environment pointer')
    environment = (root / relative).resolve()
    if environment.parent != root / 'versions':
        raise ValueError('Environment must be inside managed versions')
    return environment


def check_ready(root, value):
    environment = environment_path(root, value)
    receipt = environment / 'ready.json'
    if hashlib.sha256(receipt.read_bytes()).hexdigest() != value['receipt_sha256']:
        raise ValueError('Managed environment receipt does not match pointer')
    ready = read_json(receipt)
    if ready['bundle'] != value['bundle'] or ready['status'] != 'ready':
        raise ValueError('Managed environment was not preflighted for this release')
    for relative in ('Scripts/python.exe', 'Scripts/pythonw.exe'):
        if not (environment / relative).is_file():
            raise FileNotFoundError('Managed interpreter is absent: ' + relative)
    return environment


def automatic_commit_allowed(root, value):
    if type(value['automatic']) is not bool:
        raise ValueError('Pending automatic flag must be a boolean')
    if not value['automatic']:
        return True
    path = root / 'update-policy.json'
    policy = read_json(path)['policy'] if path.exists() else 'AUTO_UPDATE'
    if policy not in ('MANUAL_UPDATE', 'AUTO_UPDATE', 'AUTO_UPDATE_PRE_RELEASE'):
        raise ValueError('Invalid managed update policy')
    return policy == 'AUTO_UPDATE_PRE_RELEASE' or (policy == 'AUTO_UPDATE' and value['bundle']['channel'] == 'stable')


def report_update_error(root, value):
    try:
        atomic_json(root / 'last-update-error.json', value)
    except OSError as error:
        if sys.stderr is not None:
            print('Unable to save update error: ' + str(error), file=sys.stderr)
    if sys.stderr is not None:
        print('Managed update: ' + value['message'], file=sys.stderr)


def commit_pending(root, owners, *, lease, write):
    pending = root / 'pending.json'
    if not pending.exists():
        return
    value = None
    try:
        value = read_json(pending)
        previous_error = root / 'last-update-error.json'
        if previous_error.exists():
            error = read_json(previous_error)
            if error['status'] == 'failed' and error.get('pending') == value:
                return  # This failed candidate requires an explicit retry or a new preparation.
        if not automatic_commit_allowed(root, value):
            return
        with lease(owners, True):
            check_ready(root, value)
            active = root / 'active.json'
            if not active.exists() or read_json(active) != value:
                # Atomic replace is the only active-state commit point.
                write(active, value)
            try:
                pending.unlink()
                previous_error.unlink(missing_ok=True)
            except OSError as error:
                # Active is already committed; a retained pending is idempotent next time.
                report_update_error(root, {'status': 'committed', 'phase': 'cleanup',
                    'failure': type(error).__name__, 'message': str(error), 'pending': value})
    except LeaseBusy:
        return  # Existing GUI/worker owner keeps active; pending remains.
    except Exception as error:
        active = root / 'active.json'
        if not active.exists():
            raise
        check_ready(root, read_json(active))
        report_update_error(root, {'status': 'failed', 'phase': 'precommit',
            'failure': type(error).__name__, 'message': str(error), 'pending': value})


def launch(root, *, package_id=None, task=None, device=None, config=None,
           run=subprocess.run, lease=file_lease, write=atomic_json):
    """Commit at invocation and hold ownership until the selected child exits."""
    if task is None:
        if package_id is not None or device is not None or config is not None:
            raise ValueError('Scheduled arguments require a task')
    elif not task or not package_id or not isinstance(device, dict) or (config is not None and not isinstance(config, dict)):
        raise ValueError('Scheduled dispatch requires package id, task and device object')
    root = Path(root).resolve()
    installation = read_json(root / 'installation.json')
    if installation['managed_root'] != str(root):
        raise ValueError('Managed installation root changed')
    switch = root / '.leases/switch.lock'
    owners = root / '.leases/environment.lock'
    with ExitStack() as lifetime:
        with lease(switch, True):
            commit_pending(root, owners, lease=lease, write=write)
            value = read_json(root / 'active.json')
            environment = check_ready(root, value)
            lifetime.enter_context(lease(owners, False))
        command = [str(environment / 'Scripts/pythonw.exe'), '-m', 'gameframe', 'gui',
                   '--packages', str(environment / 'gamepacks'),
                   '--data-dir', installation['data_dir'], '--managed-root', str(root)]
        if task is not None:
            if package_id != value['bundle']['package_id']:
                raise ValueError('Scheduled package does not match active managed release')
            data_root = installation['data_dir']
            context_path = Path(data_root) / 'launcher-context.json'
            if context_path.exists():
                data_root = read_json(context_path).get('data_root', data_root)
            if str(data_root).startswith(('\\\\', '//')) or not Path(data_root).is_absolute():
                raise ValueError('Data directory must be an absolute local path')
            command = [str(environment / 'Scripts/pythonw.exe'), '-m', 'gameframe', 'run',
                       str(environment / 'gamepacks' / package_id), '--task', task,
                       '--data-dir', str(Path(data_root).resolve() / package_id),
                       '--device', json.dumps(device), '--config', json.dumps(config or {}),
                       '--managed-root', str(root)]
        process_environment = dict(os.environ)
        process_environment.pop('PYTHONPATH', None)
        process_environment['GAMEFRAME_MANAGED_ROOT'] = str(root)
        result = run(command, cwd=environment, env=process_environment, check=False)
        return result.returncode


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--managed-root', type=Path, required=True)
    parser.add_argument('--package-id')
    parser.add_argument('--task')
    def json_object(text):
        value = json.loads(text)
        if not isinstance(value, dict):
            raise argparse.ArgumentTypeError('Expected a JSON object')
        return value
    parser.add_argument('--device', type=json_object)
    parser.add_argument('--config', type=json_object)
    args = parser.parse_args(argv)
    if args.task is None and any(value is not None for value in (args.package_id, args.device, args.config)):
        parser.error('Scheduled arguments require --task')
    if args.task is not None and (not args.task or not args.package_id or args.device is None):
        parser.error('--task requires --package-id and --device')
    return launch(args.managed_root, package_id=args.package_id, task=args.task,
                  device=args.device, config=args.config)


if __name__ == '__main__':
    raise SystemExit(main())
