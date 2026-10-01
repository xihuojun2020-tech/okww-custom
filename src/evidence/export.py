"""Verified incremental original-image ZIPs, independent of dashboard filters."""
import hashlib
import json
import os
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4
from zipfile import ZipFile, ZIP_DEFLATED

import cv2
import numpy as np

from src.evidence.model import GAME_ZONE, PROJECTS, now_iso

_locks = {}
_locks_guard = threading.Lock()


def asset_lock(root):
    # One installation lock protects export against permanent deletion; saves continue.
    with _locks_guard:
        return _locks.setdefault(str(Path(root).resolve()), threading.RLock())


def export_state(repository, profile_id):
    return json.loads(repository.get_preference('screenshot_export:' + profile_id) or '{}')


def _stamp(value):
    value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        raise ValueError('截图时间缺少时区，无法确认完整时间范围')
    return value.astimezone(GAME_ZONE)


def _name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip(' .')[:60]
    return value or '未填昵称'


def export_screenshots(repository, profile_id, nickname, cutoff, *, cancelled=None, progress=None, full=False):
    """Only a verified, durable ZIP advances receipts. Late originals are backfilled."""
    profile_id = str(UUID(profile_id))
    end = _stamp(cutoff)
    lock = asset_lock(repository.root)
    if not lock.acquire(blocking=False):
        raise RuntimeError('截图正在打包或删除，请稍后重试')
    pending = None
    try:
        def check_cancel():
            if cancelled is not None and cancelled.is_set():
                raise InterruptedError('打包已取消，上次成功记录未改变')

        check_cancel()
        # Read metadata and receipts in one short snapshot; no write lock during ZIP work.
        with repository._connect() as db:
            db.execute('BEGIN')
            saved = db.execute('SELECT value FROM preferences WHERE key=?',
                               ('screenshot_export:' + profile_id,)).fetchone()
            state = json.loads(saved[0]) if saved else {}
            rows = [dict(json.loads(payload), trashed=bool(trashed)) for payload, trashed in
                    db.execute('SELECT metadata, trashed FROM evidence WHERE profile_id=? ORDER BY rowid',
                               (profile_id,))]
        rebuild = full or state.get('day_rule') != 'beijing_4am'
        exported = set() if rebuild else set(state.get('images', []))
        rows = [row for row in rows if _stamp(row['captured_at']) <= end]
        # Game days reset at 04:00 Beijing time; select BEFORE export receipts.
        # A late older picture must not replace a newer daily/category winner.
        latest = {}
        for row in rows:
            image = row.get('image_path')
            if not image:
                continue
            key = row['project_id'] + ':' + (_stamp(row['captured_at']) - timedelta(hours=4)).date().isoformat()
            rank = (_stamp(row['captured_at']), _stamp(row.get('created_at') or row['captured_at']))
            if key not in latest or rank >= latest[key][0]:
                latest[key] = (rank, row)
        groups = {} if rebuild else dict(state.get('daily_groups', {}))
        images = {}
        for key, (rank, row) in latest.items():
            previous = groups.get(key)
            if previous and rank <= (_stamp(previous['captured_at']), _stamp(previous['created_at'])):
                continue
            if row['image_path'] not in exported:
                images[row['image_path']] = row
            groups[key] = dict(captured_at=row['captured_at'],
                               created_at=row.get('created_at') or row['captured_at'])
        if not images:
            return dict(path=None, count=0, state=state)
        start = (None if rebuild else state.get('cutoff')) or min((row['captured_at'] for row in images.values()), key=_stamp)
        if _stamp(start) > end:
            raise ValueError('当前时间早于上次打包截止时间，请检查系统时间')
        # Production root is okww监控室/CompletionEvidence; legacy standalone roots
        # still put exports inside an explicit monitor folder.
        monitor = repository.root.parent
        if monitor.name != 'okww监控室':
            monitor = repository.root / 'okww监控室'
        folder = monitor / '完成截图打包'
        folder.mkdir(parents=True, exist_ok=True)
        base = f"{_name(nickname)}_{_stamp(start):%Y%m%d-%H%M%S}_至_{end:%Y%m%d-%H%M%S}"
        final = folder / (base + '.zip')
        number = 1
        while final.exists():
            final = folder / f'{base}_{number}.zip'
            number += 1
        pending = folder / ('.' + uuid4().hex + '.pending')
        checksums = {}
        with pending.open('xb') as stream:
            with ZipFile(stream, 'w', ZIP_DEFLATED, allowZip64=True) as archive:
                for index, (image, row) in enumerate(images.items(), 1):
                    check_cancel()
                    try:
                        data = repository.asset_path(image).read_bytes()
                    except OSError as error:
                        raise OSError(f'原图缺失或无法读取：{image}；未推进打包时间') from error
                    digest = hashlib.sha256(data).hexdigest()
                    if row.get('image_hash') and digest != row['image_hash']:
                        raise ValueError(f'原图校验失败：{image}；未推进打包时间')
                    if cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) is None:
                        raise ValueError(f'原图损坏：{image}；未推进打包时间')
                    project = PROJECTS.get(row['project_id'], (row['project_id'],))[0]
                    prefix = '回收区/' if row['trashed'] else ''
                    entry = f"{prefix}{_name(project)}/{_stamp(row['captured_at']):%Y%m%d-%H%M%S}_{Path(image).name}"
                    archive.writestr(entry, data)
                    checksums[entry] = digest
                    if progress:
                        progress(index, len(images))
            stream.flush()
            os.fsync(stream.fileno())
        with ZipFile(pending) as archive:
            if archive.testzip() is not None or len(archive.namelist()) != len(images):
                raise ValueError('压缩包完整性校验失败，未推进打包时间')
            for entry, digest in checksums.items():
                check_cancel()
                if hashlib.sha256(archive.read(entry)).hexdigest() != digest:
                    raise ValueError('压缩包图片校验失败，未推进打包时间')
        check_cancel()
        # All app exports share the lock; collision suffixes preserve existing ZIPs.
        pending.rename(final)
        pending = None
        state = dict(cutoff=cutoff, completed_at=now_iso(), path=str(final), count=len(images),
                     images=sorted(exported | set(images)), daily_groups=groups, day_rule='beijing_4am')
        try:
            repository.set_preference('screenshot_export:' + profile_id, json.dumps(state, ensure_ascii=False))
        except Exception as error:
            raise OSError(f'压缩包已保存到 {final}，续打包记录保存失败；请重试，未跳过截图') from error
        return dict(path=str(final), count=len(images), state=state)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
        lock.release()
