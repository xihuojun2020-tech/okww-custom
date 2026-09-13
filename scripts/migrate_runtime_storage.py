"""Offline, copy/verify/switch migration. Originals are never removed."""
import argparse
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

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
    """Diagnostic CLI for the same engine used by first-start migration."""
    from src.runtime.storage_bootstrap import discover, migrate as migrate_storage
    from src.runtime.storage_handoff import quiesce_uploaders
    repo = Path(repo).resolve()
    if not apply:
        return discover(repo)
    require_offline(repo)
    return migrate_storage(repo, destination, progress=print, quiesce=quiesce_uploaders)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--apply', action='store_true', help='关闭程序后复制、校验并切换；默认只展示计划')
    args = parser.parse_args()
    print(json.dumps(migrate(args.destination, apply=args.apply), ensure_ascii=False, indent=2))
