"""Launcher choices scoped to the current user's explicitly selected local root."""

import json
from pathlib import Path

from gameframe.launcher_options import save_options


def local_root(value):
    text = str(value)
    if text.startswith(('\\\\', '//')):
        raise ValueError('Choose a local data directory')
    path = Path(value)
    if not path.is_absolute():
        raise ValueError('Data directory must be absolute')
    return path.resolve()


def load_context(path):
    path = Path(path)
    if not path.exists():
        return {'selected_package': None, 'restore_services': True}
    value = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or type(value.get('restore_services')) is not bool
            or (value.get('selected_package') is not None and not isinstance(value['selected_package'], str))):
        raise ValueError('Invalid launcher context')
    if 'data_root' in value:
        value['data_root'] = str(local_root(value['data_root']))
    if 'window_geometry' in value and not isinstance(value['window_geometry'], str):
        raise ValueError('Invalid window geometry')
    return value


def save_context(path, value):
    save_options(path, value)
