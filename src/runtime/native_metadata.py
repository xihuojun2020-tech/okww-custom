# SPDX-License-Identifier: AGPL-3.0-or-later
"""JSON snapshots of genuine task metadata; callbacks stay in the owner."""

from copy import deepcopy


GLOBAL_METADATA = {
    'Game Hotkey': {
        'description': 'In Game Hotkey for Skills',
        'config_description': {'Bag Key': 'In-game hotkey used to open the Bag.'},
        'config_type': {},
    },
    'Character Config': {
        'description': 'Character Config',
        'config_description': {}, 'config_type': {},
    },
    'Monthly Card Config': {
        'description': 'Turn on to avoid interruption by monthly card when executing tasks',
        'config_description': {
            'Check Monthly Card': 'Check for monthly card to avoid interruption of tasks',
            'Monthly Card Time': "Your computer's local time when the monthly card will popup, hour in (0-23), 0 means midnight",
        },
        'config_type': {'Monthly Card Time': {'min': 0, 'max': 23}},
    },
}


def task_id(task):
    if getattr(task, "native_task_id", None) is not None:
        return task.native_task_id
    name = type(task).__name__
    return 'auto-combat' if name == 'AutoCombatTask' else name


def json_value(value):
    if value is None or type(value) in (bool, int, float, str):
        return value
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    raise TypeError(f'Task metadata is not JSON serializable: {type(value).__name__}')


class TaskMetadata:
    def __init__(self, host):
        self.host = host
        self.actions = {}

    def _config_type(self, task):
        result = {}
        for key, definition in task.config_type.items():
            if not isinstance(definition, dict):
                result[key] = json_value(definition)
                continue
            item = {}
            for name, value in definition.items():
                if name in ('callback', 'buttons', 'icon', 'last_completed_provider'):
                    continue
                if name == 'sub_configs':
                    item[name] = [{'value': json_value(option), 'keys': json_value(keys)}
                                  for option, keys in value.items()]
                else:
                    item[name] = json_value(value)
            if definition.get('type') == 'button' or 'callback' in definition or 'buttons' in definition:
                item['type'] = 'button'
                item['buttons'] = []
                for index, button in enumerate(definition.get('buttons') or [definition]):
                    callback = button.get('callback')
                    action_id = f'{task_id(task)}/{key}/{index}'
                    method = getattr(callback, '__name__', '')
                    target = ('management' if method in ('manage_daily_profiles', 'manage_sequences')
                              else 'owner')
                    # These production methods only change task-owned memory.
                    no_device = method == 'clear_current_character_scan'
                    self.actions[action_id] = (task, callback, target, no_device)
                    item['buttons'].append({'action_id': action_id,
                                            'text': button.get('text', key),
                                            'target': target, 'requires_device': not no_device and target == 'owner'})
            provider = definition.get('last_completed_provider')
            if provider is not None:
                item['last_completed'] = [{'value': json_value(option), 'completed': json_value(provider(option))}
                                          for option in definition.get('options', ())]
            result[key] = item
        return result

    def snapshot(self):
        from src.runtime.native_task import NativeTriggerTask
        self.actions.clear()
        tasks = []
        for task in self.host.tasks.values():
            config_type = self._config_type(task)
            readonly = {}
            for key, definition in task.config_type.items():
                if not isinstance(definition, dict) or definition.get('type') != 'label':
                    continue
                sub_key = definition.get('sub_key')
                if sub_key and hasattr(task, 'get_readonly_last_completed'):
                    # Weekly status also reads the run-bound account plan. Before
                    # a run binds that identity, expose the real saved timestamp.
                    value = (task.get_last_completed(sub_key) if task._active_profile_id() is None
                             else task.get_readonly_last_completed(sub_key))
                elif hasattr(task, 'get_readonly_config_value'):
                    value = task.get_readonly_config_value(key)
                else:
                    value = task.config.get(key)
                readonly[key] = json_value(value)
            tasks.append({
                'id': task_id(task), 'name': task.name, 'description': task.description,
                'kind': 'service' if isinstance(task, NativeTriggerTask) else 'one-shot',
                'visible': getattr(task, 'visible', True),
                'support_schedule_task': getattr(task, 'support_schedule_task', False),
                'default_config': json_value(task.default_config),
                'current_config': json_value(task.config),
                'config_description': json_value(task.config_description),
                'config_type': config_type, 'readonly_values': readonly,
                'enabled': task.enabled, 'running': task.running,
            })
        globals_ = []
        for name, config in self.host.global_configs.items():
            metadata = deepcopy(GLOBAL_METADATA[name])
            globals_.append({'id': name, 'name': name,
                             'default_config': json_value(config.default),
                             'current_config': json_value(config),
                             'readonly_values': {}, **metadata})
        return {'tasks': tasks, 'globals': globals_}
