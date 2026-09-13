"""Local SQLite index and immutable PNG originals. No retention cleanup exists."""
import hashlib
import json
import os
import sqlite3
from datetime import datetime
from contextlib import contextmanager, closing
from pathlib import Path
from uuid import UUID, uuid4

import cv2
import numpy as np

from src.evidence.model import GAME_ZONE, PROJECTS, SOURCES, STATUSES, now_iso, period_for


class EvidenceRepository:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.database = self.root / 'index.sqlite3'

    @contextmanager
    def _connect(self):
        self.root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.database, timeout=10)
        try:
            db.execute('PRAGMA busy_timeout=10000')
            db.execute('''CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, project_id TEXT NOT NULL,
                captured_at TEXT NOT NULL, period_id TEXT, trashed INTEGER NOT NULL DEFAULT 0,
                metadata TEXT NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS evidence_lookup ON evidence(profile_id, project_id, captured_at DESC)')
            db.execute('CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS account_runs (id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, started_at TEXT NOT NULL, metadata TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS account_runs_lookup ON account_runs(profile_id, started_at DESC)')
            self._migrate_daily_periods(db)
            with db:
                yield db
        finally:
            db.close()

    def _migrate_daily_periods(self, db):
        """One transactional index migration; immutable images/sidecars stay intact."""
        marker = 'daily_periods_v2'
        if db.execute('SELECT 1 FROM preferences WHERE key=?', (marker,)).fetchone():
            return
        db.commit()
        with db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM preferences WHERE key=?', (marker,)).fetchone():
                return
            rows = db.execute("SELECT id, project_id, captured_at, metadata FROM evidence "
                              "WHERE project_id IN ('nightmare_nest','battle_pass') AND period_id IS NULL").fetchall()
            if rows:
                folder = self.root / 'backups' / ('daily-periods-' + str(uuid4()))
                folder.mkdir(parents=True)
                # A separate reader can snapshot while this writer holds the reservation.
                with closing(sqlite3.connect(self.database)) as source, closing(sqlite3.connect(folder / 'index.sqlite3')) as target:
                    source.backup(target)
            invalid = []
            for identity, project, captured, payload in rows:
                try:
                    record = json.loads(payload)
                    period = period_for(project, captured)
                    record.update(period_id=period, period_rule='day')
                except (TypeError, ValueError, AttributeError):
                    invalid.append(identity)
                    continue
                db.execute('UPDATE evidence SET period_id=?, metadata=? WHERE id=?',
                           (period, json.dumps(record, ensure_ascii=False), identity))
            db.execute('INSERT INTO preferences VALUES (?, ?)', (marker, json.dumps({'invalid': invalid})))

    def asset_path(self, relative):
        path = (self.root / relative).resolve()
        if path == self.root or self.root not in path.parents:
            raise ValueError('证据路径越界')
        return path

    def save_run(self, record):
        record = json.loads(json.dumps(record, ensure_ascii=False))
        identity = str(UUID(record['profile_id']))
        record['profile_id'] = identity
        record['run_id'] = str(UUID(record['run_id']))
        if record.get('result') not in ('running', 'returned', 'failed', 'stopped'):
            raise ValueError('运行结果无效')
        for key in ('started_at', 'finished_at'):
            if key == 'finished_at' and record.get(key) is None:
                continue
            stamp = datetime.fromisoformat(record[key])
            if stamp.tzinfo is None:
                raise ValueError('运行时间必须包含时区')
            record[key] = stamp.astimezone(GAME_ZONE).isoformat()
        if not isinstance(record.get('video_paths'), list) or any(not isinstance(p, str) for p in record['video_paths']):
            raise ValueError('录像路径格式无效')
        with self._connect() as db:
            previous = db.execute('SELECT profile_id, started_at FROM account_runs WHERE id=?', (record['run_id'],)).fetchone()
            if previous and previous != (identity, record['started_at']):
                raise ValueError('不能修改运行记录的账号或开始时间')
            db.execute('INSERT OR REPLACE INTO account_runs VALUES (?, ?, ?, ?)',
                (record['run_id'], identity, record['started_at'], json.dumps(record, ensure_ascii=False)))
        return record

    def latest_run(self, profile_id):
        if not self.database.exists():
            return None
        with self._connect() as db:
            row = db.execute('SELECT metadata FROM account_runs WHERE profile_id=? ORDER BY started_at DESC LIMIT 1',
                             (profile_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def backup(self):
        """Explicit consistent snapshot under a new folder; no backup rotation."""
        import shutil
        destination = self.root / 'backups' / str(uuid4())
        destination.mkdir(parents=True)
        with self._connect() as db:
            # Block concurrent writers/deletions while copying referenced assets.
            db.execute('BEGIN IMMEDIATE')
            reader = sqlite3.connect(self.database)
            backup_db = sqlite3.connect(destination / 'index.sqlite3')
            try:
                reader.backup(backup_db)
            finally:
                backup_db.close()
                reader.close()
            for (payload,) in db.execute('SELECT metadata FROM evidence'):
                record = json.loads(payload)
                for relative in (record.get('image_path'), record.get('thumbnail_path'),
                        f"{record['profile_id']}/{record['project_id']}/{record['evidence_id']}.json"):
                    if relative and self.asset_path(relative).is_file():
                        target = destination / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(self.asset_path(relative), target)
        return str(destination)

    @staticmethod
    def _write_new(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + '.pending')
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            raise FileExistsError('不能覆盖已保存证据')
        temporary.rename(path)

    def save(self, metadata, frame):
        if not metadata.get('require_image'):
            return self._save_record(metadata, frame)
        if frame is None or not metadata.get('event_id'):
            raise ValueError('核验证据必须包含图片及幂等事件编号')
        from src.runtime.diagnostic_export import atomic_json
        key = hashlib.sha256(str(metadata['event_id']).encode()).hexdigest()
        folder = self.root / 'pending_verified' / key
        folder.mkdir(parents=True, exist_ok=True)
        if not (folder / 'record.json').exists():
            ok, encoded = cv2.imencode('.png', frame)
            if not ok:
                raise OSError('核验证据原图编码失败')
            if not (folder / 'frame.png').exists():
                self._write_new(folder / 'frame.png', encoded.tobytes())
            atomic_json(folder / 'record.json', metadata)
        frozen = json.loads((folder / 'record.json').read_text(encoding='utf-8'))
        if frozen != json.loads(json.dumps(metadata)):
            raise ValueError('同一次运行不能更换证据归属或结论')
        frozen_frame = cv2.imdecode(np.frombuffer((folder / 'frame.png').read_bytes(), dtype='uint8'), cv2.IMREAD_COLOR)
        if frozen_frame is None:
            raise ValueError('待保存图片损坏')
        saved = self._save_record(frozen, frozen_frame)
        atomic_json(folder / 'done.json', {'evidence_id': saved['evidence_id']})
        self._queue_required_upload(folder, saved)
        return saved

    def recover_required(self):
        """Retry durable verified observations without repeating the game task."""
        recovered = []
        for path in (self.root / 'pending_verified').glob('*/record.json'):
            if (path.parent / 'done.json').exists() and (path.parent / 'nas.json').exists():
                continue
            try:
                metadata = json.loads(path.read_text(encoding='utf-8'))
                frame = cv2.imdecode(np.frombuffer(
                    (path.parent / 'frame.png').read_bytes(), dtype='uint8'), cv2.IMREAD_COLOR)
                if frame is not None:
                    recovered.append(self.save(metadata, frame))
            except (OSError, ValueError, sqlite3.Error):
                continue
        return recovered

    def _queue_required_upload(self, folder, record):
        if (folder / 'nas.json').exists():
            return
        try:
            from src.runtime.diagnostic_lifecycle import _session
            from src.runtime.diagnostic_session import seal_run
            from src.runtime.diagnostic_export import atomic_json
            if _session is None or _session.closed_session:
                return
            batch = seal_run(_session.run, 'verified_completion', sizes={},
                             reviewed_images=[self.asset_path(record['image_path'])], prepared_images=True)
            state = batch.parents[2] / 'states' / (batch.parents[1].name + '--' + batch.name + '.json')
            atomic_json(folder / 'nas.json', {'state': str(state)})
        except Exception:
            # The durable journal retries on the next start; NAS cannot undo completion.
            pass

    def _nas_status(self, record):
        if not record.get('require_image'):
            return ''
        key = hashlib.sha256(str(record['event_id']).encode()).hexdigest()
        marker = self.root / 'pending_verified' / key / 'nas.json'
        try:
            state = Path(json.loads(marker.read_text(encoding='utf-8'))['state'])
            value = json.loads(state.read_text(encoding='utf-8')) if state.exists() else {}
            return 'NAS 已上传' if value.get('status') == 'uploaded' else 'NAS 待上传，诊断队列重试中'
        except (OSError, ValueError, KeyError):
            return '本机已保存，NAS 待上传'

    def _save_record(self, metadata, frame):
        record = json.loads(json.dumps(metadata, ensure_ascii=False))
        if record.get('require_image') and frame is None:
            raise ValueError('该完成证据必须包含图片')
        record['profile_id'] = str(UUID(record['profile_id']))
        project = record['project_id']
        if project not in PROJECTS:
            raise ValueError('未知证据项目')
        record.setdefault('source', 'manual_capture')
        record.setdefault('completion_status', 'unknown')
        if record['source'] not in SOURCES or record['completion_status'] not in STATUSES:
            raise ValueError('证据状态或来源无效')
        record.setdefault('captured_at', now_iso())
        timestamp = datetime.fromisoformat(record['captured_at'])
        if timestamp.tzinfo is None:
            raise ValueError('证据时间必须包含时区')
        record['captured_at'] = timestamp.astimezone(GAME_ZONE).isoformat()
        if record['source'] == 'manual_capture' and record['completion_status'] != 'unknown':
            raise ValueError('人工结论必须明确标记为手动确认')
        record['period_id'] = period_for(project, record['captured_at'])
        record['period_rule'] = PROJECTS[project][1] or 'snapshot'
        record.update(schema_version=1, evidence_id=str(uuid4()), created_at=now_iso(), trashed=False)
        record.setdefault('identity_source', 'user_confirmed')
        for key in ('target_id', 'run_id', 'event_id', 'reason', 'note'):
            record.setdefault(key, '')
        record.setdefault('progress', {})
        if record['source'] == 'automatic' and record['event_id']:
            with self._connect() as db:
                previous = db.execute('''SELECT metadata FROM evidence WHERE profile_id=?
                    AND project_id=? AND json_extract(metadata, '$.event_id')=? LIMIT 1''',
                    (record['profile_id'], project, record['event_id'])).fetchone()
                if previous:
                    return json.loads(previous[0])
        record.update(image_path=None, thumbnail_path=None, image_hash=None)
        if frame is not None:
            if frame.ndim != 3 or frame.shape[2] != 3 or not frame.size or frame.dtype.name != 'uint8':
                raise ValueError('无效的游戏截图')
            folder = Path(record['profile_id']) / project / (record['period_id'] or 'unknown').replace(':', '-')
            base = folder / record['evidence_id']
            image = base.with_suffix('.png').as_posix()
            thumb = base.with_suffix('.thumb.png').as_posix()
            ok, encoded = cv2.imencode('.png', frame)
            if not ok:
                raise OSError('原图编码失败')
            data = encoded.tobytes()
            self._write_new(self.asset_path(image), data)
            # Keep the original even if thumbnail/index writing fails.
            scale = min(1, 480 / max(frame.shape[:2]))
            small = cv2.resize(frame, (max(1, round(frame.shape[1] * scale)), max(1, round(frame.shape[0] * scale))))
            ok, encoded = cv2.imencode('.png', small)
            if not ok:
                raise OSError('缩略图编码失败，原图已保留')
            self._write_new(self.asset_path(thumb), encoded.tobytes())
            record.update(image_path=image, thumbnail_path=thumb, image_hash=hashlib.sha256(data).hexdigest(), asset_status='available')
        else:
            record['asset_status'] = 'record_only' if record['source'] == 'legacy_record' else 'capture_failed'
        payload = json.dumps(record, ensure_ascii=False)
        sidecar = Path(record['profile_id']) / project / f"{record['evidence_id']}.json"
        self._write_new(self.asset_path(sidecar.as_posix()), payload.encode('utf-8'))
        with self._connect() as db:
            db.execute('INSERT INTO evidence VALUES (?, ?, ?, ?, ?, 0, ?)', (
                record['evidence_id'], record['profile_id'], project, record['captured_at'], record['period_id'], payload))
        return record

    def list_records(self, profile_id, project_id=None, trashed=False, limit=100, offset=0):
        if not self.database.exists():
            return []
        query = 'SELECT metadata, trashed FROM evidence WHERE profile_id=? AND trashed=?'
        args = [profile_id, int(trashed)]
        if project_id:
            query += ' AND project_id=?'
            args.append(project_id)
        query += ' ORDER BY captured_at DESC, rowid DESC LIMIT ? OFFSET ?'
        args += [min(max(int(limit), 1), 200), max(int(offset), 0)]
        with self._connect() as db:
            rows = db.execute(query, args).fetchall()
        result = []
        for payload, deleted in rows:
            record = json.loads(payload)
            record['trashed'] = bool(deleted)
            if record['image_path'] and not self.asset_path(record['image_path']).is_file():
                record['asset_status'] = 'missing'
            record['nas_status'] = self._nas_status(record)
            result.append(record)
        return result

    def profiles(self):
        if not self.database.exists():
            return []
        with self._connect() as db:
            return [row[0] for row in db.execute('SELECT profile_id FROM evidence UNION SELECT profile_id FROM account_runs')]

    def get_preference(self, key):
        if not self.database.exists():
            return None
        with self._connect() as db:
            row = db.execute('SELECT value FROM preferences WHERE key=?', (key,)).fetchone()
            return row[0] if row else None

    def set_preference(self, key, value):
        with self._connect() as db:
            db.execute('INSERT OR REPLACE INTO preferences VALUES (?, ?)', (key, value))

    def read_page(self, profile_id, project_id=None, trashed=False, limit=60, offset=0):
        rows = self.list_records(profile_id, project_id, trashed, limit, offset)
        return self._thumbnails(rows)

    def read_current(self, profile_id, project_id=None):
        """Latest per source/status, independent of history pagination and volume."""
        if not self.database.exists():
            return []
        result = []
        with self._connect() as db:
            for project in ([project_id] if project_id else PROJECTS):
                rows = db.execute('''SELECT metadata FROM (
                    SELECT metadata, captured_at, rowid AS seq,
                        ROW_NUMBER() OVER (PARTITION BY json_extract(metadata, '$.source'),
                            json_extract(metadata, '$.completion_status'),
                            (json_extract(metadata, '$.image_path') IS NOT NULL)
                            ORDER BY captured_at DESC, rowid DESC) AS rank
                    FROM evidence WHERE profile_id=? AND project_id=?
                        AND period_id IS ? AND trashed=0)
                    WHERE rank=1 ORDER BY captured_at DESC, seq DESC''',
                    (profile_id, project, period_for(project))).fetchall()
                for (payload,) in rows:
                    record = json.loads(payload)
                    record['trashed'] = False
                    if record['image_path'] and not self.asset_path(record['image_path']).is_file():
                        record['asset_status'] = 'missing'
                    record['nas_status'] = self._nas_status(record)
                    result.append(record)
        return self._thumbnails(result)

    def inspect_storage(self):
        """Explicit read-only audit. Orphan/pending files are NEVER deleted."""
        indexed = set()
        with self._connect() as db:
            for (payload,) in db.execute('SELECT metadata FROM evidence'):
                record = json.loads(payload)
                indexed.update(p for p in (record.get('image_path'), record.get('thumbnail_path')) if p)
        files = [p for p in self.root.rglob('*') if p.is_file() and not p.is_symlink()
                 and 'backups' not in p.relative_to(self.root).parts]
        orphans = [p.relative_to(self.root).as_posix() for p in files
                   if (p.suffix == '.pending' or p.suffix == '.png')
                   and p.relative_to(self.root).as_posix() not in indexed]
        return dict(bytes=sum(p.stat().st_size for p in files), orphans=orphans,
                    missing=[p for p in indexed if not self.asset_path(p).is_file()])

    def _thumbnails(self, rows):
        for row in rows:
            thumbnail = row.get('thumbnail_path')
            row['_thumbnail'] = (self.asset_path(thumbnail).read_bytes()
                                 if thumbnail and self.asset_path(thumbnail).is_file() else None)
        return rows

    def trash(self, evidence_id):
        with self._connect() as db:
            db.execute('UPDATE evidence SET trashed=1 WHERE id=?', (evidence_id,))

    def restore(self, evidence_id):
        with self._connect() as db:
            db.execute('UPDATE evidence SET trashed=0 WHERE id=?', (evidence_id,))

    def permanently_delete(self, evidence_id, *, confirmed=False):
        if not confirmed:
            raise ValueError('永久删除需要用户明确确认')
        with self._connect() as db:
            row = db.execute('SELECT metadata, trashed FROM evidence WHERE id=?', (evidence_id,)).fetchone()
            if row is None or not row[1]:
                raise ValueError('只能永久删除回收区中明确选中的证据')
            record = json.loads(row[0])
            paths = [record.get('image_path'), record.get('thumbnail_path'),
                     f"{record['profile_id']}/{record['project_id']}/{record['evidence_id']}.json"]
            for path in paths:
                if path:
                    self.asset_path(path).unlink(missing_ok=True)
            db.execute('DELETE FROM evidence WHERE id=?', (evidence_id,))
