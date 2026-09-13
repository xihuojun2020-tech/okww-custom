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

from src.runtime.diagnostic_export import atomic_json, digest, sanitize_data, sanitize_file, sanitize_text, sanitize_identity, sanitize_incident
from src.runtime.diagnostic_policy import POLICY, installation_id, settings

PART_LIMIT = 4 * 1024 * 1024
LOG_INTERVAL = 30.


def default_root():
    from src.runtime.diagnostic_storage import storage_path
    root = (Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'okww-custom' / 'diagnostics'
            / POLICY / installation_id())
    root = storage_path('diagnostics', root)
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


def seal_run(run, kind, *, sizes=None, reviewed_images=(), offsets=None, incident=None, prepared_images=False,
             source_ranges=()):
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
    add(f'日志/{prefix}/metadata.json', json.dumps(sanitize_identity(metadata), ensure_ascii=False).encode())
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
        name = f'截图/{prefix}/{Path(picture).stem}.png'
        content = sanitize_file(picture, reviewed_image=True, prepared_png=prepared_images)
        add(name, content)
        if incident is not None:
            for frame in incident['frames']:
                if frame['frame_id'] == Path(picture).stem:
                    frame.update(remote_path=name, batch_id=batch_id, sha256=digest(content))
    if incident is not None:
        add(f'日志/{prefix}/incident.json', json.dumps(sanitize_incident(incident), ensure_ascii=False).encode())
    manifest = {'schema_version': 1, 'run_id': run.name, 'batch_id': batch_id,
                'created_at': time.time(), 'kind': kind, 'files': entries,
                'policy': metadata.get('policy'), 'source_ranges': list(source_ranges),
                'log_ranges': {p.name: [int((offsets or {}).get(p.name, 0)), n] for p, n in sources.items()}}
    atomic_json(batch / 'manifest.json', manifest)
    (batch / '_READY').write_text(digest((batch / 'manifest.json').read_bytes()), encoding='ascii')
    from src.runtime.diagnostic_queue import queue_batch
    queue_batch(batch)
    atomic_json(run / 'upload-status.json', {'latest_batch': batch_id, 'status': 'pending'})
    return batch


def publish_incident(run, incident, pictures):
    seal_run(run, 'error', sizes={}, reviewed_images=pictures, incident=incident, prepared_images=True)
    return incident


def seal_pending(run, kind, *, sizes=None):
    """At least once: advance offsets only after an immutable batch is durable."""
    run = Path(run)
    from src.runtime.diagnostic_evidence import recover_events
    recover_events(run, lambda index, pictures: publish_incident(run, index, pictures),
                   interrupted=kind == 'final')
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
    def __init__(self, root, version, *, source_root=None, current_run_started_at=None):
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
        self.triggers = queue.Queue(maxsize=128)
        self.closed_session = False
        self.metadata = {'schema_version': 1, 'version': version, 'policy': POLICY,
                         'device_id': settings(self.root)['device_id'], 'installation_id': installation_id(),
                         'system': platform.platform(),
                         'started_at': datetime.now().astimezone().isoformat(), 'run_id': self.run_id,
                         'process_status': 'running', 'error_events': 0, 'dropped_batches': 0}
        self.parts, self.total, self.last_error_batch = {}, 0, 0
        self.streams = {}
        self.sequence = 0
        self.frame_provider = None
        self.sample_provider = None
        self.on_batch_ready = None
        self.collector = None
        if source_root is not None:
            from src.runtime.diagnostic_collector import FileCollector
            self.collector = FileCollector(source_root, self.root,
                                           current_run_started_at=current_run_started_at)
        self.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
        from src.runtime.diagnostic_evidence import EvidenceWindow
        identity = {key: self.metadata[key] for key in ('device_id', 'installation_id', 'run_id', 'version')}
        self.evidence = EvidenceWindow(self.run / 'incidents', identity,
                                       lambda index, pictures: publish_incident(self.run, index, pictures))
        self.capacity_checked_at = 0
        self.capacity_warning = None
        self.status_saved_at = 0.
        self.collect_after = 0.
        from src.runtime.diagnostic_performance import PerformanceSampler
        self.performance = PerformanceSampler()
        self._save_metadata()
        self.worker = threading.Thread(target=self._work, name='diagnostic-local', daemon=True)
        self.worker.start()

    def _save_metadata(self):
        atomic_json(self.run / 'metadata.json', sanitize_identity(self.metadata))

    def _append(self, stem, suffix, text):
        data = (text + '\n').encode('utf-8')
        index, size = self.parts.get(stem, (0, 0))
        if size + len(data) > PART_LIMIT:
            index, size = index + 1, 0
        name = stem + (f'-{index:04d}' if index else '') + suffix
        stream = self.streams.get(stem)
        if stream is None or Path(stream.name).name != name:
            if stream is not None:
                stream.close()
            # Unbuffered writes remain visible to recovery; reuse the handle
            # instead of opening/closing the same file on every log line.
            stream = self.streams[stem] = (self.run / name).open('ab', buffering=0)
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
                    data = {'message': self.format(record), 'logger': record.name, 'level': record.levelname}
                    self.record_event('error_log', data)
                    self.record_error(data)
                    if time.monotonic() - self.last_error_batch >= 5:
                        self.last_error_batch = time.monotonic()
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

    def record_error(self, data):
        """Only a bounded queue operation in the caller; frames stay off its thread."""
        data = {key: value[:4096] if isinstance(value, str) else value for key, value in data.items()}
        data['event_sequence'] = self.sequence
        try:
            self.triggers.put_nowait((time.monotonic(), sanitize_data(data)))
            self.request_batch('incident')
        except queue.Full:
            self.metadata['dropped_error_triggers'] = self.metadata.get('dropped_error_triggers', 0) + 1

    def _sample_evidence(self):
        now = time.monotonic()
        if now - self.capacity_checked_at >= 300:
            self.capacity_checked_at = now
            free = shutil.disk_usage(self.root).free
            # Stop walking as soon as the quota is reached. Never delete pending evidence.
            pending_bytes = 0
            from src.runtime.diagnostic_queue import pending_batches
            for batch in pending_batches(self.root):
                state_path = self.root / 'states' / (batch.parents[1].name + '--' + batch.name + '.json')
                try:
                    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
                    if state.get('status') in ('uploaded', 'logs_purged'):
                        continue
                    manifest = json.loads((batch / 'manifest.json').read_text(encoding='utf-8'))
                    pending_bytes += sum(item['size'] for item in manifest['files'])
                except (OSError, ValueError, KeyError):
                    continue
                if pending_bytes >= 2 * 1024 ** 3:
                    break
            self.capacity_warning = ('low_disk_space' if free < 2 * 1024 ** 3 else
                                     'pending_size_limit' if pending_bytes >= 2 * 1024 ** 3 else None)
        if self.capacity_warning:
            self.evidence.unavailable(self.capacity_warning)
        elif self.sample_provider:
            sample = self.sample_provider()
            if sample is None:
                self.evidence.unavailable('frame_unavailable')
            else:
                self.evidence.sample(*sample)
        elif self.frame_provider:
            self.evidence.sample(self.frame_provider())
        else:
            self.evidence.unavailable('frame_unavailable')
        self.evidence.tick()
        if now - self.status_saved_at >= 30:
            atomic_json(self.run / 'evidence-status.json', self.evidence.status())
            self.status_saved_at = now

    def add_screenshot(self, path):
        self.record_event('screenshot_saved', {'status': 'automatic_upload', 'suffix': Path(path).suffix})
        # Capture the exact file named by the framework hook. A directory scan can lag or
        # be capped by unrelated changed logs, leaving only screenshot_saved on the server.
        self.request_batch(('screenshot', str(path)))

    def capture_last_frame(self):
        if self.frame_provider:
            frame = self.frame_provider()
            if frame is not None and frame.nbytes <= 256 * 1024 * 1024:
                self.request_batch(('frame', frame.copy()))

    def _work(self):
        next_log = time.monotonic() + LOG_INTERVAL
        next_sample = time.monotonic()
        while True:
            queued = True
            try:
                end = self.evidence.deadline if self.evidence.active else float('inf')
                kind = self.pending.get(timeout=max(0, min(next_log, next_sample, end) - time.monotonic()))
            except queue.Empty:
                kind, queued = 'tick', False
            try:
                if kind is None:
                    return
                for _ in range(32):
                    try:
                        at, data = self.triggers.get_nowait()
                    except queue.Empty:
                        break
                    self.evidence.trigger(data, at)
                now = time.monotonic()
                due_end = self.evidence.active and now >= self.evidence.deadline
                if now >= next_sample or self.evidence.want_at or due_end:
                    next_sample = (now + 1 if self.evidence.want_at or due_end else
                                   max(next_sample + 1, now + .5))
                    sample_started = time.monotonic()
                    try:
                        self._sample_evidence()
                    except Exception as error:
                        self.evidence.unavailable('capture_failed:' + type(error).__name__)
                        self.evidence.tick()
                    self.performance.observe('diagnostic_sample', time.monotonic() - sample_started)
                with self.guard:
                    performance = self.performance.sample()
                if performance is not None:
                    performance.update(queue_length=self.pending.qsize(), ring_bytes=self.evidence.ring_bytes)
                    self.record_event('performance', performance, allow_closed=True)
                if kind == 'final':
                    self.evidence.finish()
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
                            if self.collector:
                                self.collector.acknowledge(source)
                    self.record_event('screenshot_copy', {'image_id': image_id,
                                      'local_file': saved.name if saved else None,
                                      'status': 'automatic_upload' if saved else 'unavailable'}, allow_closed=True)
                    kind = 'screenshot'
                if time.monotonic() >= next_log or kind not in ('tick', 'incident'):
                    next_log = time.monotonic() + LOG_INTERVAL
                    with self.guard:
                        self._save_metadata()
                        sizes = log_sources(self.run)
                    if self.collector and (kind == 'final' or time.monotonic() >= self.collect_after):
                        self.collect_after = time.monotonic() + LOG_INTERVAL
                        self.collector.collect(self.run)
                    seal_pending(self.run, kind if kind != 'tick' else 'periodic', sizes=sizes)
                # Also wake for incident-only batches; the process launcher applies its throttle.
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
            with self.guard:
                for stream in self.streams.values():
                    stream.close()
                self.streams.clear()
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
