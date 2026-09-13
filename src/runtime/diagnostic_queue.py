"""Small pending-batch index; occasional reconciliation recovers interrupted writes."""
import json
import time
from pathlib import Path

from src.runtime.diagnostic_export import atomic_json, safe_path


def queue_batch(batch):
    batch = Path(batch)
    root = batch.parents[2]
    directory = root / 'pending'
    directory.mkdir(exist_ok=True)
    pointer = directory / (batch.parents[1].name + '--' + batch.name)
    pointer.touch(exist_ok=True)


def pending_batches(root, *, now=None, limit=None):
    root = Path(root)
    now = time.time() if now is None else now
    marker = root / 'pending-index.json'
    try:
        progress = json.loads(marker.read_text(encoding='utf-8'))
        last = progress.get('reconciled_at', 0)
    except (OSError, ValueError, TypeError):
        last = None
        progress = {}
    if last is None or now < last or now - last >= 900:
        after = progress.get('after', '')
        ready_files = sorted(root.glob('*/batches/*/_READY'))
        outstanding = [p for p in ready_files if p.relative_to(root).as_posix() > after]
        for ready in outstanding[:256]:
            batch = ready.parent
            state_file = root / 'states' / (batch.parents[1].name + '--' + batch.name + '.json')
            try:
                state = json.loads(state_file.read_text(encoding='utf-8')) if state_file.exists() else {}
                if state.get('status') not in ('uploaded', 'logs_purged'):
                    queue_batch(batch)
            except (OSError, ValueError):
                continue
        if len(outstanding) > 256:
            atomic_json(marker, {'reconciled_at': last or 0,
                                 'after': outstanding[255].relative_to(root).as_posix()})
        else:
            atomic_json(marker, {'reconciled_at': now})
    pointers = sorted(p for p in (root / 'pending').glob('*') if '--' in p.name and not p.name.endswith('.tmp'))
    cursor_path = root / 'pending-cursor.json'
    try:
        cursor = json.loads(cursor_path.read_text(encoding='utf-8')).get('after', '')
    except (OSError, ValueError):
        cursor = ''
    if limit is not None:
        pointers = ([p for p in pointers if p.name > cursor] + [p for p in pointers if p.name <= cursor])[:limit]
        if pointers:
            atomic_json(cursor_path, {'after': pointers[-1].name})
    for pointer in pointers:
        if '--' not in pointer.name:
            continue
        run, batch = pointer.name.split('--', 1)
        try:
            candidate = safe_path(root, run + '/batches/' + batch)
            if (candidate / '_READY').is_file():
                yield candidate
        except (OSError, ValueError):
            continue


def acknowledge(batch):
    batch = Path(batch)
    (batch.parents[2] / 'pending' / (batch.parents[1].name + '--' + batch.name)).unlink(missing_ok=True)
