"""Build the independent combat entrypoint and AGPL production code/assets."""

import argparse
import json
from pathlib import Path

from scripts.build_gamepack import (ROOT, payload_files, source_metadata,
                                    write_gamepack_archive)


PACKAGE = Path('gamepacks/wuthering_waves_native')
METADATA = {
    'LICENSE.txt',
    'docs/research/2026-10-10-framework-asset-provenance.json',
    'docs/research/2026-10-10-framework-asset-provenance.md',
}


def native_metadata(source_root=ROOT):
    """Keep native entries tied to the application's real task registry."""
    original = source_metadata(source_root)
    tasks = []
    for task in original['tasks'][1:]:
        name = task['class']
        capabilities = ['frames', 'keyboard', 'mouse']
        if name in {'SecondSolTask', 'ResonanceSimulationTask'}:
            capabilities.append('foreground-query')
        if name == 'ResonanceSimulationTask':
            capabilities.append('hotkey-query')
        tasks.append({
            'id': 'auto-combat' if name == 'AutoCombatTask' else name,
            'title': task['title'], 'kind': task['kind'],
            'default_config': {'_enabled': True} if task['kind'] == 'service' else {},
            'required_capabilities': capabilities,
            'module': task['module'], 'class': name,
            'integration': 'native-production-rules',
            'config_scope': 'native-data-directory',
        })
    return {'version': original['version'], 'tasks': tasks, 'supports_session': True,
            'management': True}


def build_native_gamepack(output, *, source_root=ROOT):
    root = Path(source_root).resolve()
    pack = root / PACKAGE
    manifest = json.loads((pack / 'manifest.json').read_text(encoding='utf-8'))
    manifest.update(native_metadata(root), source_root='payload')
    content = {name: (pack / name).read_bytes()
               for name in ('plugin.py', 'README.md', 'requirements.txt', 'requirements-management.txt')}
    for path in payload_files(root):
        relative = path.relative_to(root).as_posix()
        if relative in METADATA or relative.startswith(('src/', 'assets/')):
            content['payload/' + relative] = path.read_bytes()
    content['manifest.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    return write_gamepack_archive(content, output, 'wuthering_waves_native')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    args = parser.parse_args()
    print(build_native_gamepack(args.output, source_root=args.source_root))


if __name__ == '__main__':
    main()
