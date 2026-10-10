"""Per-package launcher choices, outside the installed package's code."""

import json
import os
import tempfile
from pathlib import Path


def load_options(path):
    path = Path(path)
    if not path.exists():
        return {'tasks': {}, 'device': {'type': 'replay', 'frames': []}}
    value = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or not isinstance(value.get('tasks'), dict)
            or not isinstance(value.get('device'), dict)):
        raise ValueError(f'Invalid launcher options: {path}')
    return value


def save_options(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.name, suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
