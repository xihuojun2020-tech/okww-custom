# SPDX-License-Identifier: AGPL-3.0-or-later
"""Owner configuration API and a separate JSONL process without a device."""

import json
from pathlib import Path
import sys
import threading

from src.runtime.native_metadata import GLOBAL_METADATA, TaskMetadata, task_id


COMMANDS = frozenset({'get-schema', 'set-config', 'invoke-action'})


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
                    task.config.update(ordinary)
                    if toggled:
                        self.host._set_service(task, values['_enabled'], preference_only=True)
                        if values['_enabled']:
                            self.host._configuration_service_enables.add(task)
                        else:
                            self.host._configuration_service_enables.discard(task)
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
            else:
                raise ValueError(f'Unknown configuration command: {command}')
            response.update(ok=True, schema=self.metadata.snapshot())
            if result is not None:
                from src.runtime.native_metadata import json_value
                response['result'] = json_value(result)
        except Exception as error:
            response.update(ok=False, error={'type': type(error).__name__, 'message': str(error)})
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
                               backup_dir=resolve_config_backup_dir(root))
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    definitions = manifest['tasks']
    source = Path(__file__).resolve().parents[2]
    context = TaskContext(None, {}, root, threading.Event(), 'configuration', events)
    return NativeCombatHost(
        context, coco_path=source / 'assets/coco_annotations.json',
        global_options=COMBAT_GLOBAL_DEFAULTS, ocr_engine=None,
        template_matching=TEMPLATE_MATCHING_DEFAULTS,
        task_entry=definitions[0]['module'] + ':' + definitions[0]['class'],
        registered_tasks=tuple(task['module'] + ':' + task['class'] for task in definitions),
        device_identity='configuration')


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args(argv)
    def emit(value):
        print(json.dumps(value, ensure_ascii=False), flush=True)
    host = None
    try:
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
        if host is not None:
            from src.evidence.service import get_evidence_service
            get_evidence_service().close()


if __name__ == '__main__':
    raise SystemExit(main())
