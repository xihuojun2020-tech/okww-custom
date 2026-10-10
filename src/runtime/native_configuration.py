# SPDX-License-Identifier: AGPL-3.0-or-later
"""Owner configuration API and a separate JSONL process without a device."""

import json
from pathlib import Path
import sys
import threading

from src.runtime.native_metadata import GLOBAL_METADATA, TaskMetadata, task_id


COMMANDS = frozenset({'get-schema', 'set-config', 'invoke-action',
    'get-context', 'set-context',
    'user-task-list', 'user-task-read', 'user-task-save', 'user-task-delete',
    'user-bundle-inspect', 'user-bundle-list', 'user-bundle-read', 'user-bundle-import',
    'user-bundle-export', 'user-task-export', 'user-bundle-delete',
    'character-list', 'character-read', 'character-save', 'character-reset', 'character-set-mode'})


def _validate_values(values, defaults, config_type):
    if not isinstance(values, dict):
        raise ValueError('Configuration values must be a JSON object')
    for key, value in values.items():
        if key not in defaults:
            raise ValueError(f'Unknown configuration key: {key}')
        definition = config_type.get(key, {})
        if definition.get('hidden') or definition.get('type') in ('label', 'button'):
            raise ValueError(f'Configuration is read-only: {key}')
        if type(value) is not type(defaults[key]):
            raise ValueError(f'{key} requires {type(defaults[key]).__name__}')
        if 'min' in definition and value < definition['min']:
            raise ValueError(f'{key} must be at least {definition["min"]}')
        if 'max' in definition and value > definition['max']:
            raise ValueError(f'{key} must be at most {definition["max"]}')
        options = definition.get('options')
        kind = definition.get('type')
        if not kind and options is not None:
            kind = 'multi_selection' if isinstance(defaults[key], list) else 'drop_down'
        if options is not None and kind in ('drop_down', 'integer_drop_down', 'multi_selection', 'dropdown_multi_selection'):
            allowed = [option[0] if kind == 'integer_drop_down' else option for option in options]
            selected = value if kind in ('multi_selection', 'dropdown_multi_selection') else [value]
            if any(option not in allowed for option in selected):
                raise ValueError(f'Invalid configuration option: {key}')


class ConfigurationService:
    def __init__(self, host):
        self.host = host
        self.metadata = TaskMetadata(host)

    def _task(self, identifier):
        identifier = 'auto-combat' if identifier == 'AutoCombatTask' else identifier
        for task in self.host.tasks.values():
            if task_id(task) == identifier:
                return task
        raise ValueError(f'Unknown task: {identifier}')

    def request(self, request):
        response = {'event': 'configuration-response', 'request_id': request.get('request_id'),
                    'command': request.get('command')}
        try:
            command = request['command']
            result = None
            if command == 'get-schema':
                pass
            elif command in ('get-context', 'set-context'):
                from src.runtime.native_account_context import NativeAccountContext
                context = NativeAccountContext(self.host)
                result = (context.snapshot() if command == 'get-context' else
                          context.set(**{key: value for key, value in request.items()
                                         if key not in ('command', 'request_id')}))
            elif command == 'set-config':
                values = request['values']
                if request['scope'] == 'task':
                    from src.runtime.native_task import NativeTriggerTask
                    task = self._task(request['id'])
                    toggled = '_enabled' in values if isinstance(values, dict) else False
                    ordinary = {key: value for key, value in values.items() if key != '_enabled'} if isinstance(values, dict) else values
                    if toggled and (not isinstance(task, NativeTriggerTask) or type(values['_enabled']) is not bool):
                        raise ValueError('Service enabled preference must be a boolean')
                    _validate_values(ordinary, task.default_config, task.config_type)
                    from src.task.MultiAccountDailyTask import CURRENT_SEQUENCE, CURRENT_ACCOUNT
                    if task_id(task) == 'MultiAccountDailyTask' and {CURRENT_SEQUENCE, CURRENT_ACCOUNT}.intersection(ordinary):
                        from src.runtime.native_account_context import NativeAccountContext
                        NativeAccountContext(self.host).set_config(ordinary)
                    else:
                        task.config.update(ordinary)
                    if toggled:
                        self.host._set_service(task, values['_enabled'], preference_only=True)
                        if values['_enabled']:
                            self.host._configuration_service_enables.add(task_id(task))
                        else:
                            self.host._configuration_service_enables.discard(task_id(task))
                elif request['scope'] == 'global':
                    identifier = request['id']
                    config = self.host.global_configs[identifier]
                    _validate_values(values, config.default, GLOBAL_METADATA[identifier]['config_type'])
                    if identifier == 'Game Hotkey':
                        for value in values.values():
                            self.host.task.validate_key(value)
                    config.update(values)
                else:
                    raise ValueError('Configuration scope must be task or global')
            elif command == 'invoke-action':
                self.metadata.snapshot()
                task, callback, target, no_device = self.metadata.actions[request['action_id']]
                if task_id(task) != request['task_id']:
                    raise ValueError('Configuration action belongs to another task')
                if target == 'management':
                    result = {'target': 'management', 'section': 'accounts'}
                else:
                    if self.host.context.device is None and not no_device:
                        raise RuntimeError('This configuration action requires an execution device')
                    if callback is None:
                        raise ValueError('Configuration button has no action')
                    result = callback()
            elif command in {'user-task-list', 'user-task-read', 'user-task-save', 'user-task-delete'}:
                from src.runtime.native_user_tasks import NativeUserTaskStore
                store = NativeUserTaskStore(self.host.context.data_dir)
                if command == 'user-task-list':
                    result = {'tasks': store.list(), 'catalog_revision': store.revision}
                elif command == 'user-task-read':
                    result = store.read(request['source_id'])
                else:
                    if command == 'user-task-save':
                        result = store.save(request['code'], request['class_name'],
                            source_id=request.get('source_id'),
                            expected_revision=request.get('expected_revision'),
                            required_capabilities=request['required_capabilities'])
                    else:
                        result = {'catalog_revision': store.delete(request['source_id'],
                            expected_revision=request['expected_revision'])}
                    # Disk publication and this owner's applied registry are
                    # separate facts; another running worker is not implied.
                    response['result'] = {**result, 'applied': False,
                                          'applied_revision': self.host.applied_revision}
                    applied = self.host.reload_user_tasks()
                    result = {**result, 'applied': True, **applied}
            elif command.startswith('user-bundle-') or command == 'user-task-export':
                from src.runtime.native_user_tasks import NativeUserTaskStore
                store = NativeUserTaskStore(self.host.context.data_dir)
                if command == 'user-bundle-inspect':
                    result = store.inspect_bundle(request['archive_path'])
                elif command == 'user-bundle-list':
                    result = {'bundles': store.list_bundles(), 'catalog_revision': store.revision}
                elif command == 'user-bundle-read':
                    result = store.read_bundle(request['bundle_id'])
                elif command == 'user-bundle-export':
                    result = store.export_bundle(request['bundle_id'], request['output_path'],
                        expected_revision=request['expected_revision'])
                elif command == 'user-task-export':
                    result = store.export_tasks(request['source_ids'], request['output_path'],
                        file_name=request['file_name'], script_name=request['script_name'],
                        version=request['version'], expected_revision=request['expected_revision'])
                elif command in {'user-bundle-import', 'user-bundle-delete'}:
                    if command == 'user-bundle-import':
                        result = store.import_bundle(request['archive_path'],
                            expected_revision=request['expected_revision'],
                            expected_archive_sha256=request['expected_archive_sha256'],
                            migration_tasks=request.get('migration_tasks'))
                    else:
                        result = store.delete_bundle(request['bundle_id'],
                            expected_revision=request['expected_revision'])
                    response['result'] = {**result, 'applied': False,
                                          'applied_revision': self.host.applied_revision}
                    result = {**result, 'applied': True, **self.host.reload_user_tasks()}
                else:
                    raise ValueError(f'Unknown user bundle command: {command}')
            elif command.startswith('character-') and command in COMMANDS:
                from src.runtime.native_characters import NativeCharacterService
                service = NativeCharacterService(self.host.context.data_dir)
                if command == 'character-list':
                    result = service.list()
                elif command == 'character-read':
                    result = service.read(request['class_name'])
                else:
                    if command == 'character-save':
                        result = service.save(request['class_name'], request['code'],
                            expected_revision=request['expected_revision'])
                    elif command == 'character-reset':
                        result = service.reset(request['class_name'], expected_revision=request['expected_revision'])
                    else:
                        result = service.set_mode(request['class_name'], request['use_custom'],
                            expected_revision=request['expected_revision'])
                    response['result'] = {**result, 'applied': False,
                        'applied_character_revision': self.host.applied_character_revision}
                    result = {**result, 'applied': True, **self.host.reload_character_code()}
            else:
                raise ValueError(f'Unknown configuration command: {command}')
            response.update(ok=True, schema=self.metadata.snapshot())
            if result is not None:
                from src.runtime.native_metadata import json_value
                response['result'] = json_value(result)
        except Exception as error:
            response.update(ok=False, error={'type': type(error).__name__, 'message': str(error)})
        response['applied_revision'] = self.host.applied_revision
        response['applied_character_revision'] = self.host.applied_character_revision
        return response


def create_configuration_host(data_dir, program_version, manifest_path, events):
    """Construct genuine task/config objects without preparing any device or model."""
    from gameframe.api import TaskContext
    from src.runtime import combat_api
    from src.runtime.account_runtime_bootstrap import initialize_account_runtime
    from src.runtime.native_combat_host import NativeCombatHost
    from src.combat.settings import COMBAT_GLOBAL_DEFAULTS, TEMPLATE_MATCHING_DEFAULTS
    from src.storage import resolve_config_backup_dir
    root = Path(data_dir).resolve()
    combat_api.configure(native=True, data_dir=root)
    initialize_account_runtime(root, program_version, install_start_guard=False,
                               backup_dir=resolve_config_backup_dir(root), restore_prepared=True)
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    definitions = manifest['tasks']
    from src.runtime.native_user_tasks import NativeUserTaskStore
    store = NativeUserTaskStore(root)
    user_tasks = store.load_tasks()
    source = Path(__file__).resolve().parents[2]
    from src.runtime.native_language import LANGUAGE_DEFAULTS, create_language_config, load_language
    from src.runtime.native_program_preferences import DEFAULTS, NAME, NativeProgramPreferences
    preferences = NativeProgramPreferences(root)
    from src.runtime.native_notifications import NativeNotificationPreferences
    notification_preferences = NativeNotificationPreferences(root)
    create_language_config(root)
    language = load_language(root, pack_root=Path(manifest_path).parent)
    context = TaskContext(None, {}, root, threading.Event(), 'configuration', events)
    host = NativeCombatHost(
        context, coco_path=source / 'assets/coco_annotations.json',
        global_options={**COMBAT_GLOBAL_DEFAULTS, NAME: DEFAULTS, 'Language': LANGUAGE_DEFAULTS,
                        notification_preferences.config.config_file.stem: notification_preferences.config.default},
        ocr_engine=None,
        translate=language.translate,
        template_matching=TEMPLATE_MATCHING_DEFAULTS,
        task_entry=definitions[0]['module'] + ':' + definitions[0]['class'],
        registered_tasks=tuple(task['module'] + ':' + task['class'] for task in definitions),
        device_identity='configuration', user_tasks=user_tasks,
        program_preferences=preferences.config)
    host.task_metadata = {task['id']: task for task in definitions}
    host.program_preferences = host.global_configs[NAME]
    host.applied_revision = store.revision
    return host


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args(argv)
    from contextlib import ExitStack
    from gameframe.process_locks import data_lease, package_lease
    def emit(value):
        print(json.dumps(value, ensure_ascii=False), flush=True)
    host = None
    leases = ExitStack()
    try:
        leases.enter_context(package_lease(args.manifest.parent))
        from src.native_maintenance import prepare_native_data
        prepare_native_data(args.data_dir, args.version)
        leases.enter_context(data_lease(args.data_dir))
        host = create_configuration_host(args.data_dir, args.version, args.manifest, emit)
        emit({'event': 'configuration-ready'})
        for line in sys.stdin:
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError('Configuration request must be a JSON object')
                if request.get('command') == 'stop':
                    break
                response = host.configuration_request(request)
            except Exception as error:
                response = {'event': 'configuration-response', 'request_id': None,
                            'ok': False, 'error': {'type': type(error).__name__, 'message': str(error)}}
            emit(response)
        return 0
    except Exception as error:
        emit({'event': 'configuration-failed', 'error': {'type': type(error).__name__, 'message': str(error)}})
        return 1
    finally:
        try:
            if host is not None:
                from src.evidence.service import get_evidence_service
                get_evidence_service().close()
        finally:
            leases.close()


if __name__ == '__main__':
    raise SystemExit(main())
