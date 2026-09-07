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

POLICY = 'automatic-v1'
SCHEDULER_REVISION = 2
DEFAULT_TARGET = r'\\192.168.3.170\xihuojun 共享给我\AI诊断'
REPO = Path(__file__).resolve().parents[2]


def installation_id(repo=REPO):
    return hashlib.sha256(os.path.normcase(str(Path(repo).resolve())).encode()).hexdigest()[:16]


def settings(root):
    path = Path(root) / 'settings.json'
    value = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    changed = value.get('policy') != POLICY
    if changed:
        value = {'policy': POLICY, 'started_at': time.time(), 'device_id': uuid.uuid4().hex,
                 'target': DEFAULT_TARGET}
    # The owner's mandatory upload policy supersedes the former opt-in flag.
    if changed or value.get('enabled') is not True:
        value['enabled'] = True
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


def connect(target):
    """Only called in the timeout-controlled SMB worker, never on the UI thread."""
    share = share_name(target)
    if os.name != 'nt' or not share:
        return
    import win32cred
    import win32wnet
    try:
        credential = win32cred.CredRead('okww-nas:' + share.casefold(), win32cred.CRED_TYPE_GENERIC)
    except Exception as error:
        if getattr(error, 'winerror', error.args[0] if error.args else None) == 1168:
            return  # Windows may already have a valid SMB session/domain login.
        raise
    secret = credential['CredentialBlob']
    if isinstance(secret, bytes):
        secret = secret.decode('utf-16-le')
    try:
        win32wnet.WNetAddConnection2(1, None, share, None, credential['UserName'], secret, 0)
    except Exception as error:
        # Never tear down unrelated connections to resolve error 1219.
        raise OSError('NAS authentication failed, Windows code ' + str(error.args[0])) from None
    finally:
        secret = credential = None


def ensure_task(root):
    path = Path(root) / 'scheduler.json'
    try:
        state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if (state.get('status') == 'installed' and state.get('root') == str(root)
                and state.get('revision') == SCHEDULER_REVISION
                and time.time() - state.get('checked_at', 0) < 86400):
            return
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                 '-File', str(REPO / 'src/runtime/install_diagnostic_task.ps1'),
                                 '-PythonExe', sys.executable, '-Root', str(root),
                                 '-TaskName', 'okww-diagnostics-' + installation_id()],
                                capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        atomic_json(path, {'status': 'installed' if result.returncode == 0 else 'failed',
                           'checked_at': time.time(), 'exit_code': result.returncode, 'root': str(root),
                           'revision': SCHEDULER_REVISION})
    except (OSError, subprocess.TimeoutExpired):
        atomic_json(path, {'status': 'failed', 'checked_at': time.time()})
