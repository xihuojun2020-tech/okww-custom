"""Append-only local material evidence. No deletion, retention or account cascade."""
import csv
import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import contextmanager, closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4, UUID
from src.materials.model import Settlement, Drop, GAME_ZONE


def now_iso():
    return datetime.now(GAME_ZONE).isoformat()


def default_root():
    from src.runtime.diagnostic_storage import storage_path
    return storage_path('MaterialPlanner', Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'.local/share'))) / 'OKWW/MaterialPlanner')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class MaterialRepository:
    def __init__(self, root=None):
        self.root = Path(root or default_root()).resolve()
        self.database = self.root / 'index.sqlite3'

    @contextmanager
    def connect(self):
        self.root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS claims (
                    id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, target_revision TEXT NOT NULL,
                    group_id TEXT NOT NULL, captured_at TEXT NOT NULL, context TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS frames (
                    record_id TEXT NOT NULL, seq INTEGER NOT NULL, path TEXT NOT NULL,
                    sha256 TEXT NOT NULL, captured_at TEXT NOT NULL, PRIMARY KEY(record_id,seq));
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, kind TEXT NOT NULL,
                    captured_at TEXT NOT NULL, complete INTEGER NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS parses (
                    claim_id TEXT NOT NULL, revision INTEGER NOT NULL, digest TEXT NOT NULL,
                    parser_version TEXT NOT NULL, payload TEXT NOT NULL, captured_at TEXT NOT NULL,
                    PRIMARY KEY(claim_id,revision), UNIQUE(claim_id,digest));
                CREATE TABLE IF NOT EXISTS claim_events (
                    id INTEGER PRIMARY KEY, claim_id TEXT NOT NULL, state TEXT NOT NULL,
                    captured_at TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS snapshot_lookup ON snapshots(profile_id,kind,captured_at);
            ''')
            with db:
                yield db
        finally:
            db.close()

    def begin_claim(self, profile_id, target_revision, group_id, captured_at=None, context=None):
        identity = str(UUID(profile_id))
        claim = str(uuid4())
        with self.connect() as db:
            db.execute('INSERT INTO claims VALUES (?,?,?,?,?,?)',
                       (claim, identity, target_revision, group_id, captured_at or now_iso(), encoded(context or {})))
        return claim

    def claim(self, claim_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM claims WHERE id=?', (claim_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown claim')
        return dict(row)

    def record_event(self, claim_id, state, payload=None):
        self.claim(claim_id)
        if state not in ('not_claimed','consumed','capture_failed','resolved'):
            raise ValueError('Invalid claim state')
        with self.connect() as db:
            db.execute('INSERT INTO claim_events(claim_id,state,captured_at,payload) VALUES (?,?,?,?)',
                       (claim_id, state, now_iso(), encoded(payload or {})))

    def save_frame(self, record_id, frame_seq, png_bytes):
        record_id = str(UUID(record_id))
        if type(frame_seq) is not int or frame_seq < 0 or not png_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Invalid evidence frame')
        digest = hashlib.sha256(png_bytes).hexdigest()
        relative = f'assets/{record_id}/{frame_seq:04d}.png'
        path = self.root / relative
        # Single SQLite writer protects the filesystem idempotency check too.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM frames WHERE record_id=? AND seq=?', (record_id,frame_seq)).fetchone()
            if row:
                if row['sha256'] != digest or not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                    raise ValueError('Immutable frame conflict')
                return dict(row)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError('Orphan frame conflict; original preserved')
            else:
                pending = path.with_name(path.name + '.' + uuid4().hex + '.pending')
                with pending.open('xb') as stream:
                    stream.write(png_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(pending, path)
            stamp = now_iso()
            db.execute('INSERT INTO frames VALUES (?,?,?,?,?)', (record_id,frame_seq,relative,digest,stamp))
        return dict(record_id=record_id, seq=frame_seq, path=relative, sha256=digest, captured_at=stamp)

    def append_settlement(self, result, parser_version, evidence=None):
        claim = self.claim(result.claim_id)
        if (claim['profile_id'],claim['target_revision'],claim['group_id']) != (
                result.profile_id,result.target_revision,result.target_group):
            raise ValueError('Claim identity cannot change')
        value = asdict(result)
        if evidence is not None:
            value['_evidence'] = evidence
        payload = encoded(value)
        digest = hashlib.sha256((parser_version+'\n'+payload).encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT revision FROM parses WHERE claim_id=? AND digest=?',
                                  (result.claim_id,digest)).fetchone()
            if previous:
                return previous['revision']
            if result.complete and not db.execute('SELECT 1 FROM frames WHERE record_id=?', (result.claim_id,)).fetchone():
                raise ValueError('Complete statistics require original screenshot evidence')
            revision = db.execute('SELECT COALESCE(MAX(revision),0)+1 FROM parses WHERE claim_id=?',
                                  (result.claim_id,)).fetchone()[0]
            db.execute('INSERT INTO parses VALUES (?,?,?,?,?,?)',
                       (result.claim_id,revision,digest,parser_version,payload,now_iso()))
        return revision

    def save_snapshot(self, profile_id, kind, payload, captured_at=None, complete=False, snapshot_id=None):
        if kind not in ('inventory','target','inventory_partial'):
            raise ValueError('Invalid snapshot kind')
        record_id = str(UUID(snapshot_id)) if snapshot_id else str(uuid4())
        identity = str(UUID(profile_id))
        stamp = captured_at or now_iso()
        if datetime.fromisoformat(stamp).tzinfo is None:
            raise ValueError('Snapshot time must include timezone')
        with self.connect() as db:
            db.execute('INSERT INTO snapshots VALUES (?,?,?,?,?,?)',
                       (record_id,identity,kind,stamp,int(complete),encoded(payload)))
        return record_id

    def latest_complete_snapshot(self, profile_id, kind):
        with self.connect() as db:
            row = db.execute('SELECT * FROM snapshots WHERE profile_id=? AND kind=? AND complete=1 '
                             'ORDER BY captured_at DESC,rowid DESC LIMIT 1', (profile_id,kind)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result['payload'] = json.loads(result['payload'])
        return result

    def list_settlements(self, profile_id, group_id=None):
        with self.connect() as db:
            rows = db.execute('SELECT p.payload FROM parses p JOIN claims c ON p.claim_id=c.id '
                'WHERE c.profile_id=? AND (? IS NULL OR c.group_id=?) AND '
                'p.revision=(SELECT MAX(q.revision) FROM parses q WHERE q.claim_id=p.claim_id) '
                'ORDER BY c.captured_at', (profile_id,group_id,group_id)).fetchall()
        results = []
        for row in rows:
            value = json.loads(row[0])
            value.pop('_evidence', None)
            value['drops'] = tuple(Drop(**{**d, 'position':tuple(d['position'])}) for d in value['drops'])
            value['errors'] = tuple(value['errors'])
            results.append(Settlement(**value))
        return results

    def pending_claims(self, profile_id):
        with self.connect() as db:
            rows = db.execute('SELECT c.* FROM claims c WHERE profile_id=? '
                "AND NOT EXISTS (SELECT 1 FROM parses p WHERE p.claim_id=c.id AND json_extract(p.payload,'$.complete')=1 "
                'AND p.revision=(SELECT MAX(q.revision) FROM parses q WHERE q.claim_id=c.id)) '
                "AND NOT EXISTS (SELECT 1 FROM claim_events e WHERE e.claim_id=c.id AND e.state IN ('not_claimed','resolved'))",
                (profile_id,)).fetchall()
        return [dict(r) for r in rows]

    def export_csv(self, profile_id, destination):
        with self.connect() as db:
            revisions = {r['claim_id']:(r['revision'],r['parser_version']) for r in db.execute(
                'SELECT claim_id,revision,parser_version FROM parses p WHERE revision='
                '(SELECT MAX(revision) FROM parses q WHERE p.claim_id=q.claim_id)')}
        with Path(destination).open('x', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(('claim_id','group','stamina','complete','reward_units','row','column','item','rarity','amount',
                             'revision','parser_version','evidence_directory'))
            for result in self.list_settlements(profile_id):
                for drop in result.drops or (None,):
                    details = (*drop.position,drop.item_id,drop.rarity,drop.amount) if drop else ('',)*5
                    writer.writerow((result.claim_id,result.target_group,result.stamina,result.complete,
                        result.reward_units,*details,*revisions[result.claim_id],f'assets/{result.claim_id}'))
        return str(destination)

    def backup(self, destination):
        destination = Path(destination).resolve()
        if destination == self.root or destination.is_relative_to(self.root):
            raise ValueError('Choose a separate backup directory')
        destination.mkdir(parents=True, exist_ok=False)
        with self.connect() as writer:
            writer.execute('BEGIN IMMEDIATE')
            with closing(sqlite3.connect(self.database)) as source, closing(sqlite3.connect(destination/'index.sqlite3')) as target:
                source.backup(target)
            if (self.root/'assets').exists():
                shutil.copytree(self.root/'assets', destination/'assets')
        return str(destination)
