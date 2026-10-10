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


@dataclass(frozen=True)
class TaskDefinition:
    id: str
    title: str
    kind: str
    default_config: dict[str, Any]
    required_capabilities: frozenset[str]


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

    @classmethod
    def read(cls, directory: Path | str) -> PackageManifest:
        root = Path(directory).resolve()
        value = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        if value['api_version'] != API_VERSION:
            raise ValueError(f'Unsupported package API: {value["api_version"]}')
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', value['id']):
            raise ValueError('Invalid package ID')
        entry, symbol = value['entrypoint'].split(':', 1)
        path = (root / entry).resolve()
        if not path.is_relative_to(root) or not path.is_file() or not symbol.isidentifier():
            raise ValueError('Package entrypoint must be a Python file inside the package')
        tasks = tuple(TaskDefinition(
            item['id'], item['title'], item['kind'], item.get('default_config', {}),
            frozenset(item.get('required_capabilities', []))) for item in value['tasks'])
        if len({task.id for task in tasks}) != len(tasks):
            raise ValueError('Duplicate task ID')
        if any(task.kind not in {'one-shot', 'service', 'application'} for task in tasks):
            raise ValueError('Unknown task kind')
        if any(not isinstance(task.default_config, dict) for task in tasks):
            raise ValueError('Task default_config must be an object')
        execution = value.get('execution', 'native')
        if execution not in {'native', 'legacy-application'}:
            raise ValueError('Unknown package execution mode')
        return cls(root, value['id'], value.get('title', value['id']), value['version'],
                   value['entrypoint'], value['license'], tuple(value['platforms']),
                   execution, tasks)

    def task(self, task_id: str) -> TaskDefinition:
        for task in self.tasks:
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


def install_archive(archive_path: Path | str, directory: Path | str) -> PackageManifest:
    """Install a gamepack ZIP atomically, without replacing existing package data."""
    destination = Path(directory).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.gameframe-install-', dir=destination) as temporary:
        staging = Path(temporary)
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
        roots = list(staging.iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            raise ValueError('A gamepack ZIP must contain one package directory')
        manifest = PackageManifest.read(roots[0])
        index = roots[0] / 'files.json'
        if index.is_file():
            expected = json.loads(index.read_text(encoding='utf-8'))
            actual = {path.relative_to(roots[0]).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in roots[0].rglob('*') if path.is_file() and path != index}
            if actual != expected:
                raise ValueError('Gamepack content does not match its SHA256 index')
        installed = destination / manifest.id
        if installed.exists():
            raise FileExistsError(f'Package already installed: {installed}')
        roots[0].rename(installed)
    return PackageManifest.read(installed)
