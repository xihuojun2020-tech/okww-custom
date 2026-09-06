"""Apply a source update to a temporary previous checkout and compare SHA-256."""

from __future__ import annotations

import argparse
import hashlib
import json
import runpy
import subprocess
import tempfile
import zipfile
from pathlib import Path

from scripts.package_smoke import inspect_distribution, inspect_member
from scripts.validate_release import validate_release


def verify_update(archive: Path, root: Path, previous_ref: str) -> dict:
    root = root.resolve()
    build = runpy.run_path(str(root / '打包更新.py'))
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
        if manifest['version'] != validate_release(root):
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
            package.extractall(target)
            after = {p.relative_to(target): p.read_bytes() for p in marker.parent.rglob('*') if p.is_file()}
            if before != after:
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
            'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--previous-ref', default='v1.33.00')
    args = parser.parse_args()
    inspect_distribution(args.archive.resolve().parent)
    print(json.dumps(verify_update(args.archive, args.root, args.previous_ref), ensure_ascii=False))


if __name__ == '__main__':
    main()
