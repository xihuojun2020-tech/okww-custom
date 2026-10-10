"""Desktop preferences and transition-based hotkey reads, without game input."""

import ctypes
import json
import os
from pathlib import Path


HOTKEYS = ('None', 'F9', 'F10', 'F11', 'F12')


def desktop_preferences(data_dir, options):
    """Migrate only settings with native behavior; explicit False is preserved."""
    basic_path = Path(data_dir) / 'configs/Basic Options.json'
    notification_path = Path(data_dir) / 'configs/Notification.json'
    basic = json.loads(basic_path.read_text(encoding='utf-8')) if basic_path.exists() else {}
    notification = json.loads(notification_path.read_text(encoding='utf-8')) if notification_path.exists() else {}
    value = {
        'pause_hotkey': options.get('pause_hotkey', basic.get('Start/Stop', 'None')),
        'tray_notifications': options.get('tray_notifications', notification.get('System Notification', True)),
        'close_to_tray': options.get('close_to_tray', basic.get('Minimize Window to System Tray when Closing', False)),
    }
    if value['pause_hotkey'] not in HOTKEYS or any(type(value[key]) is not bool
            for key in ('tray_notifications', 'close_to_tray')):
        raise ValueError('Invalid desktop preferences')
    return value


def key_pressed(key):
    if os.name != 'nt' or key == 'None':
        return False
    return bool(ctypes.WinDLL('user32').GetAsyncKeyState(0x6F + int(key[1:])) & 0x8000)


class HotkeyTransition:
    def __init__(self, reader=key_pressed):
        self.reader = reader
        self.key = 'None'
        self.down = False

    def set_key(self, key):
        if key not in HOTKEYS:
            raise ValueError(f'Unsupported pause hotkey: {key}')
        self.key, self.down = key, False

    def poll(self):
        down = self.key != 'None' and self.reader(self.key)
        pressed = down and not self.down
        self.down = down
        return pressed
