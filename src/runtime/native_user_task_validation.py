# SPDX-License-Identifier: AGPL-3.0-or-later
"""Execute trusted user task candidates in a separate no-device process.

This is configuration/runtime isolation, not a security sandbox. User Python
code retains the permissions of the user who chose to run it.
"""

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import threading


def load_export(path, class_name, module_name, source_bytes):
    """Compile exact source bytes, avoiding timestamp-based bytecode reuse."""
    from src.runtime.native_task import NativeBaseTask
    path = Path(path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        exec(compile(source_bytes, str(path), 'exec'), module.__dict__)
        exported = getattr(module, class_name)
        if (not isinstance(exported, type) or exported is NativeBaseTask
                or not issubclass(exported, NativeBaseTask)
                or exported.__module__ != module_name or exported.__name__ != class_name):
            raise TypeError('导出必须是在本源码中定义的 NativeBaseTask/NativeTriggerTask 子类')
        return exported
    except BaseException:
        sys.modules.pop(module_name, None)
        raise


def validate_candidate(code_path, class_name, data_dir, source_id, source_revision):
    from gameframe.api import TaskContext
    from src.runtime import combat_api
    from src.runtime.native_combat_host import NativeCombatHost
    from src.runtime.native_metadata import TaskMetadata
    from src.runtime.account_runtime_bootstrap import initialize_account_runtime
    from src.combat.settings import COMBAT_GLOBAL_DEFAULTS, TEMPLATE_MATCHING_DEFAULTS
    combat_api.configure(native=True, data_dir=data_dir)
    # Native account helpers must resolve to the same disposable root as Config.
    # Copied saved settings/accounts are read-only inputs to this process;
    # constructor writes stay in this root and no account task is started.
    initialize_account_runtime(
        data_dir, 'user-task-validation', install_start_guard=False,
        backup_dir=Path(data_dir) / 'configs_backup', restore_prepared=True)
    task_class = load_export(code_path, class_name,
                             'okww_user_' + source_id.replace('-', '') + '_' + source_revision,
                             Path(code_path).read_bytes())
    descriptor = {'task_class': task_class, 'id': 'user:' + source_id,
                  'config_name': 'user_' + source_id, 'source_revision': source_revision,
                  'required_capabilities': frozenset()}
    context = TaskContext(None, {}, Path(data_dir), threading.Event(),
                          'user-task-validation', lambda value: None)
    host = NativeCombatHost(
        context, coco_path=Path(__file__).resolve().parents[2] / 'assets/coco_annotations.json',
        global_options=COMBAT_GLOBAL_DEFAULTS, ocr_engine=None,
        template_matching=TEMPLATE_MATCHING_DEFAULTS, task_entry=task_class,
        user_tasks=(descriptor,), device_identity='configuration')
    metadata = TaskMetadata(host).snapshot()['tasks'][0]
    # The catalog is consumed by metadata-only core code as well as Qt forms.
    if (not isinstance(metadata['name'], str) or not metadata['name'].strip()
            or not isinstance(metadata['description'], str)
            or not isinstance(metadata['default_config'], dict)
            or any(not isinstance(key, str) for key in host.task.default_config)
            or any(not isinstance(value, str) for value in metadata['config_description'].values())
            or any(not isinstance(value, dict) for value in metadata['config_type'].values())
            or type(metadata['visible']) is not bool
            or type(metadata['support_schedule_task']) is not bool):
        raise TypeError('用户任务名称、配置表单或显示/计划任务元数据类型无效')
    json.dumps(metadata, ensure_ascii=False, allow_nan=False)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-root', type=Path, required=True)
    parser.add_argument('--code-path', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--class-name', required=True)
    parser.add_argument('--source-id', required=True)
    parser.add_argument('--source-revision', required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    sys.path.append(str(args.core_root))
    try:
        metadata = validate_candidate(args.code_path, args.class_name, args.data_dir,
                                      args.source_id, args.source_revision)
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
