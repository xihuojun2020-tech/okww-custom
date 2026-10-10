# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit combat API provider; the normal application continues to use ok-script.

An isolated native worker selects this provider before importing production
classes. No module is impersonated and already-created class MROs are not changed.
"""

import importlib
from pathlib import Path


_native = False
_mode = None


def configure(*, native, data_dir):
    global _native
    selected = 'native' if native else 'legacy'
    if _mode is not None and _mode != selected:
        raise RuntimeError('Combat API already imported in another mode; use an isolated worker')
    _native = native
    config = __getattr__('Config')
    config.config_folder = str((Path(data_dir) / 'configs').resolve())


class _NativeScene:
    def reset(self):
        pass


def _safe_get(values, index, default=None):
    try:
        return values[index]
    except IndexError:
        return default


_NATIVE_SYMBOLS = {
    'BaseTask': ('src.runtime.native_task', 'NativeBaseTask'),
    'TriggerTask': ('src.runtime.native_task', 'NativeTriggerTask'),
    'Config': ('src.runtime.native_config', 'Config'),
    'Logger': ('src.runtime.native_logging', 'Logger'),
    'Box': ('src.vision.boxes', 'Box'),
    'find_boxes_by_name': ('src.vision.boxes', 'find_boxes_by_name'),
    'find_color_rectangles': ('src.vision.color', 'find_color_rectangles'),
    **{name: ('src.runtime.native_errors', name) for name in (
        'TaskDisabledException', 'FinishedException', 'CaptureException',
        'WaitFailedException', 'CannotFindException', 'HotkeyConfigException')},
}


def __getattr__(name):
    global _mode
    if name not in _NATIVE_SYMBOLS and name not in {'BaseScene', 'safe_get'}:
        raise AttributeError(name)
    _mode = 'native' if _native else 'legacy'
    if not _native:
        return getattr(importlib.import_module('ok'), name)
    if name == 'BaseScene':
        return _NativeScene
    if name == 'safe_get':
        return _safe_get
    module, symbol = _NATIVE_SYMBOLS[name]
    return getattr(importlib.import_module(module), symbol)


def app_services(task):
    if _native or hasattr(task, '_combat_app_services'):
        return task._app if _native else task._combat_app_services
    return importlib.import_module('ok').og.my_app


def emit_task_state(task):
    if _native:
        task.executor.context.emit('combat-state', enabled=task.enabled,
                                   recovery_status=task.recovery_status)
    else:
        from ok.gui.Communicate import communicate
        communicate.task.emit(task)
