# -*- coding: utf-8 -*-
"""Build a source update from tracked files, excluding local configuration and venvs.

Usage: .venv/Scripts/python.exe 打包更新.py [output_directory]
Install into a stopped source checkout, then install requirements.txt with its
own Python 3.12 venv before restarting. The launcher installer is built by CI.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from scripts.package_smoke import inspect_member
from scripts.validate_release import validate_release

ROOT = Path(__file__).resolve().parent
SYNC_ITEMS = [
    'src', 'custom_ok', 'assets', 'icons', 'i18n',
    'auto_proxy.py', 'config.py', 'main.py', 'fix_venv.py', '启动okww.bat',
    '更新日志.md', 'requirements.txt', 'requirements.in', 'requirements-dev.txt', 'setup.py', 'pyappify.yml',
]
MANIFEST_NAME = 'update-manifest.json'


def collect_files(root=ROOT, *, tracked_files=None):
    """Only tracked sources; any missing required file aborts the build."""
    root = Path(root).resolve()
    if tracked_files is None:
        tracked_files = subprocess.check_output(
            ['git', '-C', str(root), 'ls-files', '-z']).decode('utf-8').split('\0')
    selected = sorted({name for name in tracked_files if name and any(
        name == item or name.startswith(item + '/') for item in SYNC_ITEMS)})
    for item in SYNC_ITEMS:
        if not any(name == item or name.startswith(item + '/') for name in selected):
            raise ValueError(f'更新包缺少必需的受控来源：{item}')
    files = []
    for name in selected:
        path = root / name
        inspect_member(name)
        if not path.is_file() or path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root):
            raise ValueError(f'更新包来源缺失或越界：{name}')
        if any(parent.is_symlink() or parent.is_junction() for parent in path.parents if parent != root):
            raise ValueError(f'更新包来源包含链接：{name}')
        files.append((name, path))
    return files


def build_package(output_dir, root=ROOT, *, tracked_files=None):
    root = Path(root).resolve()
    version = validate_release(root)
    files = collect_files(root, tracked_files=tracked_files)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f'okww_update_v{version}.zip'
    pending = archive.with_suffix('.zip.tmp')
    framework = next(line.strip() for line in (root / 'requirements.txt').read_text(encoding='utf-8').splitlines()
                     if line.startswith('ok-script=='))
    manifest = {'version': version, 'framework': framework, 'files': {}}
    try:
        with zipfile.ZipFile(pending, 'w', zipfile.ZIP_DEFLATED) as package:
            for name, path in files:
                data = path.read_bytes()
                package.writestr(name, data)
                manifest['files'][name] = hashlib.sha256(data).hexdigest()
            package.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        pending.replace(archive)
    finally:
        pending.unlink(missing_ok=True)
    return archive


def main():
    output_dir = sys.argv[1] if len(sys.argv) > 1 else ROOT / 'dist'
    archive = build_package(output_dir)
    print(f'更新包已生成：{archive}')
    print('关闭目标程序，解压到源码目录，使用目标 .venv 的 Python 3.12 安装 requirements.txt 后启动。')
    print('账号配置和本机 Python 路径由目标设备保留；安装器由 GitHub Actions 单独生成。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
