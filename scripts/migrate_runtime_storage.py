"""Offline, copy/verify/switch migration. Originals are never removed."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.runtime.diagnostic_export import atomic_json
from src.runtime.diagnostic_session import FileLease
from src.runtime.diagnostic_storage import storage_path


def sources(repo=REPO):
    from src.runtime.diagnostic_policy import POLICY, installation_id
    local = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share')))
    defaults = {'diagnostics': local / 'okww-custom/diagnostics' / POLICY / installation_id(repo),
                'CompletionEvidence': local / 'OKWW/CompletionEvidence',
                'MaterialPlanner': local / 'OKWW/MaterialPlanner', 'screenshots': Path(repo) / 'screenshots'}
    return {key: storage_path(key, value, repo=repo).resolve() for key, value in defaults.items()}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(root):
    result = {}
    if not root.exists():
        return result
    for directory, folders, files in os.walk(root, followlinks=False):
        for name in folders + files:
            path = Path(directory) / name
            if path.is_symlink() or path.is_junction():
                raise ValueError('迁移目录包含链接，停止以避免越界')
        for name in files:
            path = Path(directory) / name
            if path.name.endswith('.lock'):
                continue
            stat = path.stat()
            result[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return result


def require_offline(repo):
    import psutil
    for process in psutil.process_iter(['pid', 'cmdline', 'cwd']):
        if process.pid == os.getpid():
            continue
        try:
            command = ' '.join(process.info['cmdline'] or []).lower()
            cwd = process.info.get('cwd')
            if cwd and Path(cwd).resolve() == repo and any(
                    name in command for name in ('main.py', 'main_debug.py', 'launcher.py')):
                raise RuntimeError('请关闭本安装的程序后再迁移')
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def migrate(destination, *, repo=REPO, apply=False):
    repo = Path(repo).resolve()
    destination = Path(destination)
    if not destination.is_absolute() or destination.anchor.startswith('\\\\'):
        raise ValueError('目标必须是另一块本机磁盘上的绝对路径')
    if any(p.is_symlink() or p.is_junction() for p in (destination, *destination.parents)):
        raise ValueError('目标不能包含目录链接')
    destination = destination.resolve()
    old = sources(repo)
    if destination == repo or destination.is_relative_to(repo):
        raise ValueError('目标必须在程序更新目录之外')
    for root in old.values():
        if destination == root or destination.is_relative_to(root) or root.is_relative_to(destination):
            raise ValueError('目标不能与现有数据目录相互包含')
    plan = {kind: {'source': str(root), 'destination': str(destination / kind)} for kind, root in old.items()}
    if not apply:
        return plan
    require_offline(repo)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('目标必须是空文件夹；失败时保留副本，请换一个空目录重试')
    destination.mkdir(parents=True, exist_ok=True)
    with ExitStack() as locks:
        for name in ('.collector.lock', '.uploader.lock'):
            locks.enter_context(FileLease(old['diagnostics'] / name))
        before = {kind: inventory(root) for kind, root in old.items()}
        required = sum(size for entries in before.values() for size, _ in entries.values())
        if shutil.disk_usage(destination).free < required + 512 * 1024 ** 2:
            raise OSError('目标空间不足，需容纳全部副本并预留 512 MiB')
        for kind, entries in before.items():
            for relative in entries:
                source, target = old[kind] / relative, destination / kind / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                if digest(source) != digest(target):
                    raise OSError('迁移文件校验不一致，未切换目录')
        if before != {kind: inventory(root) for kind, root in old.items()}:
            raise OSError('迁移期间源文件变化，未切换目录')
        cursor = destination / 'diagnostics/source-cursors.json'
        if cursor.exists():
            cursors = json.loads(cursor.read_text(encoding='utf-8'))
            for name, value in cursors.items():
                if name.startswith('screenshots/') and '..' not in Path(name).parts:
                    target = destination / name
                    if target.is_file():
                        stat = target.stat()
                        if (value.get('size'), value.get('mtime')) == (stat.st_size, stat.st_mtime_ns):
                            value['inode'] = stat.st_ino
            atomic_json(cursor, cursors)
        config = repo / 'configs/runtime_storage.json'
        atomic_json(destination / 'migration.json', {'sources': plan, 'verified_bytes': required})
        # Switch last. Restart installs the same owned scheduled task with the
        # new root; old files remain as a rollback copy.
        atomic_json(config, {'root': str(destination)})
    return plan


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--apply', action='store_true', help='关闭程序后复制、校验并切换；默认只展示计划')
    args = parser.parse_args()
    print(json.dumps(migrate(args.destination, apply=args.apply), ensure_ascii=False, indent=2))
