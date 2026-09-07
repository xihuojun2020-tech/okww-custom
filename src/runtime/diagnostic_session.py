"""Local-only diagnostic sessions and immutable, redacted upload batches."""
from __future__ import annotations

import json
import logging
import os
import platform
import queue
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from src.runtime.diagnostic_export import atomic_json, digest, sanitize_data, sanitize_file, sanitize_text
from src.runtime.diagnostic_policy import POLICY, installation_id, settings

PART_LIMIT = 4 * 1024 * 1024


def default_root():
    root = (Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'okww-custom' / 'diagnostics'
            / POLICY / installation_id())
    root.mkdir(parents=True, exist_ok=True)
    # MSIX hosts can redirect files while returning an unredirected directory.
    # Resolve an owned file so child processes and scheduled tasks share one root.
    anchor = root / '.storage-root'
    anchor.touch(exist_ok=True)
    return anchor.resolve().parent


class FileLease:
    """OS lock: released automatically after process death, unlike sentinel files."""
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.stream = open(path, 'a+b')
        if self.stream.tell() == 0:
            self.stream.write(b'0')
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise

    def close(self):
        self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def log_sources(run):
    return {p: p.stat().st_size for p in Path(run).iterdir() if p.suffix in ('.log', '.txt', '.jsonl')
            or p.name == 'crash.json' or (p.name.startswith('collected-') and p.suffix == '.json')}


def seal_run(run, kind, *, sizes=None, reviewed_images=(), offsets=None):
    """Publish a local batch only after every exported file is valid."""
    run = Path(run).absolute()
    root = run.parent
    metadata = json.loads((run / 'metadata.json').read_text(encoding='utf-8'))
    batch_id = datetime.now().strftime('%H%M%S') + '-' + uuid.uuid4().hex[:12]
    batch = run / 'batches' / batch_id
    batch.mkdir(parents=True)
    date = metadata['started_at'][:10]
    prefix = f'okww-custom/{date}/{run.name}/{batch_id}'
    entries = []

    def add(name, content):
        target = batch / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        entries.append({'path': name, 'size': len(content), 'sha256': digest(content)})

    metadata['batch_kind'] = kind
    add(f'日志/{prefix}/metadata.json', json.dumps(sanitize_data(metadata), ensure_ascii=False).encode())
    sources = sizes if sizes is not None else log_sources(run)
    # Files are append-only. Snapshot sizes are captured under the writer lock.
    for index, (source, size) in enumerate(sorted(sources.items())):
        if source.is_symlink() or source.parent != run:
            raise ValueError('invalid session source')
        with source.open('rb') as stream:
            start = (offsets or {}).get(source.name, 0)
            stream.seek(start)
            content = stream.read(size - start)
        snapshot = batch / ('snapshot' + source.suffix)
        snapshot.write_bytes(content)
        content = sanitize_file(snapshot)
        snapshot.unlink()
        add(f'日志/{prefix}/{index:04d}{source.suffix}', content)
    for index, picture in enumerate(reviewed_images):
        add(f'截图/{prefix}/{Path(picture).stem}.png', sanitize_file(picture, reviewed_image=True))
    manifest = {'schema_version': 1, 'run_id': run.name, 'batch_id': batch_id,
                'created_at': time.time(), 'kind': kind, 'files': entries,
                'policy': metadata.get('policy'),
                'log_ranges': {p.name: [int((offsets or {}).get(p.name, 0)), n] for p, n in sources.items()}}
    atomic_json(batch / 'manifest.json', manifest)
    (batch / '_READY').write_text(digest((batch / 'manifest.json').read_bytes()), encoding='ascii')
    atomic_json(run / 'upload-status.json', {'latest_batch': batch_id, 'status': 'pending'})
    return batch


def seal_pending(run, kind, *, sizes=None):
    """At least once: advance offsets only after an immutable batch is durable."""
    run = Path(run)
    state_path = run / 'sealed-offsets.json'
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
    sources = sizes if sizes is not None else log_sources(run)
    for source, size in sorted(sources.items()):
        start = state.get(source.name, 0)
        if size <= start:
            continue
        seal_run(run, kind, sizes={source: size}, offsets={source.name: start})
        state[source.name] = size
        atomic_json(state_path, state)
    for picture in sorted((run / 'screenshots').glob('*')):
        if picture.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
            continue
        key = 'screenshots/' + picture.name
        if key not in state:
            seal_run(run, 'screenshot', sizes={}, reviewed_images=[picture])
            state[key] = picture.stat().st_size
            atomic_json(state_path, state)
    # Small metadata batch records final/error status even without new log bytes.
    if kind in ('final', 'error'):
        seal_run(run, kind, sizes={})
    if kind == 'final':
        (run / '_FINAL_SEALED').touch()


class DiagnosticSession(logging.Handler):
    def __init__(self, root, version, *, source_root=None):
        super().__init__()
        self.root = Path(root).absolute()
        self.root.mkdir(parents=True, exist_ok=True)
        self.collector_lease = FileLease(self.root / '.collector.lock') if source_root is not None else None
        self.run_id = datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:12]
        self.run = self.root / self.run_id
        self.run.mkdir()
        self.lease = FileLease(self.run / '.session.lock')
        self.guard = threading.RLock()
        self.pending = queue.Queue(maxsize=32)
        self.closed_session = False
        self.metadata = {'schema_version': 1, 'version': version, 'policy': POLICY,
                         'device_id': settings(self.root)['device_id'], 'installation_id': installation_id(),
                         'system': platform.platform(),
                         'started_at': datetime.now().astimezone().isoformat(), 'run_id': self.run_id,
                         'process_status': 'running', 'error_events': 0, 'dropped_batches': 0}
        self.parts, self.total, self.last_error_batch = {}, 0, 0
        self.sequence = 0
        self.frame_provider = None
        self.on_batch_ready = None
        self.collector = None
        if source_root is not None:
            from src.runtime.diagnostic_collector import FileCollector
            self.collector = FileCollector(source_root, self.root)
        self.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
        self._save_metadata()
        self.worker = threading.Thread(target=self._work, name='diagnostic-local', daemon=True)
        self.worker.start()

    def _save_metadata(self):
        atomic_json(self.run / 'metadata.json', sanitize_data(self.metadata))

    def _append(self, stem, suffix, text):
        data = (text + '\n').encode('utf-8')
        index, size = self.parts.get(stem, (0, 0))
        if size + len(data) > PART_LIMIT:
            index, size = index + 1, 0
        name = stem + (f'-{index:04d}' if index else '') + suffix
        with (self.run / name).open('ab') as stream:
            stream.write(data)
        self.parts[stem] = (index, size + len(data))
        self.total += len(data)

    def emit(self, record):
        try:
            if record.name.startswith('diagnostic'):
                return
            with self.guard:
                if self.closed_session:
                    return
                self._append('run', '.log', sanitize_text(self.format(record)))
                if record.levelno >= logging.ERROR:
                    self.record_event('error_log', {'message': self.format(record), 'logger': record.name})
                    if time.monotonic() - self.last_error_batch >= 5:
                        self.last_error_batch = time.monotonic()
                        self.capture_last_frame()
                        self.request_batch('error')
        except Exception:
            # Never recurse through logging or affect the task being observed.
            pass

    def record_event(self, kind, data, *, allow_closed=False):
        with self.guard:
            if self.closed_session and not allow_closed:
                return
            self.sequence += 1
            event = {'event_id': self.sequence, 'time': datetime.now().astimezone().isoformat(), 'monotonic': time.monotonic(),
                     'event': kind, 'data': sanitize_data(data)}
            self._append('events', '.jsonl', json.dumps(event, ensure_ascii=False))
            if kind in ('error_log', 'uncaught_exception'):
                self.metadata['error_events'] += 1

    def request_batch(self, kind):
        try:
            self.pending.put_nowait(kind)
        except queue.Full:
            self.metadata['dropped_batches'] += 1

    def add_screenshot(self, path):
        self.record_event('screenshot_saved', {'status': 'automatic_upload', 'suffix': Path(path).suffix})
        if self.collector and any(Path(path).absolute().is_relative_to(self.collector.source / folder)
                                  for folder in ('logs', 'screenshots')):
            self.request_batch('periodic')
            return
        self.request_batch(('screenshot', str(path)))

    def capture_last_frame(self):
        if self.frame_provider:
            frame = self.frame_provider()
            if frame is not None and frame.nbytes <= 256 * 1024 * 1024:
                self.request_batch(('frame', frame.copy()))

    def _work(self):
        while True:
            queued = True
            try:
                kind = self.pending.get(timeout=30)
            except queue.Empty:
                kind, queued = 'periodic', False
            try:
                if kind is None:
                    return
                if isinstance(kind, tuple):
                    action, source = kind
                    folder = self.run / 'screenshots'
                    folder.mkdir(exist_ok=True)
                    image_id = uuid.uuid4().hex
                    saved = None
                    if action == 'frame':
                        import cv2
                        saved = folder / (image_id + '.png')
                        if not cv2.imwrite(str(saved), source):
                            raise OSError('frame encoding failed')
                    else:
                        source = Path(source)
                        if (source.suffix.lower() in ('.png', '.jpg', '.jpeg') and not source.is_symlink()
                                and not source.is_junction()):
                            saved = folder / (image_id + source.suffix.lower())
                            shutil.copyfile(source, saved)
                    self.record_event('screenshot_copy', {'image_id': image_id,
                                      'local_file': saved.name if saved else None,
                                      'status': 'automatic_upload' if saved else 'unavailable'}, allow_closed=True)
                    kind = 'screenshot'
                with self.guard:
                    self._save_metadata()
                    sizes = log_sources(self.run)
                if self.collector:
                    self.collector.collect(self.run)
                seal_pending(self.run, kind, sizes=sizes)
                if self.on_batch_ready:
                    self.on_batch_ready()
            except Exception as error:
                try:
                    atomic_json(self.run / 'upload-status.json', {'status': 'blocked', 'error': sanitize_text(error)})
                except OSError:
                    pass
            finally:
                if queued:
                    self.pending.task_done()

    def finish(self, status='exited', exit_code=0, timeout=2):
        with self.guard:
            if self.closed_session:
                return
            self.closed_session = True
            self.metadata.update(process_status=status, exit_code=exit_code,
                                 ended_at=datetime.now().astimezone().isoformat())
            self._save_metadata()
            self.request_batch('final')
        deadline = time.monotonic() + timeout
        while self.pending.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.02)
        # The uploader can recover a final batch if the daemon is cut short at process exit.
        if not self.pending.unfinished_tasks:
            self.pending.put(None)
            self.worker.join(timeout=0.2)
            self.lease.close()
            if self.collector_lease:
                self.collector_lease.close()


def recover_sessions(root):
    for run in Path(root).glob('*'):
        if not run.is_dir() or run.is_symlink() or run.is_junction() or not (run / 'metadata.json').is_file():
            continue
        if (run / '_FINAL_SEALED').exists():
            continue
        try:
            with FileLease(run / '.session.lock'):
                metadata = json.loads((run / 'metadata.json').read_text(encoding='utf-8'))
                if metadata.get('policy') != POLICY:
                    continue
                finalized = False
                for ready in run.glob('batches/*/_READY'):
                    try:
                        raw = (ready.parent / 'manifest.json').read_bytes()
                        if (ready.read_text(encoding='ascii') == digest(raw)
                                and json.loads(raw).get('kind') == 'final'):
                            finalized = True
                            break
                    except (OSError, ValueError):
                        continue
                if finalized:
                    (run / '_FINAL_SEALED').touch()
                    continue
                metadata = json.loads((run / 'metadata.json').read_text(encoding='utf-8'))
                if metadata['process_status'] == 'running':
                    metadata['process_status'] = 'interrupted'
                    atomic_json(run / 'metadata.json', metadata)
                seal_pending(run, 'final')
        except (OSError, ValueError, KeyError):
            continue
