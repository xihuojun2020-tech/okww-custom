# SPDX-License-Identifier: AGPL-3.0-or-later
"""Publish a validated paired native release, replacing latest only at the end."""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gameframe.process_locks import package_lease
from src.update.native_release_manifest import (NativeReleaseError, artifact_path,
    artifacts, identity_key, parse_release, release_id, validate_artifacts, verify_artifact)


def _atomic_write(path, write):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('wb', dir=path.parent, prefix='.publish-', delete=False) as stream:
            temporary = Path(stream.name)
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def publish(bundle, artifact_root, destination, *, lease=package_lease):
    bundle = parse_release(json.dumps(bundle).encode('utf-8'))
    artifact_root, destination = Path(artifact_root).resolve(), Path(destination).resolve()
    validate_artifacts(bundle, artifact_root)
    channel_root = destination / bundle['package_id'] / bundle['channel']
    release_root = channel_root / 'releases' / release_id(bundle)
    record = (json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')
    with lease(channel_root, exclusive=True):
        immutable = release_root / 'release.json'
        if immutable.exists() and immutable.read_bytes() != record:
            raise NativeReleaseError('Immutable release identity already has different content')
        latest = channel_root / 'latest.json'
        if latest.exists():
            previous = parse_release(latest.read_bytes(), package_id=bundle['package_id'],
                                     expected_channel=bundle['channel'])
            if identity_key(previous) > identity_key(bundle):
                raise NativeReleaseError('Publishing would move latest backwards')
            if identity_key(previous) == identity_key(bundle) and previous != bundle:
                raise NativeReleaseError('Latest identity already has different content')
        for artifact in artifacts(bundle):
            target = artifact_path(channel_root, artifact)
            if target.exists():
                verify_artifact(target, artifact)
        for artifact in artifacts(bundle):
            source, target = artifact_path(artifact_root, artifact), artifact_path(channel_root, artifact)
            if not target.exists():
                with source.open('rb') as stream:
                    _atomic_write(target, lambda output: shutil.copyfileobj(stream, output))
            verify_artifact(target, artifact)
        # Read back both container metadata and hashes before exposing this release.
        validate_artifacts(bundle, channel_root)
        if not immutable.exists():
            _atomic_write(immutable, lambda output: output.write(record))
        _atomic_write(latest, lambda output: output.write(record))
        return latest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--artifact-root', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    bundle = parse_release(args.manifest.read_bytes())
    print(publish(bundle, args.artifact_root, args.destination))


if __name__ == '__main__':
    main()
