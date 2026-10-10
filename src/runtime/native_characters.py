# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixed-name native character sources and explicit owner snapshots."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from src.account_change_lock import get_account_change_lock


class CharacterConflict(RuntimeError):
    pass


class CharacterValidationError(ValueError):
    pass


def _digest(value):
    return hashlib.sha256(value).hexdigest()


class NativeCharacterService:
    def __init__(self, data_dir):
        from src.runtime import combat_api
        self.data_dir = Path(data_dir).resolve()
        combat_api.configure(native=True, data_dir=self.data_dir)
        from src.char.CharFactory import char_dict
        self.registered = {info['cls'].__name__: info for info in char_dict.values()}
        self.root = self.data_dir / 'configs/custom_chars'
        self.modes_path = self.root / 'custom_chars.json'
        self._lock = get_account_change_lock(self.root)
        self.revision = None

    def _path(self, path):
        resolved = path.resolve()
        if not resolved.is_relative_to(self.data_dir) or not resolved.is_relative_to(self.root):
            raise ValueError('角色源码路径超出配置目录')
        return resolved

    def _class(self, class_name):
        if not isinstance(class_name, str) or class_name not in self.registered:
            raise ValueError('角色必须是安装包注册的精确类名')
        return self.registered[class_name]['cls']

    def _source_path(self, class_name):
        self._class(class_name)
        return self._path(self.root / (class_name + '.py'))

    def _state(self):
        modes_path = self._path(self.modes_path)
        modes = json.loads(modes_path.read_text(encoding='utf-8')) if modes_path.exists() else {}
        if (not isinstance(modes, dict) or any(not isinstance(name, str)
                or not isinstance(row, dict) or type(row.get('use_custom', False)) is not bool
                for name, row in modes.items())):
            raise ValueError('角色模式必须是包含布尔use_custom的JSON对象')
        sources = {}
        for name in self.registered:
            path = self._source_path(name)
            sources[name] = path.read_bytes() if path.exists() else None
        encoded = json.dumps({'modes': modes, 'sources': {name: _digest(code) if code is not None else None
            for name, code in sources.items()}}, sort_keys=True, ensure_ascii=False,
            separators=(',', ':'), allow_nan=False).encode('utf-8')
        self.revision = _digest(encoded)
        return modes, sources

    def _row(self, name, modes, sources):
        from src.char.CustomCharLoader import read_builtin_char_code
        from src.char.character_names import character_display_name
        char_cls = self._class(name)
        source = sources[name]
        return {'class_name': name, 'display_name': character_display_name(char_cls),
            'builtin_code': read_builtin_char_code(char_cls),
            'custom_code': source.decode('utf-8') if source is not None else None,
            'has_custom': source is not None, 'use_custom': modes.get(name, {}).get('use_custom', False),
            'source_revision': _digest(source) if source is not None else None,
            'saved_revision': self.revision}

    def list(self):
        from src.char.character_names import character_display_name
        with self._lock:
            modes, sources = self._state()
            rows = [{'class_name': name, 'display_name': character_display_name(info['cls']),
                'has_custom': sources[name] is not None,
                'use_custom': modes.get(name, {}).get('use_custom', False),
                'source_revision': _digest(sources[name]) if sources[name] is not None else None}
                for name, info in self.registered.items()]
            rows.sort(key=lambda row: (not row['has_custom'], row['class_name'].lower()))
            return {'characters': rows, 'saved_revision': self.revision}

    def read(self, class_name):
        self._class(class_name)
        with self._lock:
            modes, sources = self._state()
            return self._row(class_name, modes, sources)

    def _check_revision(self, expected):
        if expected is None or expected != self.revision:
            raise CharacterConflict('角色源码或模式已被其他编辑修改，请重新读取')

    def _validate(self, class_name, code):
        import gameframe
        with tempfile.TemporaryDirectory(prefix='okww-character-validation-') as directory:
            temporary = Path(directory)
            source = temporary / 'candidate.py'
            source.write_text(code, encoding='utf-8', newline='')
            result_file = temporary / 'result.json'
            config_dir = self.data_dir / 'configs'
            with get_account_change_lock(config_dir):
                if config_dir.is_dir():
                    shutil.copytree(config_dir, temporary / 'data/configs')
            process = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8',
                str(Path(__file__).with_name('native_character_validation.py')),
                '--core-root', str(Path(gameframe.__file__).resolve().parent.parent),
                '--code-path', str(source), '--data-dir', str(temporary / 'data'),
                '--result', str(result_file), '--class-name', class_name],
                cwd=temporary, capture_output=True, text=True, encoding='utf-8', timeout=30)
            if not result_file.exists():
                raise CharacterValidationError(f'角色验证进程退出（{process.returncode}）：{process.stderr.strip()}')
            result = json.loads(result_file.read_text(encoding='utf-8'))
            if process.returncode != 0 or not result['ok']:
                raise CharacterValidationError(f'{result["type"]}: {result["error"]}')

    @staticmethod
    def _atomic_bytes(path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('wb', dir=path.parent, prefix='.' + path.name,
                                             suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _publish(self, class_name, source, modes):
        path = self._source_path(class_name)
        mode_path = self._path(self.modes_path)
        old_source = path.read_bytes() if path.exists() else None
        old_modes = mode_path.read_bytes() if mode_path.exists() else None
        try:
            if source is None:
                path.unlink(missing_ok=True)
            else:
                self._atomic_bytes(path, source)
            self._atomic_bytes(mode_path, json.dumps(modes, ensure_ascii=False, indent=2,
                                                     allow_nan=False).encode('utf-8'))
        except Exception:
            if old_source is None:
                path.unlink(missing_ok=True)
            else:
                self._atomic_bytes(path, old_source)
            current_modes = mode_path.read_bytes() if mode_path.exists() else None
            if current_modes != old_modes:
                if old_modes is None:
                    mode_path.unlink(missing_ok=True)
                else:
                    self._atomic_bytes(mode_path, old_modes)
            raise

    def save(self, class_name, code, *, expected_revision):
        from src.char.CustomCharLoader import read_builtin_char_code
        builtin = self._class(class_name)
        if not isinstance(code, str):
            raise TypeError('角色源码必须是字符串')
        with self._lock:
            self._state()
            self._check_revision(expected_revision)
        if code == read_builtin_char_code(builtin):
            return self.reset(class_name, expected_revision=expected_revision)
        compile(code, str(self._source_path(class_name)), 'exec')
        self._validate(class_name, code)
        with self._lock:
            modes, _ = self._state()
            self._check_revision(expected_revision)
            modes.setdefault(class_name, {})['use_custom'] = True
            self._publish(class_name, code.encode('utf-8'), modes)
            modes, sources = self._state()
            return self._row(class_name, modes, sources)

    def reset(self, class_name, *, expected_revision):
        self._class(class_name)
        with self._lock:
            modes, _ = self._state()
            self._check_revision(expected_revision)
            modes.setdefault(class_name, {})['use_custom'] = False
            self._publish(class_name, None, modes)
            modes, sources = self._state()
            return self._row(class_name, modes, sources)

    def set_mode(self, class_name, use_custom, *, expected_revision):
        self._class(class_name)
        if type(use_custom) is not bool:
            raise TypeError('角色模式必须是布尔值')
        with self._lock:
            modes, sources = self._state()
            self._check_revision(expected_revision)
            source = sources[class_name]
            if use_custom and source is None:
                raise ValueError('尚未保存自定义角色源码')
        if use_custom:
            self._validate(class_name, source.decode('utf-8'))
        with self._lock:
            modes, sources = self._state()
            self._check_revision(expected_revision)
            modes.setdefault(class_name, {})['use_custom'] = use_custom
            self._publish(class_name, sources[class_name], modes)
            modes, sources = self._state()
            return self._row(class_name, modes, sources)

    def load_snapshot(self):
        from src.char.CustomCharLoader import load_native_character_source
        with self._lock:
            modes, sources = self._state()
            revision = self.revision
        classes = {}
        source_revisions = {}
        for name, info in self.registered.items():
            source = sources[name]
            source_revisions[name] = _digest(source) if source is not None else None
            if modes.get(name, {}).get('use_custom', False):
                if source is None:
                    raise ValueError(f'已启用的自定义角色源码不存在：{name}')
                self._validate(name, source.decode('utf-8'))
                classes[info['cls']] = load_native_character_source(info['cls'], self._source_path(name), source)
            else:
                classes[info['cls']] = info['cls']
        return {'revision': revision, 'classes': classes, 'source_revisions': source_revisions}
