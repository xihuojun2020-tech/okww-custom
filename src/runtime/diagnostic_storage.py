"""Installation-local storage selection, shared by application and uploader."""
import json
from pathlib import Path


def storage_path(kind, fallback, *, repo=None):
    if repo is None:
        from src.runtime.diagnostic_policy import REPO
        repo = REPO
    config = Path(repo) / 'configs/runtime_storage.json'
    gate = Path(repo) / 'configs/storage_migration.json'
    if gate.exists():
        pending = json.loads(gate.read_text(encoding='utf-8'))
        current = json.loads(config.read_text(encoding='utf-8')) if config.exists() else {}
        if current.get('generation') != pending.get('generation'):
            raise OSError('运行数据正在迁移，请等待启动迁移完成')
    if not config.exists():
        return Path(fallback)
    value = json.loads(config.read_text(encoding='utf-8'))
    root = Path(value['root'])
    if not root.is_absolute() or root.anchor.startswith('\\\\'):
        raise ValueError('运行数据目录必须是本机绝对路径')
    if not root.is_dir():
        raise OSError('运行数据盘不可用，请恢复磁盘连接；不会切换到空目录')
    selected = Path(value.get('paths', {}).get(kind, str(root / kind)))
    if not selected.is_absolute() or selected.anchor.casefold() != root.anchor.casefold():
        raise ValueError('运行资料路径不在安装数据盘')
    return selected


def redirected_diagnostics(root):
    """Let an owned scheduled action using the previous path follow migration."""
    selected = storage_path('diagnostics', root)
    marker = selected.parent / 'migration.json'
    if selected != Path(root) and marker.is_file():
        value = json.loads(marker.read_text(encoding='utf-8'))
        old = value.get('sources', {}).get('diagnostics', {}).get('source')
        if old and Path(old).resolve() == Path(root).resolve():
            return selected
    return Path(root)
