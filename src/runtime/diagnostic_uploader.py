"""Bounded, restartable SMB transfers. Run with python -m ...diagnostic_uploader."""
from __future__ import annotations

import argparse
import errno
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from src.runtime.diagnostic_export import atomic_json, digest, safe_path, sanitize_text, validate_manifest
from src.runtime.diagnostic_session import FileLease, default_root, recover_sessions, seal_run
from src.runtime.diagnostic_policy import POLICY, DEFAULT_TARGET, REPO, settings, connect, ensure_task, save_credentials

RETRY = (5, 15, 60, 300, 900)


def bounded_read(root, name, limit):
    path = safe_path(root, name)
    if path.stat().st_size > limit:
        raise ValueError('diagnostic control file too large')
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('diagnostic control file grew beyond limit')
    return data


def control_directory(manifest):
    first = manifest['files'][0]['path']
    parent = str(Path(first).parent).replace('\\', '/')
    parts = parent.split('/')
    if (len(parts) != 5 or parts[1] != 'okww-custom'
            or parts[3] != manifest.get('run_id') or parts[4] != manifest.get('batch_id')):
        raise ValueError('manifest identity does not match batch directory')
    if not parent.startswith('日志/') or any(str(Path(x['path']).parent).replace('\\', '/') !=
                                             parent.replace('日志/', '截图/', 1)
                                             for x in manifest['files'] if x['path'].startswith('截图/')):
        raise ValueError('invalid batch directories')
    if any(str(Path(x['path']).parent).replace('\\', '/') != parent
           for x in manifest['files'] if x['path'].startswith('日志/')):
        raise ValueError('mixed log batches')
    return parent


def upload_one(batch, target):
    batch, target = Path(batch).absolute(), Path(target)
    raw = bounded_read(batch, 'manifest.json', 1024 * 1024)
    if bounded_read(batch, '_READY', 64).decode('ascii') != digest(raw):
        raise ValueError('local batch not sealed')
    manifest = validate_manifest(batch, json.loads(raw))
    remote = target / '待分析'
    control = safe_path(remote, control_directory(manifest))
    if safe_path(control, '_LOGS_PURGED').exists():
        if bounded_read(control, '_LOGS_PURGED', 64).decode('ascii') != digest(raw):
            raise ValueError('retained batch identity conflict')
        return
    if safe_path(control, '_PURGING_LOGS').exists():
        raise OSError('batch log retention is in progress')
    marker = control / '_UPLOAD_COMPLETE'
    if marker.exists():
        if bounded_read(control, '_UPLOAD_COMPLETE', 64).decode('ascii') != digest(raw):
            raise ValueError('completed batch conflict')
        validate_remote(control)
        return

    def publish(destination, data):
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink() or destination.is_junction():
            raise ValueError('linked destination')
        if destination.exists():
            if destination.stat().st_size != len(data):
                raise ValueError('existing diagnostic size conflict')
            if digest(destination.read_bytes()) != digest(data):
                raise ValueError('existing diagnostic content conflict')
            return
        stale = [destination.with_name(destination.name + '.uploading')]
        stale.extend(destination.parent.glob(destination.name + '.uploading.*'))
        for pending in stale:
            if pending.is_symlink() or pending.is_junction():
                raise ValueError('linked upload temporary file')
            try:
                if pending.stat().st_size == len(data) and digest(pending.read_bytes()) == digest(data):
                    pending.replace(destination)
                    return
            except FileNotFoundError:
                pass
        pending = destination.with_name(
            destination.name + f'.uploading.{os.getpid()}.{uuid.uuid4().hex}')
        if pending.is_symlink() or pending.is_junction():
            raise ValueError('linked upload temporary file')
        with pending.open('wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(destination)

    for item in manifest['files']:
        destination = safe_path(remote, item['path'])
        data = safe_path(batch, item['path']).read_bytes()
        if digest(data) != item['sha256']:
            raise ValueError('local file changed after validation')
        publish(destination, data)
        publish(destination.with_name(destination.name + '.sha256'), item['sha256'].encode('ascii'))
    publish(control / 'manifest.json', raw)
    publish(control / 'manifest.json.sha256', digest(raw).encode('ascii'))
    # Final marker is always last, after both log and screenshot trees are complete.
    publish(marker, digest(raw).encode('ascii'))


def validate_remote(control):
    control = Path(control).absolute()
    # control = root/待分析/日志/program/date/run/batch
    if len(control.parents) < 5 or control.parents[3].name != '日志':
        raise ValueError('invalid diagnostic control path')
    root = control.parents[4]
    manifest_path = safe_path(root, str((control / 'manifest.json').relative_to(root)).replace('\\', '/'))
    if manifest_path.stat().st_size > 1024 * 1024:
        raise ValueError('manifest too large')
    raw = manifest_path.read_bytes()
    expected = digest(raw)
    control = safe_path(root, control.relative_to(root).as_posix())
    if safe_path(control, '_PURGING_LOGS').exists():
        raise ValueError('batch log retention is in progress')
    if safe_path(control, '_LOGS_PURGED').exists():
        if (bounded_read(control, '_LOGS_PURGED', 64).decode('ascii') != expected
                or bounded_read(control, 'manifest.json.sha256', 64).decode('ascii') != expected):
            raise ValueError('purged log manifest mismatch')
        manifest = json.loads(raw)
        if safe_path(root, control_directory(manifest)) != control:
            raise ValueError('manifest belongs to another batch')
        images = [item for item in manifest['files'] if item['path'].startswith('截图/')]
        if images:
            validate_manifest(root, dict(manifest, files=images))
        for item in images:
            if bounded_read(root, item['path'] + '.sha256', 64).decode('ascii') != item['sha256']:
                raise ValueError('retained image checksum mismatch')
        return dict(manifest, files=images, logs_purged=True)
    if (bounded_read(control, '_UPLOAD_COMPLETE', 64).decode('ascii') != expected
            or bounded_read(control, 'manifest.json.sha256', 64).decode('ascii') != expected):
        raise ValueError('manifest completion mismatch')
    manifest = validate_manifest(root, json.loads(raw))
    if safe_path(root, control_directory(manifest)) != control:
        raise ValueError('manifest belongs to another batch')
    for item in manifest['files']:
        path = safe_path(root, item['path'])
        sidecar = safe_path(root, item['path'] + '.sha256')
        if bounded_read(root, item['path'] + '.sha256', 64).decode('ascii') != item['sha256']:
            raise ValueError('file checksum sidecar mismatch')
    return manifest


def retry_pending(root, target, *, timeout=30, now=None, transfer=None):
    root = Path(root)
    now = time.time() if now is None else now
    transfer = transfer or bounded_upload
    try:
        lease = FileLease(root / '.uploader.lock')
    except OSError as error:
        if error.errno in (errno.EACCES, errno.EAGAIN):
            return False
        raise
    with lease:
        recover_sessions(root)
        pending = []
        for ready in root.glob('*/batches/*/_READY'):
            batch = ready.parent
            try:
                safe_path(root, batch.relative_to(root).as_posix())
                manifest = json.loads((batch / 'manifest.json').read_text(encoding='utf-8'))
                if manifest.get('policy') != POLICY:
                    continue
                pending.append((0 if manifest['kind'] == 'error' else 1, manifest['created_at'], batch))
            except (ValueError, OSError, KeyError):
                continue
        deadline = time.monotonic() + 120
        for _, created, batch in sorted(pending):
            if time.monotonic() >= deadline:
                break
            state_file = root / 'states' / (batch.parents[1].name + '--' + batch.name + '.json')
            try:
                state = json.loads(state_file.read_text(encoding='utf-8')) if state_file.exists() else {}
                if state.get('status') in ('uploaded', 'blocked', 'logs_purged') or state.get('next_retry', 0) > now:
                    continue
                attempts = state.get('attempts', 0) + 1
                state.update(status='uploading', attempts=attempts)
                atomic_json(state_file, state)
                try:
                    transfer(batch, target, min(timeout, max(1, deadline - time.monotonic())))
                    state.update(status='uploaded', uploaded_at=time.time(), last_error=None)
                except ValueError as error:
                    state.update(status='blocked', last_error=sanitize_text(error))
                except Exception as error:
                    state.update(status='retrying', next_retry=now + RETRY[min(attempts - 1, len(RETRY) - 1)],
                                 last_error=sanitize_text(error))
                atomic_json(state_file, state)
                atomic_json(batch.parents[1] / 'upload-status.json', dict(state, latest_batch=batch.name))
            except (OSError, ValueError, KeyError) as error:
                atomic_json(root / 'uploader-error.json', {'error': sanitize_text(error), 'time': now})
    return True


def bounded_upload(batch, target, timeout):
    command = [sys.executable, '-E', '-s', '-m', 'src.runtime.diagnostic_uploader', '--upload-one', str(batch), '--target', str(target)]
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    try:
        result = subprocess.run(command, cwd=str(Path(__file__).resolve().parents[2]),
                                capture_output=True, text=True, timeout=timeout, creationflags=flags)
    except subprocess.TimeoutExpired as error:
        raise OSError('SMB worker timed out; only the owned child was stopped') from error
    if result.returncode:
        message = sanitize_text(result.stderr[-2000:])
        if result.returncode == 2:
            raise ValueError(message)
        raise OSError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=default_root())
    parser.add_argument('--target')
    parser.add_argument('--configure', action='store_true')
    parser.add_argument('--save-credentials', action='store_true')
    parser.add_argument('--ensure-task', action='store_true')
    parser.add_argument('--cleanup-one', type=Path)
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--validate', type=Path)
    parser.add_argument('--upload-one', type=Path)
    parser.add_argument('--reviewed-image', type=Path)
    parser.add_argument('--run', type=Path)
    args = parser.parse_args()
    if args.upload_one:
        try:
            connect(args.target)
            upload_one(args.upload_one, args.target)
        except ValueError as error:
            print(sanitize_text(error), file=sys.stderr)
            return 2
        except Exception as error:
            print(sanitize_text(error), file=sys.stderr)
            return 1
        return 0
    if args.validate:
        connect(args.validate)
        print(json.dumps(validate_remote(args.validate), ensure_ascii=False))
        return 0
    if args.cleanup_one:
        from src.runtime.diagnostic_retention import purge_remote_logs
        connect(args.target)
        purge_remote_logs(args.cleanup_one, args.target)
        return 0
    if args.save_credentials:
        import getpass
        save_credentials(args.target or DEFAULT_TARGET, 'ai-upload', getpass.getpass('NAS password: '))
        return 0
    if args.configure:
        value = settings(args.root)
        value['target'] = args.target or DEFAULT_TARGET
        atomic_json(args.root / 'settings.json', value)
        return 0
    if args.reviewed_image:
        if not args.run or args.run.absolute().parent != args.root.absolute():
            parser.error('--run must be an existing session beneath --root')
        safe_path(args.root, args.run.name)
        print(seal_run(args.run, 'reviewed_image', reviewed_images=[args.reviewed_image]))
        return 0
    if args.status:
        for path in sorted(args.root.glob('states/*.json')):
            print(path.name, path.read_text(encoding='utf-8'))
        return 0
    value = settings(args.root)
    if args.ensure_task:
        ensure_task(args.root)
    try:
        from src.runtime.diagnostic_collector import collect_after_exit
        collect_after_exit(args.root, REPO)
        retry_pending(args.root, args.target or value['target'])
        from src.runtime.diagnostic_retention import weekly_cleanup
        weekly_cleanup(args.root, args.target or value['target'])
    except OSError:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
