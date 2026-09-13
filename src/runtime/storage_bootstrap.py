"""Pre-application, resumable copy/verify/commit storage migration.

No Qt, config, OCR or repository imports are allowed here. Originals survive.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
import uuid
from itertools import zip_longest
from contextlib import ExitStack, closing

SCHEMA = 2
KINDS = ('diagnostics', 'MaterialPlanner', 'CompletionEvidence', 'screenshots',
         'logs', 'recordings', 'backups', 'exports', 'cache', 'SequenceBackups')


def read_json(path, default=None):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else default


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.partial')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class Lease:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.stream = open(path, 'a+b')
        self.stream.seek(0, 2)
        if not self.stream.tell():
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
        except Exception:
            self.stream.close()
            raise

    def __enter__(self): return self
    def __exit__(self, *_): self.stream.close()


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def local_path(path):
    path = Path(path).absolute()
    if path.anchor.startswith('\\\\'):
        raise ValueError('运行数据必须位于本机磁盘')
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
            raise ValueError(f'迁移路径包含目录链接：{part}')
    if not Path(path.anchor).is_dir():
        raise OSError(f'数据盘不可用：{path.anchor}')
    return path.resolve()


def discover(repo):
    repo = Path(repo).resolve()
    local = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share')))
    legacy_id = hashlib.sha256(os.path.normcase(str(repo)).encode()).hexdigest()[:16]
    defaults = dict(zip(KINDS, (local / 'okww-custom/diagnostics/automatic-v1' / legacy_id,
        local / 'OKWW/MaterialPlanner', local / 'OKWW/CompletionEvidence', repo / 'screenshots',
        repo / 'logs', repo / 'okww监控室', repo / 'configs_backup', repo / 'export_accounts', repo / 'cache')))
    defaults['SequenceBackups'] = Path(os.environ.get('APPDATA', str(local))) / 'KRLauncher_backup'
    selected = read_json(repo / 'configs/runtime_storage.json', {})
    active = {k: Path(selected['root']) / k if selected.get('root') and k in KINDS[:4] else v
              for k, v in defaults.items()}
    # Only read the known settings files, not arbitrary private config content.
    warehouse = read_json(repo / 'configs/数据仓库文件夹.json', {}) or {}
    backup = read_json(repo / 'configs/Config Backup.json', {}) or {}
    sequence = read_json(repo / 'configs/KRLauncherSwitchTask.json', {}) or {}
    if sequence.get('备份目录'):
        value = Path(sequence['备份目录'])
        active['SequenceBackups'] = value if value.is_absolute() else repo / value
        if not active['SequenceBackups'].is_dir():
            raise OSError(f'已配置的序列备份目录不可用：{active["SequenceBackups"]}')
    wh = str(warehouse.get('数据仓库文件夹', '')).strip()
    if wh:
        base = Path(wh) if Path(wh).is_absolute() else repo / wh
        if not base.is_dir(): raise OSError(f'已配置的数据仓库不可用：{base}')
        for kind, sub in (('recordings', 'okww监控室'), ('backups', '配置备份'), ('exports', '账号数据')):
            active[kind] = base / 'ok仓库' / sub
    elif backup.get('Config Backup Directory'):
        base = Path(backup['Config Backup Directory'])
        active['backups'] = base if base.is_absolute() else repo / base
        if not active['backups'].is_dir(): raise OSError(f'已配置的备份目录不可用：{base}')
    if selected.get('schema') == SCHEMA:
        active = {k: Path(selected.get('paths', {}).get(k, str(Path(selected['root']) / k))) for k in KINDS}
    result = {}
    for kind, source in active.items():
        source = local_path(source)
        if selected.get('root') and kind in KINDS[:4] and not Path(selected['root']).is_dir():
            raise OSError(f'旧数据目录不可用：{selected["root"]}')
        result[kind] = {'source': str(source), 'history': []}
        old = local_path(defaults[kind])
        if old != source and old.exists():
            result[kind]['history'].append(str(old))
    return result


def inventory(root):
    root = local_path(root)
    entries = {}
    if not root.exists(): return entries
    for directory, folders, files in os.walk(root, followlinks=False):
        for name in folders + files:
            local_path(Path(directory) / name)
        for name in files:
            if name.endswith(('.lock', '-wal', '-shm')): continue
            path = Path(directory) / name
            stat = path.stat()
            entries[path.relative_to(root).as_posix()] = [stat.st_size, stat.st_mtime_ns]
    return entries


def sqlite_snapshot(source, target):
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=5)) as reader:
        with closing(sqlite3.connect(target)) as writer:
            deadline = time.monotonic() + 30
            def progress(*_):
                if time.monotonic() > deadline:
                    raise TimeoutError('数据库快照超时，等待其他写入者结束后重试')
            reader.backup(writer, pages=256, progress=progress)
            if writer.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError(f'数据库完整性校验失败：{source}')
            # Logical equality, including WAL-committed rows; not byte layout equality.
            if any(left != right for left, right in zip_longest(reader.iterdump(), writer.iterdump())):
                raise ValueError(f'数据库快照内容不一致：{source}')


def copy_verified(source, target, *, reusable=False):
    local_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as stream:
        database = stream.read(16) == b'SQLite format 3\x00'
    partial = target.with_name(target.name + '.partial')
    local_path(partial)
    if database:
        # Rebuild an uncommitted snapshot on resume; it may include newer WAL rows.
        partial.unlink(missing_ok=True)
        sqlite_snapshot(source, partial)
        expected = digest(partial)
    else:
        expected = digest(source)
        if target.exists() and digest(target) == expected: return expected
        if target.exists() and not reusable:
            raise FileExistsError(f'目标存在不同内容，保留双方资料：{target}')
        shutil.copy2(source, partial)
        with partial.open('rb+') as stream: os.fsync(stream.fileno())
        if digest(partial) != expected:
            raise OSError(f'复制校验失败：{source}')
    if target.exists() and not reusable and digest(target) != expected:
        raise FileExistsError(f'目标存在不同内容，保留双方资料：{target}')
    os.replace(partial, target)
    if digest(target) != expected: raise OSError(f'目标读回校验失败：{target}')
    return expected


def rewrite_references(destination, sources):
    # Remote immutable manifests keep their paths and hashes unchanged.
    old = Path(sources['diagnostics']['source'])
    diagnostic_roots = [old, *(Path(p) for p in sources['diagnostics']['history'])]
    previous = read_json(old.parent / 'migration.json', {})
    previous_source = previous.get('sources', {}).get('diagnostics', {}).get('source')
    if previous_source: diagnostic_roots.append(Path(previous_source))
    for marker in (destination / 'CompletionEvidence/pending_verified').glob('*/nas.json'):
        value = read_json(marker)
        state = Path(value.get('state', ''))
        for root in diagnostic_roots:
            if state.is_absolute() and state.is_relative_to(root):
                value['state'] = str(destination / 'diagnostics' / state.relative_to(root))
                atomic_json(marker, value)
                break
    cursor = destination / 'diagnostics/source-cursors.json'
    if cursor.exists():
        values = read_json(cursor)
        for name, value in values.items():
            if name.startswith('screenshots/') and '..' not in Path(name).parts:
                target = destination / name
                if target.is_file():
                    stat = target.stat()
                    if (value.get('size'), value.get('mtime')) == (stat.st_size, stat.st_mtime_ns):
                        value['inode'] = stat.st_ino
        atomic_json(cursor, values)
    database = destination / 'CompletionEvidence/index.sqlite3'
    if database.exists():
        with closing(sqlite3.connect(database)) as db, db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'account_runs' in tables:
                for identity, payload in db.execute('SELECT id, metadata FROM account_runs').fetchall():
                    value = json.loads(payload)
                    paths = []
                    for name in value.get('video_paths', []):
                        path = Path(name)
                        root = Path(sources['recordings']['source'])
                        paths.append(str(destination / 'recordings' / path.relative_to(root))
                                     if path.is_absolute() and path.is_relative_to(root) else name)
                    value['video_paths'] = paths
                    db.execute('UPDATE account_runs SET metadata=? WHERE id=?',
                               (json.dumps(value, ensure_ascii=False), identity))
            if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('证据路径修复后数据库校验失败')


def verify_assets(destination, sources):
    """Existing missing assets remain anomalies; no migration may lose an existing asset."""
    anomalies = []
    for kind in ('MaterialPlanner', 'CompletionEvidence'):
        target_root, source_root = destination / kind, Path(sources[kind]['source'])
        database = target_root / 'index.sqlite3'
        if not database.exists(): continue
        with closing(sqlite3.connect(database)) as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            rows = []
            if kind == 'MaterialPlanner' and 'frames' in tables:
                rows = db.execute('SELECT path, sha256 FROM frames')
            if kind == 'CompletionEvidence' and 'evidence' in tables:
                def evidence_rows():
                    for (payload,) in db.execute('SELECT metadata FROM evidence'):
                        value = json.loads(payload)
                        yield value.get('image_path'), value.get('image_hash')
                        yield value.get('thumbnail_path'), None
                rows = evidence_rows()
            for relative, expected in rows:
                if not relative: continue
                if Path(relative).is_absolute() or '..' in Path(relative).parts:
                    raise ValueError(f'业务图片引用越界：{kind}')
                old, new = source_root / relative, target_root / relative
                if old.is_file():
                    if not new.is_file() or digest(old) != digest(new):
                        raise OSError(f'迁移后缺失或改变业务图片：{kind}/{relative}')
                    if expected and digest(new) != expected:
                        anomalies.append(f'{kind}/{relative}: source_hash_mismatch')
                else:
                    anomalies.append(f'{kind}/{relative}: already_missing_at_source')
    atomic_json(destination / 'migration/asset-check.json', {'existing_anomalies': anomalies})


def validate_current(repo, value):
    root = local_path(value['root'])
    marker = read_json(root / 'migration.json', {})
    if not root.is_dir() or not value.get('generation') or marker.get('generation') != value['generation']:
        raise OSError(f'活动数据目录或迁移标记不可用，拒绝初始化空仓库：{root}')
    if marker.get('source_repo', str(repo)) != str(repo):
        raise ValueError('活动数据属于另一个安装路径，不能同时共用仓库')
    return value


def migrate(repo, destination, *, progress=lambda message: None, quiesce=None):
    repo, destination = local_path(repo), local_path(destination)
    if destination.anchor.casefold() != repo.anchor.casefold():
        raise ValueError('目标必须位于程序安装盘')
    if destination == repo or destination.is_relative_to(repo) or repo.is_relative_to(destination):
        raise ValueError('数据根必须位于程序更新目录之外')
    config = repo / 'configs/runtime_storage.json'
    with Lease(repo / 'configs/.storage-migration.lock'):
        current = read_json(config, {})
        if current.get('schema') == SCHEMA and Path(current['root']) == destination:
            return validate_current(repo, current)
        sources = discover(repo)
        progress('正在检查来源并暂停本安装的后台写入')
        for item in sources.values():
            for source in [item['source'], *item['history']]:
                path = Path(source)
                if path == destination or destination.is_relative_to(path) or path.is_relative_to(destination):
                    raise ValueError(f'迁移来源与目标相互包含：{path}')
        destination.mkdir(parents=True, exist_ok=True)
        journal = destination / 'migration/progress.json'
        state = read_json(journal, {})
        if state and state.get('repo') != str(repo): raise ValueError('目标属于其他安装实例')
        if not state and any(destination.iterdir()):
            raise ValueError('目标存在未归属资料，不能覆盖')
        state.update(repo=str(repo), root=str(destination), sources=sources,
                     migration_id=state.get('migration_id', uuid.uuid4().hex), phase='QUIESCE',
                     old_config=state.get('old_config', current), files=state.get('files', {}))
        atomic_json(journal, state)
        gate = repo / 'configs/storage_migration.json'
        atomic_json(gate, {'generation': state['migration_id'], 'root': str(destination)})
        committed = False
        try:
            with ExitStack() as stack:
                if quiesce and Path(sources['diagnostics']['source']).is_dir():
                    stack.enter_context(quiesce(repo, destination))
                if Path(sources['diagnostics']['source']).is_dir():
                    for name in ('.collector.lock', '.uploader.lock'):
                        stack.enter_context(Lease(Path(sources['diagnostics']['source']) / name))
                state['phase'] = 'COPY'
                # Existing installation-local logs/cache are protected by the updater.
                paths = {k: str(repo / k if k in ('logs', 'cache') else destination / k) for k in KINDS}
                roots = [(kind, Path(item['source']), Path(paths[kind])) for kind, item in sources.items()
                         if Path(item['source']) != Path(paths[kind])]
                roots += [(kind + '/history', Path(old), destination / 'migration/history' / kind /
                           hashlib.sha256(old.encode()).hexdigest()[:12])
                          for kind, item in sources.items() for old in item['history']]
                before = {str(source): inventory(source) for _, source, _ in roots}
                progress('正在建立数据库一致性快照和文件清单')
                # Reserve SQLite writers while a separate reader takes the snapshot.
                # This also protects sources shared by older installations.
                for _, source, _ in roots:
                    for relative in before[str(source)]:
                        path = source / relative
                        with path.open('rb') as stream:
                            is_database = stream.read(16) == b'SQLite format 3\x00'
                        if is_database:
                            db = stack.enter_context(closing(sqlite3.connect(path, timeout=2)))
                            db.execute('BEGIN IMMEDIATE')
                total = sum(len(items) for items in before.values())
                size = sum(v[0] for items in before.values() for v in items.values())
                remaining = sum(v[0] for _, source, target in roots for rel, v in before[str(source)].items()
                                if not (target / rel).exists())
                if shutil.disk_usage(destination).free < remaining + 512 * 1024**2:
                    raise OSError(f'安装盘空间不足，剩余迁移约 {remaining} 字节，另需 512 MiB 余量')
                count, checkpoint = 0, time.monotonic()
                for kind, source, target in roots:
                    target.mkdir(parents=True, exist_ok=True)
                    for relative in before[str(source)]:
                        dest = target / relative
                        key = (dest.relative_to(destination).as_posix() if dest.is_relative_to(destination)
                               else '@installation/' + dest.relative_to(repo).as_posix())
                        previous = state['files'].get(key)
                        # A previously copied file may be replaced only if our manifest owns it.
                        owned = bool(previous and previous.get('source') == str(source / relative))
                        sha = copy_verified(source / relative, dest, reusable=owned)
                        state['files'][key] = {'source': str(source / relative), 'sha256': sha}
                        count += 1
                        progress(f'已校验 {count}/{total} 个文件 · {kind} · 总量 {size / 1024**3:.2f} GiB')
                        if count % 32 == 0 or time.monotonic() - checkpoint >= 1:
                            atomic_json(journal, state)
                            checkpoint = time.monotonic()
                if before != {str(source): inventory(source) for _, source, _ in roots}:
                    raise OSError('源数据在迁移期间变化，未切换；请关闭相关程序后重试')
                state['phase'] = 'REWRITE'
                atomic_json(journal, state)
                rewrite_references(destination, sources)
                verify_assets(destination, sources)
                identity = read_json(repo / 'configs/storage_identity.json', {})
                result = {'schema': SCHEMA, 'root': str(destination),
                          'instance_id': identity.get('instance_id', state['migration_id']),
                          'generation': state['migration_id'], 'paths': paths}
                atomic_json(destination / 'migration.json', {'sources': sources, 'verified_bytes': size,
                            'generation': state['migration_id'], 'source_repo': str(repo)})
                state['phase'] = 'COMMIT'
                atomic_json(journal, state)
                atomic_json(config, result)
                committed = True
                gate.unlink(missing_ok=True)
                state['phase'] = 'READY'
                atomic_json(journal, state)
                return result
        except BaseException as error:
            state.update(phase='READY' if committed else 'BLOCKED', error=str(error))
            atomic_json(journal, state)
            raise
        finally:
            gate.unlink(missing_ok=True)


def bootstrap(repo, *, progress=lambda message: None, quiesce=None):
    repo = local_path(repo)
    config = read_json(repo / 'configs/runtime_storage.json', {})
    if config.get('schema') == SCHEMA:
        root = local_path(config['root'])
        if root.anchor.casefold() == repo.anchor.casefold():
            return validate_current(repo, config)
    identity_path = repo / 'configs/storage_identity.json'
    with Lease(repo / 'configs/.storage-identity.lock'):
        identity = read_json(identity_path, {})
        if not identity:
            identity = {'instance_id': uuid.uuid4().hex}
            atomic_json(identity_path, identity)
        target = identity.get('target')
        if target and Path(target).anchor.casefold() != repo.anchor.casefold():
            target = None
        if not target:
            candidates = [Path(repo.anchor) / 'OKWW-Data', repo.parent / 'OKWW-Data']
            for base in candidates:
                try:
                    local_path(base).mkdir(parents=True, exist_ok=True)
                    target = base / identity['instance_id']
                    # Probe parent without creating a nonempty target.
                    probe = base / ('.probe-' + uuid.uuid4().hex)
                    probe.write_bytes(b''); probe.unlink()
                    break
                except OSError:
                    target = None
            if target is None: raise OSError('程序安装盘没有可写的数据位置')
            identity['target'] = str(target)
            atomic_json(identity_path, identity)
    return migrate(repo, identity['target'], progress=progress, quiesce=quiesce)


def configure_process_storage(value):
    """Only this application's child processes inherit the private temp directory."""
    root = Path(value['root'])
    temporary = root / 'cache/tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ['TMP'] = os.environ['TEMP'] = str(temporary)
    import tempfile
    tempfile.tempdir = str(temporary)
