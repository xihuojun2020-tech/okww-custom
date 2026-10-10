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
import zipfile

from gameframe import API_VERSION
from src.account_change_lock import get_account_change_lock
from src.runtime.native_user_task_validation import load_export, load_bundle_exports
from src.runtime.native_user_task_bundles import (
    FORMAT, bundle_identity, task_identity, digest_json, relative_file,
    stage_archive, prepare_legacy, check_manifest, check_assets, write_index)


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
            bundles = {}
            for row in result['tasks']:
                source_id = _source_id(row['source_id'])
                if row['id'] != 'user:' + source_id or source_id in seen:
                    raise ValueError('用户任务稳定ID无效或重复')
                seen.add(source_id)
                self._row_code_path(row)
                if 'bundle_id' in row:
                    if (row['bundle_id'] != bundle_identity(row['bundle_file_name'])
                            or source_id != task_identity(row['bundle_id'], row['bundle_task_key'])):
                        raise ValueError('用户脚本包稳定ID无效')
                    definition = (row['bundle_revision'], row['bundle_file_name'],
                                  row['bundle_title'], row['bundle_version'], row['asset_namespace'])
                    if row['bundle_id'] in bundles and bundles[row['bundle_id']] != definition:
                        raise ValueError('同一用户脚本包必须一次发布同一快照')
                    bundles[row['bundle_id']] = definition
        self.revision = result['revision']
        return result

    def _code_path(self, source_id, revision):
        source_id = _source_id(source_id)
        if not isinstance(revision, str) or re.fullmatch('[0-9a-f]{64}', revision) is None:
            raise ValueError('用户任务源码revision无效')
        return self._inside_root(self.root / source_id / 'revisions' / revision / 'task.py')

    def _bundle_path(self, bundle_id, revision):
        bundle_id = _source_id(bundle_id)
        if not isinstance(revision, str) or re.fullmatch('[0-9a-f]{64}', revision) is None:
            raise ValueError('用户脚本包revision无效')
        return self._inside_root(self.root / 'bundles' / bundle_id / 'revisions' / revision)

    def _row_code_path(self, row):
        if 'bundle_id' in row:
            root = self._bundle_path(row['bundle_id'], row['bundle_revision'])
            return relative_file(root, row['source_path'], root_python=True)
        return self._code_path(row['source_id'], row['source_revision'])

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
        payload = self._row_code_path(row).read_bytes()
        if hashlib.sha256(payload).hexdigest() != row['source_revision']:
            raise ValueError('用户任务不可变源码已被修改，未加载')
        return payload.decode('utf-8')

    def _validate(self, code, class_name, source_id, source_revision):
        with tempfile.TemporaryDirectory(prefix='okww-user-task-validation-') as directory:
            temporary = Path(directory)
            source = temporary / 'task.py'
            source.write_text(code, encoding='utf-8', newline='')
            return self._run_validation(temporary, ['--code-path', str(source), '--class-name', class_name,
                                        '--source-id', source_id, '--source-revision', source_revision])

    def _run_validation(self, temporary, source_arguments):
        import gameframe
        result_file = temporary / 'result.json'
        config_dir = self.data_dir / 'configs'
        with get_account_change_lock(config_dir):
            if config_dir.is_dir():
                shutil.copytree(config_dir, temporary / 'data/configs')
        process = subprocess.run([
            sys.executable, '-I', '-B', '-X', 'utf8',
            str(Path(__file__).with_name('native_user_task_validation.py')),
            '--core-root', str(Path(gameframe.__file__).resolve().parent.parent),
            '--data-dir', str(temporary / 'data'), '--result', str(result_file), *source_arguments],
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
            if editing and 'bundle_id' in rows[index]:
                raise UserTaskConflict('导入脚本包成员必须通过整组重导入更新')
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
            if 'bundle_id' in rows[index]:
                raise UserTaskConflict('导入脚本包成员必须通过整组删除移除')
            del rows[index]
            return self._publish(rows)

    def load_tasks(self):
        from src.runtime import combat_api
        combat_api.configure(native=True, data_dir=self.data_dir)
        catalog = self._catalog()
        descriptors = []
        bundles = {}
        for row in catalog['tasks']:
            if 'bundle_id' in row:
                if row['bundle_id'] not in bundles:
                    root = self._bundle_path(row['bundle_id'], row['bundle_revision'])
                    manifest = self._verify_bundle_snapshot(root, row['bundle_revision'])
                    bundles[row['bundle_id']] = {
                        item['id']: item for item in load_bundle_exports(root, manifest, row['bundle_revision'])}
                descriptor = bundles[row['bundle_id']][row['id']]
                if (descriptor['source_revision'] != row['source_revision']
                        or descriptor['task_class'].__name__ != row['class_name']
                        or descriptor['required_capabilities'] != frozenset(row['required_capabilities'])):
                    raise ValueError('用户脚本包任务声明与已发布快照不一致')
            else:
                code = self._read_code(row)
                task_class = load_export(
                    self._row_code_path(row), row['class_name'],
                    'okww_user_' + row['source_id'].replace('-', '') + '_' + row['source_revision'],
                    code.encode('utf-8'))
                descriptor = {'task_class': task_class, 'asset_coco_path': None,
                              'asset_namespace': None, 'group_name': None}
            descriptors.append({**deepcopy(row), **descriptor,
                                'config_name': 'user_' + row['source_id'],
                                'required_capabilities': frozenset(row['required_capabilities'])})
        return descriptors

    def inspect_bundle(self, archive_path):
        with tempfile.TemporaryDirectory(prefix='okww-bundle-inspect-') as directory:
            return stage_archive(archive_path, Path(directory))

    def _bundle_result(self, bundle_id, catalog):
        rows = [row for row in catalog['tasks'] if row.get('bundle_id') == bundle_id]
        if not rows:
            raise UserTaskConflict('用户脚本包已不存在，请重新读取')
        first = rows[0]
        return {'bundle_id': bundle_id, 'file_name': first['bundle_file_name'],
                'script_name': first['bundle_title'], 'version': first['bundle_version'],
                'bundle_revision': first['bundle_revision'], 'tasks': deepcopy(rows),
                'catalog_revision': catalog['revision']}

    def list_bundles(self):
        catalog = self._catalog()
        bundle_ids = dict.fromkeys(row['bundle_id'] for row in catalog['tasks'] if 'bundle_id' in row)
        return [self._bundle_result(bundle_id, catalog) for bundle_id in bundle_ids]

    def read_bundle(self, bundle_id):
        return self._bundle_result(_source_id(bundle_id), self._catalog())

    def _verify_bundle_snapshot(self, root, revision):
        from gameframe.packages import verify_index
        verify_index(root, required=True)
        index = json.loads((root / 'files.json').read_text(encoding='utf-8'))
        if digest_json(index) != revision:
            raise ValueError('用户脚本包不可变快照已被修改')
        payload = (root / 'manifest.json').read_bytes()
        if hashlib.sha256(payload).hexdigest() != index['manifest.json']:
            raise ValueError('用户脚本包manifest在读取前已改变')
        manifest = json.loads(payload)
        check_manifest(manifest, root)
        check_assets(root)
        return manifest

    def import_bundle(self, archive_path, *, expected_revision, expected_archive_sha256, migration_tasks=None):
        with tempfile.TemporaryDirectory(prefix='okww-bundle-validation-') as directory:
            temporary = Path(directory)
            stage = temporary / 'bundle'
            stage.mkdir()
            preview = stage_archive(archive_path, stage, expected_sha256=expected_archive_sha256)
            manifest = (prepare_legacy(stage, preview, migration_tasks) if preview['format'] == 'legacy'
                        else preview['manifest'])
            revision = digest_json(json.loads((stage / 'files.json').read_text(encoding='utf-8')))
            metadata = self._run_validation(temporary, ['--bundle-root', str(stage)])
            # Candidate code executes in the temporary tree. It cannot silently
            # change the bytes that the parent is about to publish.
            self._verify_bundle_snapshot(stage, revision)
            by_id = {item['id']: item for item in metadata}
            bundle_id = bundle_identity(manifest['file_name'])
            rows = []
            for declaration in manifest['tasks']:
                source_id = task_identity(bundle_id, declaration['key'])
                item = by_id['user:' + source_id]
                payload = relative_file(stage, declaration['path'], root_python=True).read_bytes()
                row = {'id': 'user:' + source_id, 'title': item['name'], 'kind': item['kind'],
                       'default_config': {}, 'required_capabilities': sorted(set(declaration['required_capabilities'])),
                       'visible': item['visible'], 'source_id': source_id,
                       'source_revision': hashlib.sha256(payload).hexdigest(),
                       'class_name': declaration['class_name'], 'metadata': item,
                       'bundle_id': bundle_id, 'bundle_revision': revision,
                       'bundle_file_name': manifest['file_name'], 'bundle_title': manifest['script_name'],
                       'bundle_version': manifest['version'], 'bundle_task_key': declaration['key'],
                       'source_path': declaration['path'], 'asset_namespace': manifest['file_name']}
                row['revision'] = _revision([row])
                rows.append(row)
            with self._lock:
                catalog = self._catalog()
                self._check_revision(catalog, expected_revision, editing=True)
                target = self._bundle_path(bundle_id, revision)
                if target.exists():
                    self._verify_bundle_snapshot(target, revision)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.TemporaryDirectory(prefix='.candidate-', dir=target.parent) as candidate_directory:
                        candidate = Path(candidate_directory)
                        shutil.copytree(stage, candidate, dirs_exist_ok=True)
                        for path in candidate.rglob('*'):
                            if path.is_file():
                                with path.open('r+b') as stream:
                                    os.fsync(stream.fileno())
                        os.replace(candidate, target)
                merged = [row for row in catalog['tasks'] if row.get('bundle_id') != bundle_id]
                if {row['id'] for row in rows} & {row['id'] for row in merged}:
                    raise UserTaskConflict('用户脚本包稳定ID与现有任务冲突')
                catalog_revision = self._publish([*merged, *rows])
            return {'bundle_id': bundle_id, 'catalog_revision': catalog_revision, 'tasks': deepcopy(rows)}

    def delete_bundle(self, bundle_id, *, expected_revision):
        bundle_id = _source_id(bundle_id)
        with self._lock:
            catalog = self._catalog()
            self._check_revision(catalog, expected_revision, editing=True)
            self._bundle_result(bundle_id, catalog)
            rows = [row for row in catalog['tasks'] if row.get('bundle_id') != bundle_id]
            revision = self._publish(rows)
        return {'bundle_id': bundle_id, 'catalog_revision': revision, 'tasks': []}

    def _export_snapshot(self, root, output_path, bundle_id, catalog_revision):
        output = Path(output_path).resolve()
        if output.is_relative_to(self.root):
            raise ValueError('导出文件不能写入不可变用户任务存储目录')
        # Export never overwrites existing user data, even if another exporter
        # creates the chosen path while this archive is being prepared.
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile('wb', dir=output.parent, prefix='.bundle-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
        try:
            with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(root.rglob('*')):
                    if path.is_file():
                        archive.write(path, path.relative_to(root).as_posix())
            with temporary.open('r+b') as stream:
                os.fsync(stream.fileno())
            # A hard link publishes the complete file and fails if destination
            # already exists; it avoids a check-then-replace data-loss race.
            os.link(temporary, output)
            digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        finally:
            temporary.unlink(missing_ok=True)
        return {'path': str(output), 'archive_sha256': digest, 'bundle_id': bundle_id,
                'catalog_revision': catalog_revision}

    def export_bundle(self, bundle_id, output_path, *, expected_revision):
        catalog = self._catalog()
        self._check_revision(catalog, expected_revision, editing=True)
        result = self._bundle_result(_source_id(bundle_id), catalog)
        root = self._bundle_path(result['bundle_id'], result['bundle_revision'])
        self._verify_bundle_snapshot(root, result['bundle_revision'])
        return self._export_snapshot(root, output_path, result['bundle_id'], catalog['revision'])

    def export_tasks(self, source_ids, output_path, *, file_name, script_name, version, expected_revision):
        if not isinstance(source_ids, (list, tuple)) or not source_ids:
            raise ValueError('请选择要导出的独立用户任务')
        source_ids = [_source_id(value) for value in source_ids]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError('导出任务ID重复')
        catalog = self._catalog()
        self._check_revision(catalog, expected_revision, editing=True)
        by_source = {row['source_id']: row for row in catalog['tasks']}
        with tempfile.TemporaryDirectory(prefix='okww-bundle-export-') as directory:
            root = Path(directory)
            declarations = []
            for source_id in source_ids:
                if source_id not in by_source:
                    raise UserTaskConflict('待导出任务已不存在，请重新读取')
                row = by_source[source_id]
                if 'bundle_id' in row:
                    raise ValueError('导入脚本包必须整组导出')
                path = 'task_' + source_id.replace('-', '') + '.py'
                (root / path).write_text(self._read_code(row), encoding='utf-8', newline='')
                declarations.append({'key': source_id, 'path': path, 'class_name': row['class_name'],
                                     'required_capabilities': row['required_capabilities']})
            manifest = {'format': FORMAT, 'format_version': 1, 'file_name': file_name,
                        'script_name': script_name, 'version': version, 'tasks': declarations}
            check_manifest(manifest, root)
            (root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            write_index(root)
            return self._export_snapshot(root, output_path, bundle_identity(file_name), catalog['revision'])
