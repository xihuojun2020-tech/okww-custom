"""Read package metadata without importing game code or starting a device."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import re
import shutil
import sys
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gameframe import API_VERSION
from gameframe.core_release_version import require_core_version
from gameframe.process_locks import package_lease


@dataclass(frozen=True)
class TaskDefinition:
    id: str
    title: str
    kind: str
    default_config: dict[str, Any]
    required_capabilities: frozenset[str]
    visible: bool = True
    revision: str | None = None
    category: str = ''
    order: int = 0


@dataclass(frozen=True)
class PackageManifest:
    root: Path
    id: str
    title: str
    version: str
    entrypoint: str
    license: str
    platforms: tuple[str, ...]
    execution: str
    tasks: tuple[TaskDefinition, ...]
    supports_session: bool = False
    management: bool = False
    overview: bool = False
    task_catalog: str | None = None
    session_required_capabilities: frozenset[str] = frozenset()
    configuration: bool = False
    supports_managed_updates: bool = False
    channel: str = 'stable'
    revision: int = 0
    required_core_version: str | None = None

    @property
    def release_identity(self):
        return {'id': self.id, 'version': self.version, 'channel': self.channel,
                'revision': self.revision, 'required_core_version': self.required_core_version}

    def check_release_identity(self, expected):
        if self.release_identity != expected:
            raise ValueError('Gamepack release identity changed before the process started')

    @classmethod
    def read(cls, directory: Path | str) -> PackageManifest:
        root = Path(directory).resolve()
        value = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        if value['api_version'] != API_VERSION:
            raise ValueError(f'Unsupported package API: {value["api_version"]}')
        required_core = value.get('required_core_version')
        if required_core is not None:
            require_core_version(required_core)
        channel, revision = value.get('channel', 'stable'), value.get('revision', 0)
        if (channel not in ('stable', 'alpha', 'beta') or type(revision) is not int
                or (revision != 0 if channel == 'stable' else revision <= 0)):
            raise ValueError('Invalid gamepack release channel/revision')
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', value['id']):
            raise ValueError('Invalid package ID')
        entry, symbol = value['entrypoint'].split(':', 1)
        path = (root / entry).resolve()
        if not path.is_relative_to(root) or not path.is_file() or not symbol.isidentifier():
            raise ValueError('Package entrypoint must be a Python file inside the package')
        tasks = tuple(TaskDefinition(
            item['id'], item['title'], item['kind'], item.get('default_config', {}),
            frozenset(item.get('required_capabilities', [])), item.get('visible', True),
            item.get('revision'), item.get('category', ''), item.get('order', 0)) for item in value['tasks'])
        if any('revision' in item and (not isinstance(item['revision'], str) or not item['revision'])
               for item in value['tasks']):
            raise ValueError('Task revision must be a nonempty string')
        if len({task.id for task in tasks}) != len(tasks):
            raise ValueError('Duplicate task ID')
        if any(task.kind not in {'one-shot', 'service', 'application'} for task in tasks):
            raise ValueError('Unknown task kind')
        if any(not isinstance(task.default_config, dict) for task in tasks):
            raise ValueError('Task default_config must be an object')
        if any(not isinstance(task.visible, bool) for task in tasks):
            raise ValueError('Task visible must be a boolean')
        if any(not isinstance(task.category, str) or type(task.order) is not int for task in tasks):
            raise ValueError('Task category must be text and order an integer')
        execution = value.get('execution', 'native')
        if execution not in {'native', 'legacy-application'}:
            raise ValueError('Unknown package execution mode')
        for name in ('supports_session', 'management', 'overview', 'configuration', 'supports_managed_updates'):
            if not isinstance(value.get(name, False), bool):
                raise ValueError(f'Package {name} must be a boolean')
        catalog = value.get('task_catalog')
        session_capabilities = value.get('session_required_capabilities', [])
        if (not isinstance(session_capabilities, list)
                or any(not isinstance(item, str) for item in session_capabilities)):
            raise ValueError('Session required capabilities must be a list of strings')
        if catalog is not None and (not isinstance(catalog, str) or not catalog
                or Path(catalog).anchor or Path(catalog) == Path('.') or '..' in Path(catalog).parts):
            raise ValueError('Task catalog must be a relative path inside the data directory')
        return cls(root, value['id'], value.get('title', value['id']), value['version'],
                   value['entrypoint'], value['license'], tuple(value['platforms']),
                   execution, tasks, value.get('supports_session', False),
                   value.get('management', False), value.get('overview', False), catalog,
                   frozenset(session_capabilities), value.get('configuration', False),
                   value.get('supports_managed_updates', False), channel, revision, required_core)

    def available_tasks(self, data_dir=None) -> tuple[TaskDefinition, ...]:
        if self.task_catalog is None or data_dir is None:
            return self.tasks
        root = Path(data_dir).resolve()
        path = (root / self.task_catalog).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError('Task catalog escapes the data directory')
        if not path.exists():
            return self.tasks
        catalog = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(catalog, dict) or type(catalog.get('api_version')) is not int
                or catalog['api_version'] != 1 or not isinstance(catalog.get('revision'), str) or not catalog['revision']
                or not isinstance(catalog.get('tasks'), list)):
            raise ValueError('Invalid task catalog metadata')
        tasks = list(self.tasks)
        ids = {task.id for task in tasks}
        for item in catalog['tasks']:
            if (not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id']
                    or not isinstance(item.get('title'), str) or not item['title']
                    or not isinstance(item.get('kind'), str) or item['kind'] not in {'one-shot', 'service', 'application'}
                    or not isinstance(item.get('default_config', {}), dict)
                    or not isinstance(item.get('required_capabilities', []), list)
                    or any(not isinstance(capability, str) for capability in item.get('required_capabilities', []))
                    or type(item.get('visible', True)) is not bool
                    or not isinstance(item.get('category', ''), str) or type(item.get('order', 0)) is not int
                    or ('revision' in item and (not isinstance(item['revision'], str) or not item['revision']))):
                raise ValueError('Invalid task catalog task definition')
            if item['id'] in ids:
                raise ValueError('Duplicate or shadowed task ID in catalog')
            ids.add(item['id'])
            tasks.append(TaskDefinition(item['id'], item['title'], item['kind'], item.get('default_config', {}),
                                        frozenset(item.get('required_capabilities', [])), item.get('visible', True),
                                        item.get('revision'), item.get('category', ''), item.get('order', 0)))
        return tuple(tasks)

    def task(self, task_id: str, data_dir=None) -> TaskDefinition:
        for task in self.available_tasks(data_dir):
            if task.id == task_id:
                return task
        raise KeyError(f'Unknown task {task_id!r} in {self.id}')

    def load(self):
        file, symbol = self.entrypoint.split(':', 1)
        name = f'_gameframe_package_{uuid.uuid4().hex}'
        spec = importlib.util.spec_from_file_location(name, self.root / file,
                                                     submodule_search_locations=[str(self.root)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
            return getattr(module, symbol)()
        except BaseException:
            sys.modules.pop(name, None)
            raise


def discover(directory: Path | str) -> tuple[PackageManifest, ...]:
    """An invalid installed package is an error, rather than silently disappearing."""
    root = Path(directory)
    if not root.exists():
        return ()
    return tuple(PackageManifest.read(path.parent)
                 for path in sorted(root.glob('*/manifest.json')))


def verify_index(root: Path, *, required=False):
    index = root / 'files.json'
    if not index.is_file():
        if required:
            raise ValueError('Gamepack update requires a SHA256 files.json index')
        return
    expected = json.loads(index.read_text(encoding='utf-8'))
    actual = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in root.rglob('*') if path.is_file() and path != index}
    if actual != expected:
        raise ValueError('Gamepack content does not match its SHA256 index')


def extract_zip(archive_path: Path | str, staging: Path) -> None:
    """Safely extract ZIP members without assuming an application format."""
    with zipfile.ZipFile(archive_path) as archive:
        names = set()
        for item in archive.infolist():
            name = item.filename
            target = (staging / name).resolve()
            if ('\\' in name or ':' in name or not target.is_relative_to(staging)
                    or (item.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError(f'Unsafe archive path: {name}')
            if name in names:
                raise ValueError(f'Duplicate archive path: {name}')
            names.add(name)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output)


def extract_archive(archive_path: Path | str, staging: Path, *, require_index=False) -> PackageManifest:
    """Extract and verify metadata/content without importing the package."""
    extract_zip(archive_path, staging)
    roots = list(staging.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise ValueError('A gamepack ZIP must contain one package directory')
    manifest = PackageManifest.read(roots[0])
    verify_index(roots[0], required=require_index)
    return manifest


def install_archive(archive_path: Path | str, directory: Path | str) -> PackageManifest:
    """Install a gamepack ZIP atomically, without replacing existing package data."""
    destination = Path(directory).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.gameframe-install-', dir=destination) as temporary:
        manifest = extract_archive(archive_path, Path(temporary))
        installed = destination / manifest.id
        with package_lease(installed, exclusive=True):
            if installed.exists():
                raise FileExistsError(f'Package already installed: {installed}')
            manifest.root.rename(installed)
            return PackageManifest.read(installed)
