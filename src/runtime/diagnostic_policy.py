"""Owner-requested automatic diagnostics, isolated from pre-policy history."""
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from src.runtime.diagnostic_export import atomic_json
from src.runtime.nas_location import DEFAULT_TARGET, candidates, credential_shares

POLICY = 'automatic-v1'
SCHEDULER_REVISION = 6
LEGACY_TARGETS = {
    r'\\192.168.3.161\xihuojun 共享给我\AI诊断',
    r'\\192.168.3.170\xihuojun 共享给我\AI诊断',
    r'\\192.168.3.170\AI诊断',
}
REPO = Path(__file__).resolve().parents[2]
_binding = REPO / 'source.json'
if _binding.is_file():
    REPO = Path(json.loads(_binding.read_text(encoding='utf-8'))['source_repo']).resolve()


def installation_id(repo=REPO):
    return hashlib.sha256(os.path.normcase(str(Path(repo).resolve())).encode()).hexdigest()[:16]


def settings(root):
    path = Path(root) / 'settings.json'
    value = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    changed = value.get('policy') != POLICY
    if changed:
        value = {'policy': POLICY, 'started_at': time.time(), 'device_id': uuid.uuid4().hex,
                 'target': DEFAULT_TARGET}
    elif value.get('target') != DEFAULT_TARGET:
        value['target'] = DEFAULT_TARGET
        changed = True
    # Keep collection compatible with old evidence, but transport is now explicit.
    if changed or value.get('enabled') is not True or value.get('upload_mode') != 'manual_archive':
        value['enabled'] = True
        value['upload_mode'] = 'manual_archive'
        atomic_json(path, value)
    return value


def share_name(target):
    parts = str(target).replace('/', '\\').split('\\')
    if len(parts) < 4 or parts[:2] != ['', ''] or not parts[2] or not parts[3]:
        return None
    return '\\\\' + parts[2] + '\\' + parts[3]


def save_credentials(target, username, password):
    """Windows protects the secret for the current user; never write it to JSON."""
    import win32cred
    share = share_name(target)
    if not share or not username or not password:
        raise ValueError('NAS path, username and password are required')
    win32cred.CredWrite({'Type': win32cred.CRED_TYPE_GENERIC,
                        'TargetName': 'okww-nas:' + share.casefold(),
                        'UserName': username, 'CredentialBlob': password,
                        'Persist': win32cred.CRED_PERSIST_LOCAL_MACHINE}, 0)


def _windows_error_code(error):
    code = getattr(error, 'winerror', None)
    if code is None and error.args:
        code = error.args[0]
    return code if isinstance(code, int) else None


def _disconnect_target_connections(share, win32wnet):
    """Drop only SMB connections to this server so error 1219 can recover."""
    server = share.split('\\')[2].casefold()
    resources = []
    handle = None
    try:
        handle = win32wnet.WNetOpenEnum(1, 1, 0, None)  # connected, disk
        while True:
            try:
                batch = win32wnet.WNetEnumResource(handle, 0xFFFFFFFF)
                if not batch:
                    break
                resources.extend(batch)
            except Exception as error:
                if _windows_error_code(error) == 259:  # no more items
                    break
                raise
    finally:
        if handle is not None:
            win32wnet.WNetCloseEnum(handle)
    for resource in resources:
        remote = (resource.get('lpRemoteName') or '').replace('/', '\\')
        parts = remote.split('\\')
        if len(parts) >= 3 and parts[2].casefold() == server:
            win32wnet.WNetCancelConnection2(resource.get('lpLocalName') or remote, 0, True)


def connect(target):
    """Only called in the timeout-controlled SMB worker, never on the UI thread."""
    share = share_name(target)
    if os.name != 'nt' or not share:
        return
    import win32cred
    import win32wnet
    credential = None
    for saved_share in credential_shares(share):
        try:
            credential = win32cred.CredRead('okww-nas:' + saved_share.casefold(), win32cred.CRED_TYPE_GENERIC)
            break
        except Exception as error:
            if getattr(error, 'winerror', error.args[0] if error.args else None) != 1168:
                raise
    if credential is None:
        return  # Windows may already have a valid SMB session/domain login.
    secret = credential['CredentialBlob']
    if isinstance(secret, bytes):
        secret = secret.decode('utf-16-le')
    try:
        try:
            win32wnet.WNetAddConnection2(1, None, share, None, credential['UserName'], secret, 0)
        except Exception as error:
            if _windows_error_code(error) != 1219:
                raise
            _disconnect_target_connections(share, win32wnet)
            win32wnet.WNetAddConnection2(1, None, share, None, credential['UserName'], secret, 0)
    except Exception as error:
        code = _windows_error_code(error)
        message = ('NAS 连接被正在使用的同服务器共享阻止，请关闭该 NAS 上已打开的文件'
                   if code == 1219 else 'NAS authentication failed, Windows code ' + str(code))
        raise OSError(message) from None
    finally:
        secret = credential = None


def ensure_task(root):
    path = Path(root) / 'scheduler.json'
    try:
        state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        runtime = str(Path(sys.executable).resolve())
        working_directory = str(Path(__file__).resolve().parents[2])
        task_name = 'okww-diagnostics-' + installation_id()
        script = str(Path(__file__).with_name('install_diagnostic_task.ps1'))
        command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                   '-File', script, '-PythonExe', sys.executable, '-Root', str(root),
                   '-SourceRepo', str(REPO), '-TaskName', task_name]
        if settings(root).get('upload_mode') == 'manual_archive':
            result = subprocess.run(command + ['-Disable'], capture_output=True, timeout=20,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode == 0:
                stop_legacy_uploaders(root)
            atomic_json(path, {'status': 'manual' if result.returncode == 0 else 'failed',
                              'checked_at': time.time(), 'exit_code': result.returncode})
            return
        cached = (state.get('status') == 'installed' and state.get('root') == str(root)
                and state.get('revision') == SCHEDULER_REVISION
                and state.get('runtime') == runtime
                and state.get('working_directory') == working_directory
                and time.time() - state.get('checked_at', 0) < 86400)
        if cached:
            if state.get('system_verified') and time.time() - state.get('verified_at', 0) < 3600:
                return
            verified = subprocess.run(command + ['-Verify'], capture_output=True, timeout=20,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
            if verified.returncode == 0:
                state.update(system_verified=True, verified_at=time.time())
                atomic_json(path, state)
                return
        result = subprocess.run(command, capture_output=True, timeout=20,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        atomic_json(path, {'status': 'installed' if result.returncode == 0 else 'failed',
                           'checked_at': time.time(), 'exit_code': result.returncode, 'root': str(root),
                           'revision': SCHEDULER_REVISION, 'runtime': runtime,
                           'working_directory': working_directory,
                           'system_verified': result.returncode == 0})
    except (OSError, subprocess.TimeoutExpired):
        atomic_json(path, {'status': 'failed', 'checked_at': time.time()})


def stop_legacy_uploaders(root):
    """Stop detached workers only when both root and runtime ownership agree."""
    import psutil
    root = Path(root).resolve()
    for process in psutil.process_iter(['pid', 'cmdline', 'exe']):
        try:
            args = process.info['cmdline'] or []
            if process.pid == os.getpid() or 'src.runtime.diagnostic_uploader' not in args or '--root' not in args:
                continue
            index = args.index('--root')
            if index + 1 >= len(args) or Path(args[index + 1]).resolve() != root:
                continue
            if not process.info.get('exe'):
                continue
            executable = Path(process.info['exe']).resolve()
            binding = executable.parent.parent / 'ready.json'
            owned = executable.is_relative_to(REPO) and Path(process.cwd()).resolve() == REPO
            if binding.is_file():
                owned |= Path(json.loads(binding.read_text(encoding='utf-8'))['source_repo']).resolve() == REPO
            if owned:
                children = process.children(recursive=True)
                for child in reversed(children):child.terminate()
                process.terminate()
                _, alive = psutil.wait_procs([process, *children], timeout=5)
                if alive:raise OSError('旧上传器仍未退出，请关闭后重启程序')
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except psutil.AccessDenied as error:
            raise OSError('无法停止本程序的旧上传器，请退出旧程序后重试') from error
