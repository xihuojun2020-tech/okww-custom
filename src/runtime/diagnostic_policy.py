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
SCHEDULER_REVISION = 5
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
    elif value.get('target') in LEGACY_TARGETS or candidates(value.get('target', ''))[0] != value.get('target'):
        value['target'] = candidates(value.get('target', ''))[0] if value.get('target') not in LEGACY_TARGETS else DEFAULT_TARGET
        changed = True
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
        runtime = str(Path(sys.executable).resolve())
        working_directory = str(Path(__file__).resolve().parents[2])
        task_name = 'okww-diagnostics-' + installation_id()
        script = str(Path(__file__).with_name('install_diagnostic_task.ps1'))
        command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                   '-File', script, '-PythonExe', sys.executable, '-Root', str(root),
                   '-SourceRepo', str(REPO), '-TaskName', task_name]
        cached = (state.get('status') == 'installed' and state.get('root') == str(root)
                and state.get('revision') == SCHEDULER_REVISION
                and state.get('runtime') == runtime
                and state.get('working_directory') == working_directory
                and time.time() - state.get('checked_at', 0) < 86400)
        if cached:
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
