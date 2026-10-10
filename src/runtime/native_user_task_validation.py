# SPDX-License-Identifier: AGPL-3.0-or-later
"""Execute trusted user task candidates in a separate no-device process.

This is configuration/runtime isolation, not a security sandbox. User Python
code retains the permissions of the user who chose to run it.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import threading


def load_module(path, module_name, source_bytes):
    """Compile exact source bytes, avoiding timestamp-based bytecode reuse."""
    path = Path(path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        exec(compile(source_bytes, str(path), 'exec'), module.__dict__)
        return module
    except BaseException:
        sys.modules.pop(module_name, None)
        raise


def exported_class(module, class_name):
    from src.runtime.native_task import NativeBaseTask
    exported = getattr(module, class_name)
    if (not isinstance(exported, type) or exported is NativeBaseTask
            or not issubclass(exported, NativeBaseTask)
            or exported.__module__ != module.__name__ or exported.__name__ != class_name):
        raise TypeError('导出必须是在本源码中定义的 NativeBaseTask/NativeTriggerTask 子类')
    return exported


def load_export(path, class_name, module_name, source_bytes):
    module = load_module(path, module_name, source_bytes)
    try:
        return exported_class(module, class_name)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise


def load_bundle_exports(root, manifest, bundle_revision):
    from src.runtime.native_user_task_bundles import bundle_identity, relative_file, task_identity, digest_json
    root = Path(root)
    bundle_id = bundle_identity(manifest['file_name'])
    index = json.loads((root / 'files.json').read_text(encoding='utf-8'))
    if digest_json(index) != bundle_revision:
        raise ValueError('用户脚本包源码索引在加载前已改变')
    modules, descriptors = {}, []
    for task in manifest['tasks']:
        path = relative_file(root, task['path'], root_python=True)
        if task['path'] not in modules:
            payload = path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != index[task['path']]:
                raise ValueError('用户脚本包不可变源码在加载前已改变')
            name = ('okww_bundle_' + bundle_id.replace('-', '') + '_' + bundle_revision
                    + '_' + hashlib.sha256(task['path'].encode('utf-8')).hexdigest()[:12])
            modules[task['path']] = load_module(path, name, payload), hashlib.sha256(payload).hexdigest()
        module, revision = modules[task['path']]
        source_id = task_identity(bundle_id, task['key'])
        descriptors.append({'task_class': exported_class(module, task['class_name']),
                            'id': 'user:' + source_id, 'source_id': source_id,
                            'config_name': 'user_' + source_id, 'source_revision': revision,
                            'required_capabilities': frozenset(task['required_capabilities']),
                            'group_name': manifest['script_name'],
                            'asset_coco_path': (root / 'assets/coco_annotations.json'
                                                if (root / 'assets/coco_annotations.json').is_file() else None),
                            'asset_namespace': manifest['file_name']})
    return descriptors


def _prepare_runtime(data_dir):
    from src.runtime import combat_api
    from src.runtime.account_runtime_bootstrap import initialize_account_runtime
    combat_api.configure(native=True, data_dir=data_dir)
    # Native account helpers must resolve to the same disposable root as Config.
    # Copied saved settings/accounts are read-only inputs to this process;
    # constructor writes stay in this root and no account task is started.
    initialize_account_runtime(
        data_dir, 'user-task-validation', install_start_guard=False,
        backup_dir=Path(data_dir) / 'configs_backup', restore_prepared=True)


def _validate_descriptors(descriptors, data_dir):
    from gameframe.api import TaskContext
    from src.runtime.native_combat_host import NativeCombatHost
    from src.runtime.native_metadata import TaskMetadata
    from src.combat.settings import COMBAT_GLOBAL_DEFAULTS, TEMPLATE_MATCHING_DEFAULTS
    context = TaskContext(None, {}, Path(data_dir), threading.Event(),
                          'user-task-validation', lambda value: None)
    host = NativeCombatHost(
        context, coco_path=Path(__file__).resolve().parents[2] / 'assets/coco_annotations.json',
        global_options=COMBAT_GLOBAL_DEFAULTS, ocr_engine=None,
        template_matching=TEMPLATE_MATCHING_DEFAULTS, task_entry=descriptors[0]['task_class'],
        user_tasks=descriptors, device_identity='configuration')
    metadata = TaskMetadata(host).snapshot()['tasks']
    # The catalog is consumed by metadata-only core code as well as Qt forms.
    for task, item in zip(host.tasks.values(), metadata):
        if (not isinstance(item['name'], str) or not item['name'].strip()
                or not isinstance(item['description'], str)
                or not isinstance(item['default_config'], dict)
                or any(not isinstance(key, str) for key in task.default_config)
                or any(not isinstance(value, str) for value in item['config_description'].values())
                or any(not isinstance(value, dict) for value in item['config_type'].values())
                or type(item['visible']) is not bool
                or type(item['support_schedule_task']) is not bool):
            raise TypeError('用户任务名称、配置表单或显示/计划任务元数据类型无效')
    json.dumps(metadata, ensure_ascii=False, allow_nan=False)
    return metadata


def validate_candidate(code_path, class_name, data_dir, source_id, source_revision):
    _prepare_runtime(data_dir)
    task_class = load_export(code_path, class_name,
                             'okww_user_' + source_id.replace('-', '') + '_' + source_revision,
                             Path(code_path).read_bytes())
    descriptor = {'task_class': task_class, 'id': 'user:' + source_id,
                  'config_name': 'user_' + source_id, 'source_revision': source_revision,
                  'required_capabilities': frozenset()}
    return _validate_descriptors((descriptor,), data_dir)[0]


def validate_bundle(root, data_dir):
    from gameframe.packages import verify_index
    from src.runtime.native_user_task_bundles import check_manifest, check_assets, digest_json
    root = Path(root)
    verify_index(root, required=True)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    check_manifest(manifest, root)
    check_assets(root)
    _prepare_runtime(data_dir)
    revision = digest_json(json.loads((root / 'files.json').read_text(encoding='utf-8')))
    return _validate_descriptors(load_bundle_exports(root, manifest, revision), data_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-root', type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--code-path', type=Path)
    source.add_argument('--bundle-root', type=Path)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--class-name')
    parser.add_argument('--source-id')
    parser.add_argument('--source-revision')
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    sys.path.append(str(args.core_root))
    try:
        metadata = (validate_bundle(args.bundle_root, args.data_dir) if args.bundle_root else
                    validate_candidate(args.code_path, args.class_name, args.data_dir,
                                       args.source_id, args.source_revision))
        result, status = {'ok': True, 'metadata': metadata}, 0
    except Exception as error:
        result, status = {'ok': False, 'error': str(error), 'type': type(error).__name__}, 1
    finally:
        from src.evidence.service import close_existing_evidence_service
        close_existing_evidence_service()
    args.result.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    return status


if __name__ == '__main__':
    raise SystemExit(main())
