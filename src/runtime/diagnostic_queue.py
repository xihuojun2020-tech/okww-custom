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
    (directory / (batch.parents[1].name + '--' + batch.name)).touch(exist_ok=True)


def pending_batches(root, *, now=None):
    root = Path(root)
    now = time.time() if now is None else now
    marker = root / 'pending-index.json'
    try:
        last = json.loads(marker.read_text(encoding='utf-8')).get('reconciled_at', 0)
    except (OSError, ValueError, TypeError):
        last = None
    if last is None or now < last or now - last >= 900:
        for ready in root.glob('*/batches/*/_READY'):
            batch = ready.parent
            state_file = root / 'states' / (batch.parents[1].name + '--' + batch.name + '.json')
            try:
                state = json.loads(state_file.read_text(encoding='utf-8')) if state_file.exists() else {}
                if state.get('status') not in ('uploaded', 'logs_purged'):
                    queue_batch(batch)
            except (OSError, ValueError):
                continue
        atomic_json(marker, {'reconciled_at': now})
    for pointer in (root / 'pending').glob('*'):
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
