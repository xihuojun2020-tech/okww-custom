"""Explicit-path, headless configuration for native Wuthering Waves tasks."""

import json
import os
import tempfile
from pathlib import Path


class ConfigOption:
    def __init__(self, name, default=None, description='', config_description=None,
                 config_type=None, validator=None, icon=None, show_at_tab=False):
        self.name = name
        self.description = description
        self.default_config = default or {}
        self.config_description = config_description or {}
        self.config_type = config_type
        self.validator = validator
        self.icon = icon
        self.show_at_tab = show_at_tab


class Config(dict):
    # NativeTask binds this to data_dir/configs before importing production combat.
    config_folder = None

    def __init__(self, name, default, folder=None, validator=None):
        folder = folder if folder is not None else self.config_folder
        if folder is None:
            raise RuntimeError('Native config folder must be bound before task import')
        folder = Path(folder)
        if not folder.is_absolute():
            raise ValueError('Native config folder must be an absolute path')
        self.config_file = folder / f'{name}.json'
        self.default = default
        self.validator = validator
        self.on_change = None
        if self.config_file.exists():
            with self.config_file.open('r', encoding='utf-8') as stream:
                current = json.load(stream)
            if not isinstance(current, dict):
                raise ValueError(f'Config must contain a JSON object: {self.config_file}')
            if self.verify_config(current, default):
                self.save_file()
        else:
            self.reset_to_default()

    def save_file(self):
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8',
                                             dir=self.config_file.parent,
                                             prefix=f'.{self.config_file.name}.',
                                             suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(self, stream, indent=4, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.config_file)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def get_default(self, key):
        return self.default.get(key)

    def reset_to_default(self):
        dict.clear(self)
        dict.update(self, self.default)
        self.save_file()

    def pop(self, key, default=None):
        value = dict.pop(self, key, default)
        self.save_file()
        return value

    def popitem(self):
        value = dict.popitem(self)
        self.save_file()
        return value

    def clear(self):
        dict.clear(self)
        self.save_file()

    def __setitem__(self, key, value):
        if self.validator is not None:
            valid, message = self.validator(key, value)
            if not valid:
                raise ValueError(message)
        if key not in self or value != self[key]:
            dict.__setitem__(self, key, value)
            self.save_file()
            if self.on_change is not None:
                self.on_change(key, value)

    def update(self, *args, **kwargs):
        incoming = dict(*args, **kwargs)
        if self.validator is not None:
            for key, value in incoming.items():
                valid, message = self.validator(key, value)
                if not valid:
                    raise ValueError(message)
        changed = {key: value for key, value in incoming.items()
                   if key not in self or value != self[key]}
        if changed:
            dict.update(self, changed)
            self.save_file()
            if self.on_change is not None:
                for key, value in changed.items():
                    self.on_change(key, value)

    def has_user_config(self):
        return not all(key.startswith('_') for key in self)

    def verify_config(self, current, default_config):
        modified = any(key not in default_config for key in current)
        verified = {}
        for key, fallback in default_config.items():
            value = current.get(key)
            if key not in current or not isinstance(value, type(fallback)):
                value = fallback
                modified = True
            elif self.validator is not None:
                valid, _ = self.validator(key, value)
                if not valid:
                    value = fallback
                    modified = True
            verified[key] = value
        dict.clear(self)
        dict.update(self, verified)
        return modified
