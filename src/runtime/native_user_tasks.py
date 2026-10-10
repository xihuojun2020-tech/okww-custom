# SPDX-License-Identifier: AGPL-3.0-or-later
"""Immutable user task sources and one atomic, metadata-only catalog."""

from copy import deepcopy
import hashlib
import json
import keyword
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

from gameframe import API_VERSION
from src.account_change_lock import get_account_change_lock
from src.runtime.native_user_task_validation import load_export


class UserTaskConflict(RuntimeError):
    """A published catalog changed after the editor read it."""


class UserTaskValidationError(ValueError):
    """The isolated candidate failed; the catalog was not published."""


def _revision(tasks):
    encoded = json.dumps(tasks, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _source_id(value):
    return str(uuid.UUID(str(value)))


class NativeUserTaskStore:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).resolve()
        self.root = self.data_dir / 'user_tasks'
        self.catalog_path = self.root / 'catalog.json'
        self.revision = _revision([])
        self._lock = get_account_change_lock(self.root)

    def _inside_root(self, path):
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(self.data_dir) or not resolved.is_relative_to(self.root):
            raise ValueError('用户任务路径超出数据目录')
        return resolved

    def _catalog(self):
        self._inside_root(self.catalog_path)
        if not self.catalog_path.exists():
            result = {'api_version': API_VERSION, 'revision': _revision([]), 'tasks': []}
        else:
            result = json.loads(self.catalog_path.read_text(encoding='utf-8'))
            if (not isinstance(result, dict) or type(result.get('api_version')) is not int
                    or result['api_version'] != API_VERSION or not isinstance(result.get('tasks'), list)
                    or result.get('revision') != _revision(result['tasks'])):
                raise ValueError('用户任务目录元数据或revision无效')
            seen = set()
            for row in result['tasks']:
                source_id = _source_id(row['source_id'])
                if row['id'] != 'user:' + source_id or source_id in seen:
                    raise ValueError('用户任务稳定ID无效或重复')
                seen.add(source_id)
                self._code_path(source_id, row['source_revision'])
        self.revision = result['revision']
        return result

    def _code_path(self, source_id, revision):
        source_id = _source_id(source_id)
        if not isinstance(revision, str) or re.fullmatch('[0-9a-f]{64}', revision) is None:
            raise ValueError('用户任务源码revision无效')
        return self._inside_root(self.root / source_id / 'revisions' / revision / 'task.py')

    def list(self):
        return deepcopy(self._catalog()['tasks'])

    def read(self, source_id):
        catalog = self._catalog()
        source_id = _source_id(source_id)
        row = next((item for item in catalog['tasks'] if item['source_id'] == source_id), None)
        if row is None:
            raise UserTaskConflict('用户任务已不存在，请重新读取')
        code = self._read_code(row)
        return {**deepcopy(row), 'code': code, 'catalog_revision': catalog['revision']}

    def _read_code(self, row):
        payload = self._code_path(row['source_id'], row['source_revision']).read_bytes()
        if hashlib.sha256(payload).hexdigest() != row['source_revision']:
            raise ValueError('用户任务不可变源码已被修改，未加载')
        return payload.decode('utf-8')

    def _validate(self, code, class_name, source_id, source_revision):
        import gameframe
        with tempfile.TemporaryDirectory(prefix='okww-user-task-validation-') as directory:
            temporary = Path(directory)
            source = temporary / 'task.py'
            source.write_text(code, encoding='utf-8', newline='')
            result_file = temporary / 'result.json'
            config_dir = self.data_dir / 'configs'
            with get_account_change_lock(config_dir):
                if config_dir.is_dir():
                    shutil.copytree(config_dir, temporary / 'data/configs')
            process = subprocess.run([
                sys.executable, '-I', '-B', '-X', 'utf8',
                str(Path(__file__).with_name('native_user_task_validation.py')),
                '--core-root', str(Path(gameframe.__file__).resolve().parent.parent),
                '--code-path', str(source), '--data-dir', str(temporary / 'data'),
                '--result', str(result_file), '--class-name', class_name,
                '--source-id', source_id, '--source-revision', source_revision],
                cwd=temporary, capture_output=True, text=True, encoding='utf-8', timeout=30)
            if not result_file.exists():
                raise UserTaskValidationError(
                    f'验证进程退出（{process.returncode}）：{process.stderr.strip()}')
            result = json.loads(result_file.read_text(encoding='utf-8'))
            if process.returncode != 0 or not result['ok']:
                raise UserTaskValidationError(f'{result.get("type", "validation")}: {result["error"]}')
            return result['metadata']

    def _check_revision(self, catalog, expected_revision, *, editing):
        if editing and expected_revision is None:
            raise UserTaskConflict('编辑已有用户任务必须提供读取时的catalog revision')
        if expected_revision is not None and expected_revision != catalog['revision']:
            raise UserTaskConflict('用户任务目录已被其他编辑修改，请重新读取')

    def _publish(self, tasks):
        self._inside_root(self.catalog_path)
        catalog = {'api_version': API_VERSION, 'revision': _revision(tasks), 'tasks': tasks}
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.root,
                                             prefix='.catalog-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(catalog, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.catalog_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.revision = catalog['revision']
        return self.revision

    def save(self, code, class_name, *, source_id=None, expected_revision=None,
             required_capabilities=()):
        if not isinstance(code, str):
            raise TypeError('用户任务源码必须是字符串')
        if not isinstance(class_name, str) or not class_name.isidentifier() or keyword.iskeyword(class_name):
            raise ValueError('请输入精确导出类名')
        if (not isinstance(required_capabilities, (list, tuple, set, frozenset))
                or any(not isinstance(value, str) or not value for value in required_capabilities)):
            raise ValueError('required_capabilities必须是非空能力名称的列表')
        editing = source_id is not None
        source_id = _source_id(source_id) if editing else str(uuid.uuid4())
        source_revision = hashlib.sha256(code.encode('utf-8')).hexdigest()
        metadata = self._validate(code, class_name, source_id, source_revision)
        row = {'id': 'user:' + source_id, 'title': metadata['name'], 'kind': metadata['kind'],
               # Native task defaults belong to persisted Config, not the
               # generic Runtime overrides passed to primary after_init.
               'default_config': {},
               'required_capabilities': sorted(set(required_capabilities)),
               'visible': metadata['visible'], 'source_id': source_id,
               'source_revision': source_revision, 'class_name': class_name, 'metadata': metadata}
        # Bind the executable class, capabilities and metadata, not only code
        # bytes: two exports from the same source can be different tasks.
        row['revision'] = _revision([row])
        with self._lock:
            catalog = self._catalog()
            self._check_revision(catalog, expected_revision, editing=editing)
            rows = catalog['tasks']
            index = next((index for index, item in enumerate(rows) if item['source_id'] == source_id), None)
            if editing and index is None:
                raise UserTaskConflict('用户任务已被删除，请重新读取')
            target = self._code_path(source_id, source_revision)
            if target.exists():
                if target.read_bytes() != code.encode('utf-8'):
                    raise ValueError('用户任务不可变源码revision内容已改变')
            else:
                target.parent.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='.candidate-', dir=target.parent.parent) as directory:
                    candidate = Path(directory)
                    with (candidate / 'task.py').open('wb') as stream:
                        stream.write(code.encode('utf-8'))
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(candidate, target.parent)
            if index is None:
                rows.append(row)
            else:
                rows[index] = row
            revision = self._publish(rows)
        return {**deepcopy(row), 'code': code, 'catalog_revision': revision}

    def delete(self, source_id, *, expected_revision):
        source_id = _source_id(source_id)
        with self._lock:
            catalog = self._catalog()
            self._check_revision(catalog, expected_revision, editing=True)
            rows = catalog['tasks']
            index = next((index for index, row in enumerate(rows) if row['source_id'] == source_id), None)
            if index is None:
                raise UserTaskConflict('用户任务已被删除，请重新读取')
            del rows[index]
            return self._publish(rows)

    def load_tasks(self):
        from src.runtime import combat_api
        combat_api.configure(native=True, data_dir=self.data_dir)
        catalog = self._catalog()
        descriptors = []
        for row in catalog['tasks']:
            code = self._read_code(row)
            task_class = load_export(
                self._code_path(row['source_id'], row['source_revision']), row['class_name'],
                'okww_user_' + row['source_id'].replace('-', '') + '_' + row['source_revision'],
                code.encode('utf-8'))
            descriptors.append({**deepcopy(row), 'task_class': task_class,
                                'config_name': 'user_' + row['source_id'],
                                'required_capabilities': frozenset(row['required_capabilities'])})
        return descriptors
