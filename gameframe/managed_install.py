# SPDX-License-Identifier: MIT
"""One explicitly managed core/native-pack pair, prepared entirely offline."""
from contextlib import contextmanager, ExitStack
from email.parser import BytesParser
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile

from gameframe.process_locks import _file_lease
from gameframe.core_release_version import release_key


def atomic_json(path, value):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.name, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def initialize(root, *, bootstrap_pythonw, base_python, data_dir):
    """Explicit first installation; stable interpreter is supplied by distributor."""
    if not Path(root).is_absolute() or not Path(data_dir).is_absolute():
        raise ValueError('Managed root and user data must be explicit absolute paths')
    root, data_dir = Path(root).resolve(), Path(data_dir).resolve()
    pythonw = Path(bootstrap_pythonw)
    if not pythonw.is_absolute() or not pythonw.is_file() or pythonw.name.lower() != 'pythonw.exe':
        raise ValueError('An existing absolute stable bootstrap pythonw is required')
    pythonw = pythonw.resolve()
    base_python = Path(base_python)
    if (not base_python.is_absolute() or not base_python.is_file()
            or base_python.name.lower() != 'python.exe'):
        raise ValueError('An existing absolute stable base python.exe is required')
    base_python = base_python.resolve()
    if pythonw.is_relative_to(root / 'versions'):
        raise ValueError('Bootstrap interpreter must live outside versioned environments')
    if base_python.is_relative_to(root / 'versions'):
        raise ValueError('Base interpreter must live outside versioned environments')
    if data_dir.is_relative_to(root / 'versions'):
        raise ValueError('User data must live outside versioned environments')
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'installation.json').exists():
        raise FileExistsError('Managed installation already initialized')
    shutil.copyfile(Path(__file__).with_name('managed_bootstrap.py'), root / 'bootstrap.py')
    value = {'managed_root': str(root), 'bootstrap_pythonw': str(pythonw),
             'base_python': str(base_python), 'data_dir': str(data_dir)}
    atomic_json(root / 'installation.json', value)
    return [str(pythonw), str(root / 'bootstrap.py'), '--managed-root', str(root)]


def artifact_path(root, item):
    relative = item['path']
    if (not isinstance(relative, str) or Path(relative).is_absolute() or '\\' in relative
            or ':' in relative or '..' in Path(relative).parts or relative in ('', '.')):
        raise ValueError('Artifact must be a relative path inside release root')
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Artifact is not a local release file')
    verify_artifact(path, item)
    return path


def verify_artifact(path, item):
    if type(item['size']) is not int or item['size'] <= 0 or path.stat().st_size != item['size']:
        raise ValueError('Release artifact size mismatch')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != item['sha256']:
        raise ValueError('Release artifact SHA256 mismatch')


def _check_bundle(bundle, core):
    if bundle['schema_version'] != 2:
        raise ValueError('Managed install requires a verified schema2 bundle')
    pack = bundle['gamepack']
    if any(pack[key] != bundle[key] for key in ('package_id', 'version', 'channel', 'revision')):
        raise ValueError('Bundle and gamepack release identities differ')
    with zipfile.ZipFile(core) as wheel:
        metadata = [name for name in wheel.namelist() if name.endswith('.dist-info/METADATA')]
        if len(metadata) != 1:
            raise ValueError('Core wheel requires one distribution metadata record')
        value = BytesParser().parsebytes(wheel.read(metadata[0]))
    if (value['Name'].replace('_', '-').lower() != 'gameframe-runtime'
            or value['Version'] != bundle['core']['version']):
        raise ValueError('Core wheel identity differs from release bundle')


PREFLIGHT = r'''
import importlib.metadata, json, sys
from pathlib import Path
from gameframe.packages import install_archive, verify_index
import gameframe.gui, gameframe.worker, gameframe.package_process
bundle = json.loads(sys.argv[1])
environment = Path(sys.argv[2]).resolve()
if importlib.metadata.version('gameframe-runtime') != bundle['core']['version']:
    raise ValueError('Installed core version differs from bundle')
import gameframe
if not Path(gameframe.__file__).resolve().is_relative_to(environment):
    raise ValueError('Core preflight imported outside candidate environment')
manifest = install_archive(sys.argv[3], environment / 'gamepacks')
verify_index(manifest.root, required=True)
value = json.loads((manifest.root / 'manifest.json').read_text(encoding='utf-8'))
expected = bundle['gamepack']
for key in ('version', 'channel', 'revision', 'required_core_version'):
    if value[key] != expected[key]:
        raise ValueError('Installed gamepack identity differs from bundle: ' + key)
if manifest.id != bundle['package_id']:
    raise ValueError('Installed package ID differs from bundle')
print('managed-preflight-ok')
'''


def archive_requirements(archive, package_id):
    """Only pinned named requirements may enter the verified offline resolver."""
    requirements = []
    with zipfile.ZipFile(archive) as package:
        for filename in ('requirements.txt', 'requirements-management.txt'):
            text = package.read(package_id + '/' + filename).decode('utf-8-sig')
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9][A-Za-z0-9.!+_-]*(?:\s*;\s*[^\r\n]+)?', line):
                    raise ValueError('Unsupported offline requirement in ' + filename + ': ' + line)
                requirements.append(line)
    return requirements


def prepare_environment(root, artifact_root, bundle, *, base_python, automatic=False,
                        run=subprocess.run, lease=_file_lease):
    """Build a new environment; publish pending only after checked preflight succeeds."""
    root, artifact_root = Path(root).resolve(), Path(artifact_root).resolve()
    installation = json.loads((root / 'installation.json').read_text(encoding='utf-8'))
    if installation['managed_root'] != str(root):
        raise ValueError('Managed installation root changed')
    if type(automatic) is not bool:
        raise TypeError('Automatic update intent must be a boolean')
    base_python = Path(base_python)
    if not base_python.is_absolute() or not base_python.is_file() or base_python.resolve().is_relative_to(root / 'versions'):
        raise ValueError('An absolute base interpreter outside managed versions is required')
    if str(base_python.resolve()) != installation['base_python']:
        raise ValueError('Base interpreter differs from explicit managed installation')
    core = artifact_path(artifact_root, bundle['core'])
    pack = artifact_path(artifact_root, bundle['gamepack'])
    _check_bundle(bundle, core)
    wheels = [(core, bundle['core'])] + [(artifact_path(artifact_root, item), item) for item in bundle['wheels']]
    if any(path.suffix != '.whl' for path, _ in wheels) or len({path.name for path, _ in wheels}) != len(wheels):
        raise ValueError('Wheelhouse must contain distinct wheel artifacts')
    environment = root / 'versions' / uuid.uuid4().hex
    environment.parent.mkdir(parents=True, exist_ok=True)
    published = False
    try:
        # The directory is never renamed: installed scripts may contain absolute paths.
        run([str(base_python), '-I', '-m', 'venv', str(environment)], check=True)
        wheelhouse = environment / 'wheelhouse'
        wheelhouse.mkdir()
        for path, item in wheels:
            destination = wheelhouse / path.name
            shutil.copyfile(path, destination)
            verify_artifact(destination, item)
        archive = environment / 'gamepack.zip'
        shutil.copyfile(pack, archive)
        verify_artifact(archive, bundle['gamepack'])
        requirements = archive_requirements(archive, bundle['package_id'])
        python = environment / 'Scripts/python.exe'
        process_environment = dict(os.environ)
        process_environment.pop('PYTHONPATH', None)
        # pip's documented devnull config skips global/user/site find-links; isolated ignores PIP_* options.
        process_environment['PIP_CONFIG_FILE'] = os.devnull
        run([str(python), '-I', '-m', 'pip', '--isolated', 'install', '--no-index', '--no-cache-dir', '--only-binary=:all:',
             '--find-links', str(wheelhouse), *[str(wheelhouse / path.name) for path, _ in wheels],
             *requirements, 'gameframe-runtime[gui,windows]==' + bundle['core']['version']],
            cwd=environment, env=process_environment, check=True)
        # Resolver sees only verified wheels, including core GUI/Windows extras; never use another source.
        run([str(python), '-I', '-m', 'pip', '--isolated', 'check'],
            cwd=environment, env=process_environment, check=True)
        result = run([str(python), '-I', '-B', '-c', PREFLIGHT,
                      json.dumps(bundle), str(environment), str(archive)],
                     cwd=environment, env=process_environment, check=True, capture_output=True, text=True)
        if result.stdout.strip() != 'managed-preflight-ok':
            raise ValueError('Candidate did not complete the required offline preflight')
        receipt = {'status': 'ready', 'bundle': bundle}
        atomic_json(environment / 'ready.json', receipt)
        pointer = {'environment': environment.relative_to(root).as_posix(), 'bundle': bundle,
                   'receipt_sha256': hashlib.sha256((environment / 'ready.json').read_bytes()).hexdigest(),
                   'automatic': automatic}
        with lease(root / '.leases/switch.lock', True):
            incoming_key = release_key(bundle['core']['version'])
            for name in ('active.json', 'pending.json'):
                existing_path = root / name
                if not existing_path.exists():
                    continue
                existing_bundle = json.loads(existing_path.read_text(encoding='utf-8'))['bundle']
                existing_key = release_key(existing_bundle['core']['version'])
                if incoming_key < existing_key:
                    raise ValueError('Candidate would replace a newer managed release')
                if incoming_key == existing_key:
                    if bundle != existing_bundle:
                        raise ValueError('Managed release identity has conflicting content')
                    if name == 'pending.json':
                        raise FileExistsError('This managed release is already pending')
            atomic_json(root / 'pending.json', pointer)
            published = True
        return pointer
    except BaseException:
        if not published and environment.exists():
            if not environment.resolve().is_relative_to(root / 'versions'):
                raise ValueError('Refusing to remove a candidate outside managed versions')
            shutil.rmtree(environment)
        raise


@contextmanager
def managed_owner(root, *, environment, lease=_file_lease):
    """Explicit GUI/worker/config/management/overview hook; no directory guessing."""
    root = Path(root).resolve()
    with ExitStack() as lifetime:
        with lease(root / '.leases/switch.lock', True):
            active = json.loads((root / 'active.json').read_text(encoding='utf-8'))
            expected = (root / active['environment']).resolve()
            if expected.parent != root / 'versions' or Path(environment).resolve() != expected:
                raise RuntimeError('Owner interpreter is no longer the active managed environment')
            lifetime.enter_context(lease(root / '.leases/environment.lock', False))
        yield


@contextmanager
def managed_entry(root=None):
    """Explicit CLI/env ownership, propagated to children for this entry's lifetime."""
    selected = root if root is not None else os.environ.get('GAMEFRAME_MANAGED_ROOT')
    if selected is None:
        yield None
        return
    root = Path(selected)
    if not root.is_absolute():
        raise ValueError('Managed installation root must be absolute')
    root = root.resolve()
    previous = os.environ.get('GAMEFRAME_MANAGED_ROOT')
    with managed_owner(root, environment=sys.prefix):
        os.environ['GAMEFRAME_MANAGED_ROOT'] = str(root)
        try:
            yield root
        finally:
            if previous is None:
                os.environ.pop('GAMEFRAME_MANAGED_ROOT', None)
            else:
                os.environ['GAMEFRAME_MANAGED_ROOT'] = previous


def set_update_policy(root, policy, *, lease=_file_lease):
    if policy not in ('MANUAL_UPDATE', 'AUTO_UPDATE', 'AUTO_UPDATE_PRE_RELEASE'):
        raise ValueError('Unknown managed update policy')
    root = Path(root).resolve()
    installation = json.loads((root / 'installation.json').read_text(encoding='utf-8'))
    if installation['managed_root'] != str(root):
        raise ValueError('Managed installation root changed')
    with lease(root / '.leases/switch.lock', True):
        atomic_json(root / 'update-policy.json', {'policy': policy})


def request_pending_retry(root, *, lease=_file_lease):
    """Explicit user retry clears a prior failure marker without touching active/data."""
    root = Path(root).resolve()
    installation = json.loads((root / 'installation.json').read_text(encoding='utf-8'))
    if installation['managed_root'] != str(root):
        raise ValueError('Managed installation root changed')
    with lease(root / '.leases/switch.lock', True):
        (root / 'last-update-error.json').unlink(missing_ok=True)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    initial = commands.add_parser('initialize')
    initial.add_argument('--managed-root', type=Path, required=True)
    initial.add_argument('--bootstrap-pythonw', type=Path, required=True)
    initial.add_argument('--base-python', type=Path, required=True)
    initial.add_argument('--data-dir', type=Path, required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--managed-root', type=Path, required=True)
    prepare.add_argument('--artifact-root', type=Path, required=True)
    prepare.add_argument('--bundle', type=Path, required=True)
    prepare.add_argument('--automatic', action='store_true')
    retry = commands.add_parser('retry')
    retry.add_argument('--managed-root', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'initialize':
        entry = initialize(args.managed_root, bootstrap_pythonw=args.bootstrap_pythonw,
                           base_python=args.base_python, data_dir=args.data_dir)
        print(json.dumps({'bootstrap_argv': entry}, ensure_ascii=False))
    elif args.command == 'prepare':
        installation = json.loads((args.managed_root / 'installation.json').read_text(encoding='utf-8'))
        bundle = json.loads(args.bundle.read_text(encoding='utf-8'))
        pointer = prepare_environment(args.managed_root, args.artifact_root, bundle,
                                      base_python=installation['base_python'], automatic=args.automatic)
        print(json.dumps({'status': 'pending', 'environment': pointer['environment']}, ensure_ascii=False))
    else:
        request_pending_retry(args.managed_root)
        print(json.dumps({'status': 'retry-requested'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
