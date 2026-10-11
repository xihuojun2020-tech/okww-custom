# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assemble existing wheels and a native ZIP into one verified offline release."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.update.native_release_manifest import parse_release, release_id, validate_artifacts


def build(core, gamepack, wheelhouse, output, *, published_at=None):
    core, gamepack, wheelhouse, output = map(Path, (core, gamepack, wheelhouse, output))
    if output.exists():
        raise FileExistsError('Release output must be a new directory')
    with zipfile.ZipFile(gamepack) as archive:
        names = [name for name in archive.namelist()
                 if len(name.split('/')) == 2 and name.endswith('/manifest.json')]
        if len(names) != 1:
            raise ValueError('Native ZIP requires one top-level package manifest')
        pack = json.loads(archive.read(names[0]))
    identity = {key: pack[key] for key in ('version', 'channel', 'revision')}
    prefix = 'releases/' + release_id(identity)
    dependencies = sorted(wheelhouse.glob('*.whl'))
    if not dependencies:
        raise ValueError('A complete dependency wheelhouse is required')
    if any(path.name.casefold() == core.name.casefold() for path in dependencies):
        raise ValueError('Dependency wheelhouse must exclude the paired core wheel')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.native-release-', dir=output.parent) as directory:
        staging = Path(directory)

        def artifact(source, relative):
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            with target.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            return {'path': relative, 'sha256': digest, 'size': target.stat().st_size}

        core_version = core.name.split('-')[1]
        bundle = {'schema_version': 2, 'package_id': pack['id'], **identity,
                  'published_at': published_at or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                  'core': {'version': core_version, **artifact(core, prefix + '/' + core.name)},
                  'gamepack': {'package_id': pack['id'], **identity,
                              'required_core_version': pack['required_core_version'],
                              **artifact(gamepack, prefix + '/' + gamepack.name)},
                  'wheels': [artifact(path, prefix + '/wheelhouse/' + path.name) for path in dependencies]}
        bundle = parse_release(json.dumps(bundle).encode('utf-8'))
        validate_artifacts(bundle, staging)
        (staging / 'release.json').write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        staging.rename(output)
    return output / 'release.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core', type=Path, required=True)
    parser.add_argument('--gamepack', type=Path, required=True)
    parser.add_argument('--wheelhouse', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(build(args.core, args.gamepack, args.wheelhouse, args.output))


if __name__ == '__main__':
    main()
