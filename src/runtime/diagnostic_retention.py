"""Weekly retention of delivered logs only; images and pending evidence survive."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from src.runtime.diagnostic_export import atomic_json, digest, safe_path
from src.runtime.diagnostic_policy import POLICY, REPO
from src.runtime.diagnostic_session import FileLease, log_sources
from src.runtime.diagnostic_uploader import bounded_read, control_directory, validate_remote

WEEK = 7 * 86400


def purge_remote_logs(batch, target, *, now=None):
    now = time.time() if now is None else now
    raw = bounded_read(batch, 'manifest.json', 1024 * 1024)
    manifest = json.loads(raw)
    if manifest.get('policy') != POLICY or manifest['created_at'] > now - WEEK:
        raise ValueError('only old automatic-policy logs can be removed')
    if bounded_read(batch, '_READY', 64).decode('ascii') != digest(raw):
        raise ValueError('local batch not sealed')
    remote = Path(target) / '待分析'
    control = safe_path(remote, control_directory(manifest))
    checksum = digest(raw)
    done = safe_path(control, '_LOGS_PURGED')
    journal = safe_path(control, '_PURGING_LOGS')
    if done.exists():
        if bounded_read(control, done.name, 64).decode('ascii') != checksum:
            raise ValueError('retention completion conflict')
        return
    if journal.exists():
        if bounded_read(control, journal.name, 64).decode('ascii') != checksum:
            raise ValueError('retention journal conflict')
    else:
        validate_remote(control)
        if digest(bounded_read(control, 'manifest.json', 1024 * 1024)) != checksum:
            raise ValueError('remote batch differs from delivered batch')
        journal.write_text(checksum, encoding='ascii')
    # Readers stop seeing the batch as complete before any payload is removed.
    for item in manifest['files']:
        if item['path'].endswith('/incident.json'):
            source = safe_path(remote, item['path'])
            if source.exists():
                from src.runtime.diagnostic_incidents import expire_view
                expire_view(target, json.loads(bounded_read(remote, item['path'], 1024 * 1024)))
    safe_path(control, '_UPLOAD_COMPLETE').unlink(missing_ok=True)
    for item in manifest['files']:
        if item['path'].startswith('日志/'):
            safe_path(remote, item['path']).unlink(missing_ok=True)
            safe_path(remote, item['path'] + '.sha256').unlink(missing_ok=True)
    # The owned evidence index may contain copied log excerpts.
    relative = '/'.join(control.parts[-3:])
    report = safe_path(target, '已处理/' + relative + '/evidence-index.json')
    if report.exists():
        value = json.loads(bounded_read(report.parent, report.name, 1024 * 1024))
        if value.get('manifest_sha256') == checksum:
            report.unlink()
    done.write_text(checksum, encoding='ascii')
    journal.unlink(missing_ok=True)


def bounded_purge(batch, target):
    result = subprocess.run([sys.executable, '-E', '-s', '-m', 'src.runtime.diagnostic_uploader',
                             '--cleanup-one', str(batch), '--target', str(target)],
                            cwd=str(Path(__file__).resolve().parents[2]), capture_output=True,
                            timeout=30, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise OSError('NAS retention failed; source logs retained')


def weekly_cleanup(root, target, *, now=None, purge=None, source_root=REPO):
    root = Path(root).absolute()
    now = time.time() if now is None else now
    purge = purge or bounded_purge
    schedule = root / 'retention.json'
    with FileLease(root / '.uploader.lock'):
        state = json.loads(schedule.read_text(encoding='utf-8')) if schedule.exists() else {}
        if now - state.get('last_completed', 0) < WEEK:
            return
        deadline, complete, removed = time.monotonic() + 60, True, 0
        for run in sorted(root.iterdir()):
            if not run.is_dir() or run.is_symlink() or run.is_junction() or not (run / '_FINAL_SEALED').exists():
                continue
            run = safe_path(root, run.name)
            try:
                with FileLease(run / '.session.lock'):
                    metadata = json.loads(bounded_read(run, 'metadata.json', 1024 * 1024))
                    if metadata.get('policy') != POLICY:
                        continue
                    all_purged = True
                    for batch in sorted((run / 'batches').iterdir()):
                        batch = safe_path(run, 'batches/' + batch.name)
                        status_path = root / 'states' / (run.name + '--' + batch.name + '.json')
                        status = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {}
                        if status.get('status') == 'logs_purged':
                            continue
                        all_purged = False
                        if status.get('status') != 'uploaded':
                            continue
                        manifest = json.loads(bounded_read(batch, 'manifest.json', 1024 * 1024))
                        if manifest.get('policy') != POLICY or manifest['created_at'] > now - WEEK:
                            continue
                        if time.monotonic() >= deadline:
                            complete = False
                            break
                        purge(batch, target)
                        for item in manifest['files']:
                            if item['path'].startswith('日志/'):
                                safe_path(batch, item['path']).unlink(missing_ok=True)
                        status.update(status='logs_purged', logs_purged_at=now)
                        atomic_json(status_path, status)
                        removed += 1
                    # Check again after this pass; unacknowledged batches prohibit source deletion.
                    statuses = [root / 'states' / (run.name + '--' + p.name + '.json')
                                for p in (run / 'batches').iterdir()]
                    all_purged = bool(statuses) and all(p.exists() and json.loads(p.read_text(encoding='utf-8')).get('status') == 'logs_purged' for p in statuses)
                    if all_purged:
                        for path in log_sources(run):
                            safe_path(run, path.name).unlink(missing_ok=True)
                        from src.runtime.diagnostic_incidents import without_logs
                        for path in (run / 'incidents').glob('*/event.json'):
                            safe_path(run, path.relative_to(run).as_posix())
                            index = json.loads(path.read_text(encoding='utf-8'))
                            retained = without_logs(index)
                            retained['published_revision'] = index['revision']
                            atomic_json(path, retained)
            except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
                complete = False
        purge_collected_sources(root, source_root, now)
        atomic_json(schedule, {'last_completed': now if complete else state.get('last_completed', 0),
                               'last_attempt': now, 'status': 'complete' if complete else 'retrying',
                               'removed_batches': removed})


def purge_collected_sources(root, source_root, now):
    """Delete only unchanged, fully copied post-policy source logs from this install."""
    from src.runtime.diagnostic_collector import FileCollector, LOG_TYPES
    cursor_path = Path(root) / 'source-cursors.json'
    if not cursor_path.exists():
        return
    cursors = json.loads(cursor_path.read_text(encoding='utf-8'))
    for name, cursor in cursors.items():
        if (cursor.get('pre_policy', True) or not name.startswith('logs/')
                or Path(name).suffix.lower() not in LOG_TYPES
                or cursor.get('collected_at', now) > now - WEEK
                or cursor.get('offset') != cursor.get('size')):
            continue
        run = safe_path(root, cursor.get('run_id', 'invalid'))
        if not (run / '_FINAL_SEALED').is_file():
            continue
        try:
            with FileLease(run / '.session.lock'):
                batches = list((run / 'batches').iterdir())
                if not batches:
                    continue
                states = [Path(root) / 'states' / (run.name + '--' + p.name + '.json') for p in batches]
                if not all(p.exists() and json.loads(p.read_text(encoding='utf-8')).get('status') == 'logs_purged' for p in states):
                    continue
                path = safe_path(source_root, name)
                if path.exists():
                    current = FileCollector.stamp(path)
                    if all(current[k] == cursor.get(k) for k in ('mtime', 'inode', 'size')):
                        path.unlink()
        except OSError:
            continue
