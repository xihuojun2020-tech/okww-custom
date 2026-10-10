# SPDX-License-Identifier: AGPL-3.0-or-later
"""JSON snapshots of genuine task metadata; callbacks stay in the owner."""

from copy import deepcopy
from src.runtime.native_language import LANGUAGE_METADATA
from src.runtime.native_notifications import NAME as NOTIFICATION_NAME, SECRET_KEYS


GLOBAL_METADATA = {
    NOTIFICATION_NAME: {
        'description': 'Notification channels; desktop delivery uses the current input owner.',
        'config_description': {},
        'config_type': {key: {'secret': True} for key in SECRET_KEYS},
    },
    'Language': LANGUAGE_METADATA,
    'Program Preferences': {
        'description': 'Window, audio and inference preferences',
        'config_description': {
            'Trigger Interval': 'Milliseconds between service scheduling passes.',
            'Use DirectML': 'OCR provider changes apply after restarting the task session.',
            'Enable Blur': 'Blur Game UID etc to enhance OLED life',
            'Blur Algorithm': 'Method used to obscure configured areas',
            'Blur Interval': 'Seconds between processed overlay updates',
        },
        'config_type': {'Enable Blur': {'sub_configs': {True: ['Blur Algorithm', 'Blur Interval']}},
                        'Blur Algorithm': {'type': 'drop_down', 'options': ['Blur', 'Inpaint']},
                        'Blur Interval': {'min': 0},
                        'Trigger Interval': {'min': 0, 'max': 1000},
                        'Use DirectML': {'type': 'drop_down', 'options': ['Auto', 'Yes', 'No'],
                                         'restart_required': True}},
    },
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
        from src.runtime.native_account_context import NativeAccountContext
        from gameframe.ui_strings import LABELS
        tr = self.host._app.tr
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
            definition = getattr(self.host, 'task_metadata', {}).get(task_id(task), {})
            tasks.append({
                'id': task_id(task), 'name': tr(task.name), 'description': tr(task.description),
                'kind': 'service' if isinstance(task, NativeTriggerTask) else 'one-shot',
                'visible': definition.get('visible', getattr(task, 'visible', True)),
                'category': tr(definition.get('category', '')),
                'order': definition.get('order', 0),
                'group_name': getattr(task, 'group_name', None),
                'import_namespace': getattr(task, 'import_namespace', None),
                'support_schedule_task': getattr(task, 'support_schedule_task', False),
                'default_config': json_value(task.default_config),
                'current_config': json_value(task.config),
                'config_description': {key: tr(value) for key, value in task.config_description.items()},
                'config_type': config_type, 'readonly_values': readonly,
                'enabled': task.enabled, 'running': task.running,
            })
        globals_ = []
        for name, config in self.host.global_configs.items():
            metadata = deepcopy(GLOBAL_METADATA[name])
            metadata['description'] = tr(metadata['description'])
            metadata['config_description'] = {key: tr(value) for key, value in metadata['config_description'].items()}
            current = json_value(config)
            if name == NOTIFICATION_NAME:
                for key in SECRET_KEYS:
                    metadata['config_type'][key]['configured'] = bool(current[key])
                    current[key] = ''
            globals_.append({'id': name, 'name': tr(name),
                             'default_config': json_value(config.default),
                             'current_config': current,
                             'readonly_values': {}, **metadata})
        return {'tasks': tasks, 'globals': globals_,
                'launcher_labels': {text: tr(text) for text in LABELS},
                'account_context': NativeAccountContext(self.host).snapshot(),
                'reserved_hotkeys': list(self.host.global_configs['Game Hotkey'].values())
                    if 'Game Hotkey' in self.host.global_configs else []}
