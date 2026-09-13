"""Expiry of acknowledged evidence; explicit report-backed review handoff."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from src.runtime.diagnostic_export import atomic_json, safe_path, sanitize_text
from src.runtime.diagnostic_archive import hash_file
from src.runtime.diagnostic_session import FileLease, log_sources
from src.runtime.diagnostic_policy import DEFAULT_TARGET, POLICY, REPO, connect

DAY = 86400


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def control_or_empty(path):
    try:
        value = read(path)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def due(stamp, age, now):
    return isinstance(stamp, (int, float)) and 0 < stamp <= now - age


def cleanup_local(root, *, now=None, source_root=REPO):
    root = Path(root).resolve()
    now = time.time() if now is None else now
    removed, errors = 0, []
    with FileLease(root / '.archive.lock'), FileLease(root / '.uploader.lock'):
        for metadata_path in root.glob('*/metadata.json'):
            try:
                run = safe_path(root, metadata_path.parent.name)
                metadata = read(metadata_path)
                if (not (run / '_FINAL_SEALED').is_file() or metadata.get('policy') != POLICY
                        or metadata.get('local_deleted_at')):
                    continue
                with FileLease(run / '.session.lock'):
                    batches = list(run.glob('batches/*/_READY'))
                    states = [(p.parent, safe_path(root, 'states/' + run.name + '--' + p.parent.name + '.json')) for p in batches]
                    if not states or not all(s.exists() and read(s).get('status') in ('uploaded', 'logs_purged')
                            and due(read(s).get('uploaded_at'), DAY, now) for _, s in states):
                        continue
                    # Keep protocol manifests and receipts; never recursively delete a computed directory.
                    for batch, state_path in states:
                        manifest = read(batch / 'manifest.json')
                        if hash_file(batch / 'manifest.json') != (batch / '_READY').read_text(encoding='ascii'):
                            raise ValueError('封存清单校验失败')
                        for item in manifest['files']:
                            safe_path(batch, item['path']).unlink(missing_ok=True)
                        state = read(state_path)
                        state['local_deleted_at'] = now
                        atomic_json(state_path, state)
                    purge_sources(root, run.name, source_root)
                    for source in log_sources(run):
                        safe_path(run, source.name).unlink(missing_ok=True)
                    for folder in ('screenshots', 'incidents', 'collecting'):
                        for source in (run / folder).rglob('*'):
                            if source.is_file():
                                safe_path(run, source.relative_to(run).as_posix()).unlink()
                    metadata['local_deleted_at'] = now
                    atomic_json(metadata_path, metadata)
                    removed += 1
            except (OSError, ValueError, KeyError, TypeError) as error:
                errors.append(sanitize_text(error))
        for receipt_path in (root / 'archives').glob('okww诊断证据_*.json'):
            try:
                receipt = read(receipt_path)
                if receipt.get('local_deleted_at'):
                    continue
                if receipt.get('status') == 'uploaded' and not receipt.get('uploaded_at'):
                    # 1.66.00 receipts predate the explicit archive timestamp.
                    statuses = [control_or_empty(safe_path(root, 'states/' + item['key'] + '.json'))
                                for item in receipt.get('batches', [])]
                    if statuses and all(s.get('status') in ('uploaded', 'logs_purged') and s.get('uploaded_at') for s in statuses):
                        receipt['uploaded_at'] = max(s['uploaded_at'] for s in statuses)
                if receipt.get('status') != 'uploaded' or not due(receipt.get('uploaded_at'), DAY, now):
                    continue
                safe_path(root, 'archives/' + receipt_path.with_suffix('.zip').name).unlink(missing_ok=True)
                receipt['local_deleted_at'] = now
                atomic_json(receipt_path, receipt)
            except (OSError, ValueError, KeyError) as error:
                errors.append(sanitize_text(error))
    atomic_json(root / 'archive-retention.json', {'checked_at': now, 'removed_sessions': removed, 'errors': errors})
    return removed


def purge_sources(root, run_id, source_root):
    from src.runtime.diagnostic_collector import FileCollector, LOG_TYPES, IMAGE_TYPES
    from src.runtime.diagnostic_storage import storage_path
    cursor_path = root / 'source-cursors.json'
    if not cursor_path.exists():
        return
    for relative, cursor in read(cursor_path).items():
        if (cursor.get('run_id') != run_id or cursor.get('pre_policy', True)
                or cursor.get('offset') != cursor.get('size')):
            continue
        folder, _, name = relative.partition('/')
        if folder not in ('logs', 'screenshots') or Path(name).suffix.lower() not in LOG_TYPES | IMAGE_TYPES:
            continue
        base = Path(source_root) / folder
        if folder == 'screenshots':
            base = storage_path('screenshots', base, repo=source_root)
        path = safe_path(base, name)
        if path.is_file():
            stamp = FileCollector.stamp(path)
            if all(stamp[k] == cursor.get(k) for k in ('size', 'mtime', 'inode', 'prefix_hash')):
                path.unlink()


def mark_reviewed(name, report, expected, *, target=DEFAULT_TARGET, now=None):
    """Called by the reviewing AI only after completing the supplied report."""
    now = time.time() if now is None else now
    target = Path(target)
    if Path(name).name != name or not name.startswith('okww诊断证据_') or not name.endswith('.zip'):
        raise ValueError('需要诊断包文件名')
    content = Path(report).read_text(encoding='utf-8').strip()
    if not content:
        raise ValueError('检查报告不能为空')
    with FileLease(safe_path(target, '.archive-retention.lock')):
        source = safe_path(target, '待分析/压缩包/' + name)
        destination = safe_path(target, '已检查/压缩包/' + name)
        record = safe_path(target, '检查报告/' + name + '.json')
        report_path = safe_path(target, '检查报告/' + name + '.md')
        archive = source if source.exists() else destination
        if hash_file(archive) != expected:
            raise ValueError('检查包 SHA256 不匹配')
        if record.exists() and read(record).get('status') == 'reviewed':
            old = read(record)
            if old['archive_sha256'] != expected or hash_file(report_path) != old['report_sha256']:
                raise ValueError('已有检查记录冲突')
            return str(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = safe_path(target, '检查报告/' + name + '.md.partial')
        with temporary.open('w', encoding='utf-8') as stream:
            stream.write(content + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(report_path)
        atomic_json(record, {'status': 'reviewing', 'archive_sha256': expected,
                            'report_sha256': hash_file(report_path), 'reviewed_at': now})
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            if destination.exists() and hash_file(destination) != expected:
                raise ValueError('已检查目录存在同名冲突')
            source.replace(destination)
        source.with_suffix('.json').unlink(missing_ok=True)
        value = read(record)
        value['status'] = 'reviewed'
        atomic_json(record, value)
        return str(report_path)


def cleanup_remote(target=DEFAULT_TARGET, *, now=None):
    target = Path(target)
    now = time.time() if now is None else now
    removed = 0
    with FileLease(safe_path(target, '.archive-retention.lock')):
        for receipt_path in (target / '待分析/压缩包').glob('okww诊断证据_*.json'):
            receipt_path = safe_path(target, receipt_path.relative_to(target).as_posix())
            receipt = control_or_empty(receipt_path)
            if not due(receipt.get('uploaded_at'), 30 * DAY, now):
                continue
            archive = safe_path(target, '待分析/压缩包/' + receipt_path.with_suffix('.zip').name)
            if not archive.exists() or hash_file(archive) != receipt.get('sha256'):
                continue
            archive.unlink()
            receipt.update(status='expired_unreviewed', deleted_at=now)
            atomic_json(receipt_path, receipt)
            removed += 1
        for record in (target / '检查报告').glob('okww诊断证据_*.zip.json'):
            record = safe_path(target, record.relative_to(target).as_posix())
            value = control_or_empty(record)
            if (value.get('status') != 'reviewed' or value.get('evidence_deleted_at')
                    or not due(value.get('reviewed_at'), 3 * DAY, now)):
                continue
            report = safe_path(target, '检查报告/' + record.with_suffix('.md').name)
            archive = safe_path(target, '已检查/压缩包/' + record.stem)
            if not report.exists() or hash_file(report) != value.get('report_sha256'):
                continue
            if archive.exists():
                if hash_file(archive) != value.get('archive_sha256'):
                    continue
                archive.unlink()
                removed += 1
            value['evidence_deleted_at'] = now
            atomic_json(record, value)
        removed += cleanup_legacy(target, now)
    return removed


def cleanup_legacy(target, now):
    """Old scattered batches have no review proof: retain 30 days after delivery."""
    from src.runtime.diagnostic_uploader import control_directory, validate_remote
    from src.runtime.diagnostic_incidents import view_path
    removed = 0
    base = target / '待分析'
    for manifest_path in (base / '日志/okww-custom').glob('*/*/*/manifest.json'):
        try:
            control = safe_path(base, manifest_path.parent.relative_to(base).as_posix())
            marker = control / '_UPLOAD_COMPLETE'
            if not marker.exists():
                marker = control / '_LOGS_PURGED'
            journal = control / '_EXPIRING_EVIDENCE.json'
            if not journal.exists() and (not marker.exists() or not due(marker.stat().st_mtime, 30 * DAY, now)):
                continue
            manifest = read(manifest_path)
            sha = hash_file(manifest_path)
            if manifest.get('policy') != POLICY or safe_path(base, control_directory(manifest)) != control:
                continue
            if journal.exists():
                if read(journal).get('sha256') != sha:
                    continue
            else:
                validate_remote(control)
                atomic_json(journal, {'sha256': sha, 'started_at': now})
            for item in manifest['files']:
                source = safe_path(base, item['path'])
                if source.name == 'incident.json' and source.exists():
                    incident = read(source)
                    view = view_path(target, incident)
                    if control_or_empty(view).get('revision', 0) <= incident.get('revision', 0):
                        view.unlink(missing_ok=True)
                source.unlink(missing_ok=True)
                safe_path(base, item['path'] + '.sha256').unlink(missing_ok=True)
            (control / '_UPLOAD_COMPLETE').unlink(missing_ok=True)
            (control / '_LOGS_PURGED').unlink(missing_ok=True)
            copied_index = safe_path(target, '已处理/' + '/'.join(control.parts[-3:]) + '/evidence-index.json')
            if control_or_empty(copied_index).get('manifest_sha256') == sha:
                copied_index.unlink(missing_ok=True)
            atomic_json(control / '_EVIDENCE_EXPIRED.json', {'sha256': sha, 'deleted_at': now})
            journal.unlink(missing_ok=True)
            removed += 1
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return removed


def maintenance_loop(root):
    """No uploader is launched. Closed/offline machines catch up next startup."""
    while True:
        try:
            cleanup_local(root)
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            result = subprocess.run([sys.executable, '-E', '-s', '-m',
                'src.runtime.diagnostic_archive_retention', '--cleanup-remote'],
                cwd=str(Path(__file__).resolve().parents[2]), capture_output=True, timeout=120, creationflags=flags)
            if result.returncode:
                raise OSError('NAS 清理未完成，下一轮重试')
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            atomic_json(Path(root) / 'archive-retention-error.json', {'time': time.time(), 'error': sanitize_text(error)})
        time.sleep(3600)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cleanup-remote', action='store_true')
    parser.add_argument('--review')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--sha256')
    args = parser.parse_args()
    connect(DEFAULT_TARGET)
    if args.cleanup_remote:
        cleanup_remote()
    elif args.review and args.report and args.sha256:
        print(mark_reviewed(args.review, args.report, args.sha256))
    else:
        parser.error('需要 --cleanup-remote 或 --review 文件名 --report 报告路径 --sha256 哈希')
