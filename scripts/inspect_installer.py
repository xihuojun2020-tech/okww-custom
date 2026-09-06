"""Extract an NSIS installer without running it; audit payload and source hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from scripts.package_smoke import inspect_member


def logical_payload_path(name: str) -> str | None:
    """Only pyappify's verified layout may contain a source working tree/Git log."""
    parts = PurePosixPath(name.replace('\\', '/')).parts
    if len(parts) > 4 and parts[:2] == ('data', 'apps') and parts[3] in {'repo', 'working'}:
        if parts[3] == 'repo' and parts[4] == '.git':
            return None  # Public clone metadata required by the launcher updater.
        return '/'.join(parts[4:])
    return '/'.join(parts)


def inspect_extracted(payload: Path, reference: dict[str, bytes], version: str) -> dict:
    files = {}
    for path in payload.rglob('*'):
        if path.is_symlink() or path.is_junction():
            raise ValueError('安装器解包内容包含链接')
        if not path.is_file():
            continue
        name = path.relative_to(payload).as_posix()
        logical = logical_payload_path(name)
        if logical is not None:
            inspect_member(logical, read_bytes=lambda: path.read_bytes()[:16385])
        with path.open('rb') as stream:
            files[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    source_roots = sorted(path.parent for path in payload.glob('data/apps/*/working/config.py'))
    report = {'version': version, 'files': files, 'source_trees': [],
              'installation_tested': False, 'startup_tested': False}
    for working in source_roots:
        for source in (working, working.parent / 'repo'):
            eol_only = []
            for name, expected in reference.items():
                path = source / name
                if not path.is_file():
                    raise ValueError(f'安装器缺少源码：{name}')
                data = path.read_bytes()
                if data != expected:
                    # git checkout on Windows applies CRLF to text. Retain raw
                    # file hashes and explicitly report this canonical comparison.
                    if path.suffix.lower() not in {'.py', '.txt', '.md', '.in', '.yml', '.po', '.bat', '.json', '.svg', '.qss'} or (
                            data.replace(b'\r\n', b'\n') != expected.replace(b'\r\n', b'\n')):
                        raise ValueError(f'安装器源码与引用版本不一致：{name}')
                    eol_only.append(name)
            report['source_trees'].append({'path': source.relative_to(payload).as_posix(),
                                           'verified_files': len(reference), 'eol_only_differences': eol_only})
    report['bootstrap_only'] = not source_roots
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('installer', type=Path)
    parser.add_argument('--seven-zip', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--reference-ref', default='HEAD')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    names = subprocess.check_output(['git', '-C', str(root), 'ls-tree', '-rz', '--name-only',
                                     args.reference_ref]).decode('utf-8').split('\0')
    included = ('src/', 'custom_ok/', 'assets/', 'icons/', 'i18n/')
    single = {'main.py', 'auto_proxy.py', 'config.py', 'requirements.txt', '更新日志.md', 'pyappify.yml'}
    reference = {name: subprocess.check_output(['git', '-C', str(root), 'show', f'{args.reference_ref}:{name}'])
                 for name in names if name in single or name.startswith(included)}
    version = re.search(rb'^version = "([0-9]+\.[0-9]{2}\.[0-9]{2})"', reference['config.py'], re.M).group(1).decode()
    command = str(args.seven_zip.resolve())
    installer = args.installer.resolve()
    listing = subprocess.check_output([command, 'l', '-slt', '-sccUTF-8', str(installer)], timeout=60).decode('utf-8')
    members = listing.split('----------', 1)[1]
    for line in members.splitlines():
        if line.startswith('Path = '):
            path = PurePosixPath(line[7:].replace('\\', '/'))
            if path.is_absolute() or '..' in path.parts or ':' in str(path):
                raise ValueError('安装器包含不安全的解包路径')
    if 'Symbolic Link = ' in members or 'Hard Link = ' in members:
        raise ValueError('安装器包含链接')
    with tempfile.TemporaryDirectory(prefix='okww-installer-') as temp:
        subprocess.run([command, 'x', '-y', '-sccUTF-8', str(installer), '-o' + temp],
                       check=True, stdout=subprocess.DEVNULL, timeout=180)
        report = inspect_extracted(Path(temp), reference, version)
    if 'online' not in installer.name.lower() and report['bootstrap_only']:
        raise ValueError('离线安装器缺少实际源码树')
    with installer.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    report.update(installer=installer.name, reference_ref=args.reference_ref, sha256=digest)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('installer', 'version', 'sha256', 'bootstrap_only',
                                                'installation_tested', 'startup_tested')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
