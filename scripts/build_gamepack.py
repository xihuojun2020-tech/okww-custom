"""Build the complete AGPL compatibility gamepack without user runtime data."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = Path('gamepacks/wuthering_waves')
ROOT_FILES = ('main.py', 'config.py', 'auto_proxy.py', 'requirements.txt',
              'requirements.in', 'LICENSE.txt', 'README.md', '更新日志.md',
              'pyappify.yml', 'setup.py', 'CONTRIBUTING.md',
              'docs/research/2026-10-10-framework-asset-provenance.json',
              'docs/research/2026-10-10-framework-asset-provenance.md')
FOLDERS = {'src': {'.py', '.ps1'}, 'custom_ok': {'.py'},
           'assets': {'.json', '.onnx', '.png'},
           'i18n': {'.po', '.mo'}, 'icons': {'.png', '.ico'}}


def source_metadata(source_root):
    """Read the real registry without importing config, OK, Qt or game classes."""
    root = Path(source_root)
    tree = ast.parse((root / 'config.py').read_text(encoding='utf-8'))
    version = next(ast.literal_eval(node.value) for node in tree.body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'version' for t in node.targets))
    config = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == 'config' for t in node.targets))
    registry = {ast.literal_eval(key): value for key, value in zip(config.keys, config.values)
                if isinstance(key, ast.Constant) and key.value in ('onetime_tasks', 'trigger_tasks')}
    tasks = [{'id': 'application', 'title': '完整鸣潮应用（兼容运行时）',
              'kind': 'application', 'default_config': {}, 'required_capabilities': [],
              'integration': 'legacy-application'}]
    for key, kind in (('onetime_tasks', 'one-shot'), ('trigger_tasks', 'service')):
        for module, class_name in ast.literal_eval(registry[key]):
            filename = root / (module.replace('.', '/') + '.py')
            module_tree = ast.parse(filename.read_text(encoding='utf-8-sig'))
            cls = next(node for node in module_tree.body
                       if isinstance(node, ast.ClassDef) and node.name == class_name)
            names = [node.value.value for node in ast.walk(cls)
                     if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                     and isinstance(node.value.value, str)
                     and any(isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                             and t.value.id == 'self' and t.attr == 'name' for t in node.targets)]
            visibility = [node.value.value for node in ast.walk(cls)
                          if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                          and type(node.value.value) is bool
                          and any(isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                                  and t.value.id == 'self' and t.attr == 'visible' for t in node.targets)]
            tasks.append({'id': class_name, 'title': names[0] if names else class_name,
                          'visible': visibility[-1] if visibility else True,
                          'kind': kind, 'default_config': {}, 'required_capabilities': [],
                          'integration': 'legacy-task', 'module': module, 'class': class_name,
                          'config_scope': 'production-installation'})
    characters = [p.relative_to(root).as_posix() for p in sorted((root / 'src/char').glob('*.py'))]
    return {'version': version, 'tasks': tasks, 'characters': characters}


def payload_files(source_root):
    """Allow only production directories and explicit metadata, never configs/logs."""
    root = Path(source_root).resolve()
    files = [root / name for name in ROOT_FILES]
    for folder, suffixes in FOLDERS.items():
        for path in sorted((root / folder).rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            if path.name.startswith('.') or path.suffix in {'.pyc', '.pyo', '.log', '.zip'}:
                continue
            if path.suffix in suffixes:
                if not path.resolve().is_relative_to(root):
                    raise ValueError(f'Payload symlink leaves source root: {path}')
                files.append(path)
    return tuple(sorted(files))


def build_gamepack(output, *, source_root=ROOT):
    root = Path(source_root).resolve()
    pack = root / PACKAGE
    manifest = json.loads((pack / 'manifest.json').read_text(encoding='utf-8'))
    manifest.update(source_metadata(root), source_root='payload', distribution='self-contained-source')
    content = {name: (pack / name).read_bytes() for name in ('plugin.py', 'bootstrap.py', 'README.md')}
    for path in payload_files(root):
        content['payload/' + path.relative_to(root).as_posix()] = path.read_bytes()
    content['manifest.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    return write_gamepack_archive(content, output, 'wuthering_waves')


def write_gamepack_archive(content, output, package_directory):
    """Write either production package with the same reproducible ZIP/index contract."""
    # The index covers everything except itself, including the manifest.
    content['files.json'] = (json.dumps({name: hashlib.sha256(data).hexdigest()
                                       for name, data in sorted(content.items())},
                                      indent=2) + '\n').encode('utf-8')
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f'Build output already exists: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(content.items()):
            info = zipfile.ZipInfo(package_directory + '/' + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    args = parser.parse_args()
    print(build_gamepack(args.output, source_root=args.source_root))


if __name__ == '__main__':
    main()
