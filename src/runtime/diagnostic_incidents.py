"""Rebuild error-window views exclusively from verified uploaded batches."""
import json
from pathlib import Path

from src.runtime.diagnostic_export import atomic_json, safe_path


def validate_index(index):
    if (not isinstance(index, dict) or index.get('schema_version') != 1
            or index.get('state') not in ('collecting', 'complete', 'incomplete')
            or not isinstance(index.get('revision'), int) or index['revision'] < 1
            or not isinstance(index.get('frames'), list) or len(index['frames']) > 64
            or any(not isinstance(frame, dict) or not isinstance(frame.get('frame_id'), str)
                   or not isinstance(frame.get('sha256'), str) for frame in index['frames'])):
        raise ValueError('invalid incident index')


def view_path(target, index):
    # Identity fields are components, never paths supplied by a sender.
    parts = [index[key] for key in ('device_id', 'run_id', 'incident_id')]
    if any(not isinstance(part, str) or not part or '/' in part or '\\' in part for part in parts):
        raise ValueError('invalid incident identity')
    return safe_path(target, '事件索引/' + '/'.join(parts) + '.json')


def without_logs(index):
    fields = ('schema_version', 'device_id', 'installation_id', 'run_id', 'incident_id',
              'revision', 'version', 'state', 'triggered_at', 'trigger_monotonic',
              'pre_seconds', 'post_seconds', 'sample_interval', 'frames',
              'incomplete_reasons', 'missing_frames', 'ended_monotonic',
              'continued_from', 'trigger_count')
    return dict({key: value for key, value in index.items() if key in fields}, log_retention_expired=True)


def expire_view(target, incident):
    path = view_path(target, incident)
    if path.exists():
        current = json.loads(path.read_text(encoding='utf-8'))
        if current.get('revision', 0) >= incident['revision']:
            incident = current
    atomic_json(path, without_logs(incident))


def scan_incidents(target):
    from src.runtime.diagnostic_uploader import bounded_read, validate_remote
    target = Path(target).absolute()
    verified_frames, candidates = {}, {}
    tree = target / '待分析' / '日志' / 'okww-custom'
    for path in tree.glob('*/*/*/manifest.json'):
        control = path.parent
        if not ((control / '_UPLOAD_COMPLETE').exists() or (control / '_LOGS_PURGED').exists()):
            continue
        try:
            manifest = validate_remote(control)
            for item in manifest['files']:
                if item['path'].startswith('截图/'):
                    verified_frames[item['path']] = (manifest['run_id'], item['sha256'])
                if item['path'].endswith('/incident.json'):
                    index = json.loads(bounded_read(target / '待分析', item['path'], 1024 * 1024))
                    validate_index(index)
                    if index.get('run_id') != manifest['run_id']:
                        raise ValueError('incident belongs to another run')
                    destination = view_path(target, index)
                    if index['revision'] >= candidates.get(destination, {}).get('revision', 0):
                        candidates[destination] = index
        except (OSError, ValueError, KeyError, TypeError):
            continue  # diagnostic_reader reports invalid batches separately.
    # Retained views contain only image links; include them for post-retention verification.
    for path in (target / '事件索引').glob('*/*/*.json'):
        try:
            safe_path(target, path.relative_to(target).as_posix())
            old = json.loads(path.read_text(encoding='utf-8'))
            validate_index(old)
            if path != view_path(target, old):
                continue
            if old.get('log_retention_expired'):
                current = candidates.get(path, old)
                candidates[path] = without_logs(current)
            elif path not in candidates:
                candidates[path] = dict(old, source_unverified=True)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    results = []
    for path, index in candidates.items():
        missing = []
        for frame in index['frames']:
            if verified_frames.get(frame.get('remote_path')) != (index['run_id'], frame.get('sha256')):
                missing.append(frame.get('frame_id'))
        index['missing_remote_frames'] = missing
        index['delivery_state'] = ('source_unverified' if index.get('source_unverified') else
                                   'waiting_for_frames' if missing else 'verified')
        index['analysis_state'] = 'needs_analysis'
        try:
            previous = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            previous = None
        if previous != index:
            atomic_json(path, index)
            results.append(str(path))
    return results
