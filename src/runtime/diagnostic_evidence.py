"""Single-worker, bounded game-frame history and durable error windows.

Capture never happens here: the executor supplies timestamped frames from its
own thread. Network traffic remains in diagnostic_uploader's child processes.
"""
from __future__ import annotations

import json
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from src.runtime.diagnostic_export import atomic_json, digest, safe_path, sanitize_data

PRE_SECONDS = 10
POST_SECONDS = 5
SAMPLE_INTERVAL = 1.
MAX_WINDOW = 30
RING_BYTES = 128 * 1024 * 1024
EVENT_BYTES = 128 * 1024 * 1024
IMAGE_BYTES = 16 * 1024 * 1024


def utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def flush_event(directory, publish):
    """Retry from disk; only successful sealing advances the published revision."""
    directory = Path(directory)
    index = json.loads((directory / 'event.json').read_text(encoding='utf-8'))
    if index.get('published_revision', 0) >= index['revision']:
        return index
    pictures = [safe_path(directory, 'frames/' + frame['frame_id'] + '.png')
                for frame in index['frames'] if not frame.get('remote_path')]
    payload = {key: value for key, value in index.items() if key != 'published_revision'}
    result = publish(payload, pictures)
    index.update(result)
    index['published_revision'] = index['revision']
    atomic_json(directory / 'event.json', index)
    return index


def recover_events(run, publish, *, interrupted=False):
    """Called under the session/worker lease, including after process death."""
    for path in (Path(run) / 'incidents').glob('*/event.json'):
        try:
            safe_path(run, path.relative_to(run).as_posix())
            index = json.loads(path.read_text(encoding='utf-8'))
            if interrupted and index['state'] == 'collecting':
                index['state'] = 'incomplete'
                if 'interrupted' not in index['incomplete_reasons']:
                    index['incomplete_reasons'].append('interrupted')
                index['revision'] += 1
                atomic_json(path, index)
            flush_event(path.parent, publish)
        except (OSError, ValueError, KeyError, TypeError) as error:
            atomic_json(Path(run) / 'evidence-recovery-error.json',
                        {'error': type(error).__name__, 'incident': path.parent.name, 'time': time.time()})


class EvidenceWindow:
    def __init__(self, root, identity, publish, *, clock=time.monotonic):
        self.root = Path(root)
        self.identity = identity
        self.publish = publish
        self.clock = clock
        self.started = clock()
        self.ring = deque()
        self.ring_bytes = 0
        self.ring_limit = RING_BYTES
        self.event_limit = EVENT_BYTES
        self.active = None
        self.directory = None
        self.next_post = None
        self.deadline = None
        self.want_at = False
        self.last_closed = None
        self.last_error = None
        self.dropped_frames = 0
        self.last_source = None
        self.last_save = float('-inf')
        self.last_publish = float('-inf')

    def _trim(self, now):
        while self.ring and (self.ring[0][0]['sample_monotonic'] < now - PRE_SECONDS
                             or len(self.ring) > 12 or self.ring_bytes > self.ring_limit):
            _, data = self.ring.popleft()
            self.ring_bytes -= len(data)

    def trigger(self, data, at=None):
        at = self.clock() if at is None else at
        if self.active and at > self.deadline:
            self._end('window_limit' if self.deadline >= self.active['trigger_monotonic'] + MAX_WINDOW
                      else 'sampling_delayed')
        trigger = dict(sanitize_data(data), monotonic=at)
        if self.active:
            # Keep bounded detail but never lose the true trigger count.
            self.active['trigger_count'] += 1
            if len(self.active['triggers']) < 64:
                self.active['triggers'].append(trigger)
            else:
                self._reason('trigger_details_limit')
            self.deadline = min(at + POST_SECONDS, self.active['trigger_monotonic'] + MAX_WINDOW)
            self.active['last_trigger_monotonic'] = at
            self._save()
            return
        self._trim(at)
        incident_id = uuid.uuid4().hex
        self.directory = self.root / incident_id
        self.active = dict(self.identity, schema_version=1, incident_id=incident_id, revision=0,
                           state='collecting', triggered_at=utc(time.time() - (self.clock() - at)),
                           trigger_monotonic=at, last_trigger_monotonic=at, trigger_count=1,
                           pre_seconds=PRE_SECONDS, post_seconds=POST_SECONDS, sample_interval=1,
                           triggers=[trigger], frames=[], incomplete_reasons=[], missing_frames=[],
                           image_bytes=0, log_refs={'run_id': self.identity['run_id']})
        if self.last_closed and at - self.last_closed[1] <= POST_SECONDS:
            self.active['continued_from'] = self.last_closed[0]
        for frame, data in self.ring:
            if at - PRE_SECONDS <= frame['sample_monotonic'] < at:
                self._add(frame, data, 'pre')
        if len(self.active['frames']) < PRE_SECONDS:
            self._reason('warmup' if at - self.started < PRE_SECONDS else 'pre_frames_missing')
        self.want_at = True
        self.next_post = at + SAMPLE_INTERVAL
        self.deadline = at + POST_SECONDS
        self._save(force=True)

    def _reason(self, reason):
        if self.active and reason not in self.active['incomplete_reasons']:
            self.active['incomplete_reasons'].append(reason)

    def unavailable(self, reason, now=None):
        now = self.clock() if now is None else now
        self._trim(now)
        self.last_error = reason
        if self.active and (self.want_at or now >= self.next_post):
            self._reason(reason)
            if len(self.active['missing_frames']) < 64:
                self.active['missing_frames'].append({'monotonic': now, 'reason': reason})
            self.want_at = False
            self.next_post = max(self.next_post, now + SAMPLE_INTERVAL)
            self._save()

    def sample(self, frame, captured_at=None, captured_monotonic=None):
        now = self.clock()
        self._trim(now)
        if captured_monotonic is not None and (now - captured_monotonic > 1.5
                                               or (captured_monotonic == self.last_source and not self.want_at)
                                               or captured_monotonic > now + .1):
            self.unavailable('stale_frame', now)
            return
        if frame is None:
            self.unavailable('frame_unavailable', now)
            return
        import cv2
        if frame.ndim != 3 or frame.shape[2] not in (3, 4) or frame.nbytes > 128 * 1024 * 1024:
            self.unavailable('invalid_frame', now)
            return
        height, width = frame.shape[:2]
        if height <= 0 or width <= 0:
            self.unavailable('invalid_frame', now)
            return
        # Diagnostic context only: material receipts and verified completion
        # originals use their separate full-resolution save paths.
        scale = min(1., 1920 / width, 1080 / height)
        if scale < 1:
            frame = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale))))
        # Isolate from overlay mutation before the encoder releases the GIL.
        frame = frame[:, :, :3].copy()
        # OpenCV's default strategy outperformed explicit level=1 in the local
        # benchmark; keep it instead of trading more CPU for smaller files.
        ok, encoded = cv2.imencode('.png', frame)
        if not ok or encoded.nbytes > IMAGE_BYTES:
            self.unavailable('image_size_limit', now)
            return
        data = encoded.tobytes()
        record = dict(frame_id=uuid.uuid4().hex, sample_monotonic=now,
                      observed_at=utc(time.time()), captured_at=utc(captured_at) if captured_at else None,
                      captured_monotonic=captured_monotonic,
                      freshness='fresh' if captured_monotonic is not None else 'unknown',
                      original_size=[width, height], size=[frame.shape[1], frame.shape[0]],
                      sha256=digest(data))
        self.last_source = captured_monotonic
        self.last_error = None
        if self.active:
            phase = 'at' if self.want_at else 'post'
            if self.want_at or ((now >= self.next_post or now >= self.deadline) and now <= self.deadline + .25):
                if self.want_at and now - self.active['trigger_monotonic'] > .5:
                    self._reason('sampling_delayed')
                if not self.want_at and now - self.next_post > .5:
                    self._reason('sampling_delayed')
                self._add(record, data, phase)
                self.want_at = False
                self.next_post = max(self.next_post + (0 if phase == 'at' else SAMPLE_INTERVAL),
                                     now + .5)
                self._save(checkpoint=True)
        self.ring.append((record, data))
        self.ring_bytes += len(data)
        self._trim(now)

    def _add(self, frame, data, phase):
        if self.active['image_bytes'] + len(data) > self.event_limit:
            self._reason('event_size_limit')
            self.dropped_frames += 1
            return
        directory = self.directory / 'frames'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (frame['frame_id'] + '.png')
        pending = path.with_suffix('.tmp')
        pending.write_bytes(data)
        pending.replace(path)
        relative = (frame['captured_monotonic'] if frame['captured_monotonic'] is not None
                    else frame['sample_monotonic']) - self.active['trigger_monotonic']
        self.active['frames'].append(dict(frame, phase=phase, relative_seconds=round(relative, 4)))
        self.active['image_bytes'] += len(data)
        if frame['freshness'] == 'unknown':
            self._reason('freshness_unknown')

    def _save(self, force=False, checkpoint=False):
        # Merge error storms and per-frame revisions; first/final are durable
        # immediately, intervening frames remain on disk for recovery.
        if not force and not checkpoint and self.clock() - self.last_save < 2:
            return
        self.last_save = self.clock()
        self.active['revision'] += 1
        atomic_json(self.directory / 'event.json', self.active)
        if not force and self.clock() - self.last_publish < 5:
            return
        try:
            self.active = flush_event(self.directory, self.publish)
            self.last_publish = self.clock()
        except Exception as error:
            # The durable event will be retried by seal_pending/recovery.
            self.last_error = 'event_seal_failed:' + type(error).__name__

    def tick(self):
        if self.active and self.clock() >= self.deadline:
            reason = 'window_limit' if self.deadline < self.active['last_trigger_monotonic'] + POST_SECONDS else None
            if not any(f['phase'] == 'post' and f['sample_monotonic'] >= self.deadline - .5
                       for f in self.active['frames']):
                self._reason('post_frames_missing')
            expected = int(self.deadline - self.active['trigger_monotonic'])
            if sum(frame['phase'] == 'post' for frame in self.active['frames']) < expected:
                self._reason('post_frames_missing')
            self._end(reason)

    def _end(self, reason=None):
        if reason:
            self._reason(reason)
        self.active['state'] = 'incomplete' if self.active['incomplete_reasons'] else 'complete'
        self.active['ended_monotonic'] = min(self.clock(), self.deadline)
        self.last_closed = (self.active['incident_id'], self.active['ended_monotonic'])
        self._save(force=True)
        self.active = None
        self.want_at = False

    def finish(self):
        if self.active:
            self._end('interrupted')
        self.ring.clear()
        self.ring_bytes = 0

    def status(self):
        return {'active_incident': self.active['incident_id'] if self.active else None,
                'ring_frames': len(self.ring), 'ring_bytes': self.ring_bytes,
                'dropped_frames': self.dropped_frames, 'warning': self.last_error,
                'updated_at': time.time()}
