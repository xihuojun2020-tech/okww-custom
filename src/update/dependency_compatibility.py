"""Compare dependency inputs and repair formatting for legacy NAS installers.

This file can also run standalone with the installed application's Python.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path


def dependency_lines(data: bytes) -> tuple[str, ...]:
    return tuple(line.strip() for line in data.decode('utf-8-sig').splitlines()
                 if line.strip() and not line.lstrip().startswith('#'))


def repair_legacy_requirements(root: Path, archive: Path, *, version: str,
                               sha256: str, size: int) -> Path | None:
    from src.update.package_validation import validate_package

    root = Path(root).resolve()
    validated = validate_package(archive, expected_version=version,
                                 expected_sha256=sha256, expected_size=size)
    replacements = {}
    current = next((line for line in dependency_lines((root / 'requirements.txt').read_bytes())
                    if line.startswith('ok-script==')), '')
    if current != validated.framework:
        raise ValueError('真实框架版本发生变化；需要完整安装版本')
    with zipfile.ZipFile(archive) as package:
        for name in ('requirements.txt', 'requirements.in'):
            if name not in validated.files:
                continue
            path = root / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(f'依赖文件缺失或路径无效：{name}')
            before, after = path.read_bytes(), package.read(name)
            if dependency_lines(before) != dependency_lines(after):
                raise ValueError(f'真实运行依赖发生变化：{name}；需要完整安装版本')
            if before != after:
                replacements[name] = (before, after)
    if not replacements:
        return None
    backup = root / 'configs/update-backups' / f'dependency-format-{version}-{time.time_ns()}'
    backup.mkdir(parents=True, exist_ok=False)
    for name, (before, _) in replacements.items():
        (backup / name).write_bytes(before)
    written = []
    try:
        for name, (_, after) in replacements.items():
            pending = backup / (name + '.tmp')
            pending.write_bytes(after)
            os.replace(pending, root / name)
            written.append(name)
    except OSError:
        for name in written:
            shutil.copy2(backup / name, root / name)
        raise
    return backup


def main() -> None:
    parser = argparse.ArgumentParser(description='修复旧 NAS 更新器的依赖格式误报，不改变依赖版本或账号配置')
    parser.add_argument('--install-root', type=Path, required=True, help='含 main.py、config.py 的 working 目录')
    args = parser.parse_args()
    root = args.install_root.resolve()
    if not (root / 'main.py').is_file() or not (root / 'config.py').is_file():
        parser.error('请指定软件 working 目录')
    sys.path.insert(0, str(root))
    # Use only the current project NAS, including when the installed updater is old.
    stable = Path(r'\\192.168.3.173\羲火君 共享给我\AI诊断\OKWW-Updates\stable')
    from src.update.lan_manifest import LanRelease
    release = LanRelease.from_bytes((stable / 'latest.json').read_bytes(), expected_channel='stable')
    backup = repair_legacy_requirements(root, release.package_path(stable / 'latest.json'),
                                       version=release.version, sha256=release.sha256, size=release.size)
    print(f'已修复依赖格式，备份：{backup}' if backup else '依赖文件格式已匹配')
    print('请在软件中重新检查局域网更新并安装；账号配置和运行依赖版本未改变。')


if __name__ == '__main__':
    main()
