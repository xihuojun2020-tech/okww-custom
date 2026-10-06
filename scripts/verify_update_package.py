"""Apply a source update to a temporary previous checkout and compare SHA-256."""

from __future__ import annotations

import argparse
import hashlib
import json
import runpy
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.package_smoke import inspect_distribution, inspect_member
from scripts.validate_release import validate_release
from src.update.package_validation import validate_package
from src.update.lan_apply import apply_request


def verify_update(archive: Path, root: Path, previous_ref: str) -> dict:
    root = root.resolve()
    build = runpy.run_path(str(root / '打包更新.py'))
    archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    release_version = validate_release(root)
    validate_package(archive, expected_version=release_version,
                     expected_sha256=archive_digest, expected_size=archive.stat().st_size)
    reference = {name: hashlib.sha256(path.read_bytes()).hexdigest()
                 for name, path in build['collect_files'](root)}
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        if len(set(name.casefold() for name in names)) != len(names):
            raise ValueError('更新包存在重复文件')
        for name in names:
            inspect_member(name)
        if set(names) != set(reference) | {build['MANIFEST_NAME']}:
            raise ValueError('更新包文件集合与当前源码不一致')
        manifest = json.loads(package.read(build['MANIFEST_NAME']))
        if manifest['version'] != release_version:
            raise ValueError('更新包版本与当前源码不一致')
        if manifest['files'] != reference or any(
                hashlib.sha256(package.read(name)).hexdigest() != digest
                for name, digest in reference.items()):
            raise ValueError('更新包 SHA-256 与当前源码不一致')
        with tempfile.TemporaryDirectory(prefix='okww-update-') as temp:
            target = Path(temp) / 'previous'
            previous_zip = Path(temp) / 'previous.zip'
            subprocess.run(['git', '-C', str(root), 'archive', '--format=zip',
                            '-o', str(previous_zip), previous_ref], check=True)
            with zipfile.ZipFile(previous_zip) as previous:
                # The archive is produced from a local Git ref, not user input.
                previous.extractall(target)
            marker = target / 'configs' / 'synthetic-preserved.json'
            marker.parent.mkdir(exist_ok=True)
            marker.write_text('{"account":"SYNTHETIC-A1"}', encoding='utf-8')
            before = {p.relative_to(target): p.read_bytes() for p in marker.parent.rglob('*') if p.is_file()}
            staging = target / 'configs/update-staging' / manifest['version']
            staging.mkdir(parents=True)
            staged_archive = staging / archive.name
            shutil.copy2(archive, staged_archive)
            request = staging / 'apply-request.json'
            request.write_text(json.dumps(dict(schema_version=1, from_version='previous',
                to_version=manifest['version'], archive=str(staged_archive),
                sha256=archive_digest, size=archive.stat().st_size, install_root=str(target),
                parent_pid=0, restart_command=[sys.executable, '-c', 'pass'])), encoding='utf-8')
            # Exercise production preflight and replacement, not only ZIP extraction.
            with patch('src.update.lan_apply.subprocess.Popen'):
                result = apply_request(request)
            if result.status != 'succeeded':
                raise ValueError(f'更新安装器验证失败：{result.message}')
            after = {p.relative_to(target): p.read_bytes() for p in marker.parent.rglob('*') if p.is_file()}
            if any(after.get(name) != data for name, data in before.items()):
                raise ValueError('更新覆盖了目标运行配置')
            for name, digest in reference.items():
                if hashlib.sha256((target / name).read_bytes()).hexdigest() != digest:
                    raise ValueError(f'增量应用后文件不同：{name}')
            for folder in ('src', 'custom_ok'):
                actual = {p.relative_to(target).as_posix() for p in (target / folder).rglob('*.py')}
                expected = {name for name in reference if name.startswith(folder + '/') and name.endswith('.py')}
                if actual != expected:
                    raise ValueError(f'增量应用后存在缺失或遗留源码：{folder}')
    return {'previous_ref': previous_ref, 'version': manifest['version'],
            'verified_files': len(reference), 'configs_preserved': True,
            'sha256': archive_digest}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--previous-ref', default='HEAD^')
    args = parser.parse_args()
    inspect_distribution(args.archive.resolve().parent)
    print(json.dumps(verify_update(args.archive, args.root, args.previous_ref), ensure_ascii=False))


if __name__ == '__main__':
    main()
