# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schema 2 paired native releases; metadata-only, without importing game code."""

from datetime import datetime
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import tempfile
import zipfile

from gameframe.packages import extract_zip, verify_index


CHANNELS = ('stable', 'beta', 'alpha')
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
_TOP = {'schema_version', 'package_id', 'version', 'channel', 'revision',
        'published_at', 'core', 'gamepack', 'wheels'}
_ARTIFACT = {'path', 'sha256', 'size'}
_PACK = _ARTIFACT | {'package_id', 'version', 'channel', 'revision', 'required_core_version'}
_RANK = {'alpha': 0, 'beta': 1, 'stable': 2}
_CORE_VERSION = re.compile(r'(\d+)\.(\d+)\.(\d+)(?:([ab])([1-9]\d*))?', re.ASCII)


class NativeReleaseError(ValueError):
    pass


def core_version_key(value):
    """Supported PEP 440 release subset: three numbers, optionally aN or bN."""
    match = _CORE_VERSION.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise NativeReleaseError('Unsupported core release version')
    major, minor, patch, phase, revision = match.groups()
    return (int(major), int(minor), int(patch),
            {'a': 0, 'b': 1, None: 2}[phase], int(revision or 0))


def identity_key(value):
    version, channel, revision = value['version'], value['channel'], value['revision']
    if not isinstance(version, str) or not re.fullmatch(r'[0-9]+\.[0-9]{2}\.[0-9]{2}', version):
        raise NativeReleaseError('Invalid fixed-width product version')
    if channel not in CHANNELS or type(revision) is not int:
        raise NativeReleaseError('Invalid release channel/revision')
    if (channel == 'stable' and revision != 0) or (channel != 'stable' and revision <= 0):
        raise NativeReleaseError('Invalid release channel/revision')
    return (*map(int, version.split('.')), _RANK[channel], revision)


def release_id(bundle):
    suffix = '' if bundle['channel'] == 'stable' else f"-{bundle['channel']}.{bundle['revision']}"
    return 'v' + bundle['version'] + suffix


def _fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != expected:
        raise NativeReleaseError(f'Invalid {label} fields')


def _relative_path(value):
    if (not isinstance(value, str) or any(char in value for char in '\\:%?#')
            or any(ord(char) < 32 for char in value)):
        raise NativeReleaseError('Invalid artifact path')
    parts = value.split('/')
    if PurePosixPath(value).is_absolute() or any(part in ('', '.', '..') for part in parts):
        raise NativeReleaseError('Artifact path escapes its release root')
    if any(part.endswith(('.', ' ')) or PureWindowsPath(part).is_reserved() for part in parts):
        raise NativeReleaseError('Artifact path is not a regular Windows file path')
    return parts


def _artifact(value, bundle):
    parts = _relative_path(value['path'])
    if parts[:2] != ['releases', release_id(bundle)] or len(parts) < 3:
        raise NativeReleaseError('Artifact path does not match its immutable release')
    if not isinstance(value['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', value['sha256']):
        raise NativeReleaseError('Invalid artifact SHA256')
    if type(value['size']) is not int or not 1 <= value['size'] <= MAX_ARTIFACT_BYTES:
        raise NativeReleaseError('Invalid artifact size')


def artifacts(bundle):
    return (bundle['core'], bundle['gamepack'], *bundle['wheels'])


def parse_release(data, *, package_id=None, expected_channel=None):
    bundle = json.loads(data.decode('utf-8'))
    _fields(bundle, _TOP, 'release')
    if type(bundle['schema_version']) is not int or bundle['schema_version'] != 2:
        raise NativeReleaseError('Unsupported native release schema')
    if not isinstance(bundle['package_id'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', bundle['package_id']):
        raise NativeReleaseError('Invalid release package ID')
    if package_id is not None and bundle['package_id'] != package_id:
        raise NativeReleaseError('Release package ID differs from selected package')
    identity = identity_key(bundle)
    if expected_channel is not None and bundle['channel'] != expected_channel:
        raise NativeReleaseError('Release channel differs from requested channel')
    published = bundle['published_at']
    if not isinstance(published, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', published, re.ASCII):
        raise NativeReleaseError('Release timestamp must be UTC RFC3339')
    datetime.strptime(published, '%Y-%m-%dT%H:%M:%SZ')
    _fields(bundle['core'], _ARTIFACT | {'version'}, 'core')
    _fields(bundle['gamepack'], _PACK, 'gamepack')
    if not isinstance(bundle['wheels'], list):
        raise NativeReleaseError('Dependency wheels must be a list')
    for wheel in bundle['wheels']:
        _fields(wheel, _ARTIFACT, 'dependency wheel')
    pack = bundle['gamepack']
    for key in ('package_id', 'version', 'channel', 'revision'):
        if pack[key] != bundle[key] or type(pack[key]) is not type(bundle[key]):
            raise NativeReleaseError('Gamepack identity differs from paired release')
    core = bundle['core']
    base = '.'.join(str(part) for part in identity[:3])
    suffix = '' if bundle['channel'] == 'stable' else ('a' if bundle['channel'] == 'alpha' else 'b') + str(bundle['revision'])
    if core['version'] != base + suffix or core_version_key(core['version']) != identity:
        raise NativeReleaseError('Core version differs from paired release identity')
    if core_version_key(pack['required_core_version']) > identity:
        raise NativeReleaseError('Paired core does not satisfy required_core_version')
    for artifact in artifacts(bundle):
        _artifact(artifact, bundle)
    paths = [artifact['path'].casefold() for artifact in artifacts(bundle)]
    if len(paths) != len(set(paths)):
        raise NativeReleaseError('Duplicate artifact paths')
    if not pack['path'].endswith('.zip') or any(not item['path'].endswith('.whl') for item in (core, *bundle['wheels'])):
        raise NativeReleaseError('Release artifact type differs from its role')
    return bundle


def artifact_path(root, artifact):
    root = Path(root).resolve()
    path = root.joinpath(*PurePosixPath(artifact['path']).parts).resolve()
    if not path.is_relative_to(root):
        raise NativeReleaseError('Local artifact escapes its verified root')
    return path


def verify_artifact(path, artifact):
    if path.stat().st_size != artifact['size']:
        raise NativeReleaseError('Artifact size differs from release')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != artifact['sha256']:
        raise NativeReleaseError('Artifact SHA256 differs from release')


def _wheel_metadata(path):
    with zipfile.ZipFile(path) as wheel:
        names = []
        for member in wheel.infolist():
            _relative_path(member.filename.rstrip('/'))
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise NativeReleaseError('Wheel contains a symlink')
            names.append(member.filename.casefold())
        if len(names) != len(set(names)):
            raise NativeReleaseError('Wheel contains duplicate paths')
        metadata = [name for name in wheel.namelist()
                    if len(name.split('/')) == 2 and name.endswith('.dist-info/METADATA')]
        if len(metadata) != 1:
            raise NativeReleaseError('Wheel must contain one distribution metadata file')
        info = BytesParser().parsebytes(wheel.read(metadata[0]))
        wheel_info = BytesParser().parsebytes(wheel.read(metadata[0].rsplit('/', 1)[0] + '/WHEEL'))
        name, version = info.get('Name'), info.get('Version')
        if (not name or not version or wheel_info.get('Wheel-Version') != '1.0'
                or wheel_info.get('Root-Is-Purelib') not in ('true', 'false') or not wheel_info.get_all('Tag')):
            raise NativeReleaseError('Unsupported or incomplete wheel metadata')
        filename = path.name[:-4].split('-')
        normalize = lambda text: re.sub(r'[-_.]+', '-', text).lower()
        if len(filename) not in (5, 6) or normalize(filename[0]) != normalize(name) or filename[1] != version:
            raise NativeReleaseError('Wheel filename differs from distribution metadata')
        return normalize(name), version


def validate_artifacts(bundle, artifact_root):
    """Validate a parsed bundle against local bytes, without loading its code."""
    for artifact in artifacts(bundle):
        verify_artifact(artifact_path(artifact_root, artifact), artifact)
    core_name, core_version = _wheel_metadata(artifact_path(artifact_root, bundle['core']))
    if core_name != 'gameframe-runtime' or core_version != bundle['core']['version']:
        raise NativeReleaseError('Core wheel metadata differs from paired core')
    names = {core_name}
    for artifact in bundle['wheels']:
        name, _ = _wheel_metadata(artifact_path(artifact_root, artifact))
        if name in names:
            raise NativeReleaseError('Ambiguous duplicate distribution in paired wheelhouse')
        names.add(name)
    with tempfile.TemporaryDirectory(prefix='native-release-verify-') as directory:
        staging = Path(directory).resolve()
        extract_zip(artifact_path(artifact_root, bundle['gamepack']), staging)
        roots = list(staging.iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            raise NativeReleaseError('Gamepack must contain one package directory')
        root = roots[0]
        verify_index(root, required=True)
        manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        if manifest['id'] != bundle['package_id']:
            raise NativeReleaseError('ZIP package ID differs from paired release')
        for key in ('version', 'channel', 'revision', 'required_core_version'):
            expected = bundle['gamepack'][key]
            if manifest[key] != expected or type(manifest[key]) is not type(expected):
                raise NativeReleaseError('ZIP identity/core requirement differs from paired release')
