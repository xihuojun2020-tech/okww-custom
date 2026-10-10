"""Deterministic frame replay: real recognition, no OS or game input."""

import json
import time
from pathlib import Path

from gameframe.api import Action, Frame
from gameframe.vision import load_image


class ReplayDevice:
    capabilities = frozenset({'frames', 'keyboard', 'mouse', 'relative-mouse', 'multitouch', 'scroll', 'text', 'activate',
                              'foreground-query', 'hotkey-query'})

    def __init__(self, paths):
        self.paths = iter(Path(path) for path in paths)
        self.sequence = 0
        self.actions = []
        self.held = set()
        self.closed = False
        self.foreground = True
        self.cursor_position = (0, 0)
        self.target_stopped = False
        self.pressed_virtual_keys = set()
        self.foreground_process_id = 0

    def is_foreground(self):
        return self.foreground

    def hotkey_pressed(self, vk):
        return vk in self.pressed_virtual_keys

    def foreground_pid(self):
        return self.foreground_process_id

    def get_cursor_pos(self):
        return self.cursor_position

    def set_cursor_pos(self, position):
        self.cursor_position = tuple(position)

    def client_to_screen(self, x, y):
        return int(x), int(y)

    def stop_target(self):
        self.release_all()
        self.target_stopped = True
        self.actions.append(Action('stop_target', {}))

    def next_frame(self, timeout=1.0):
        if self.closed:
            raise RuntimeError('Replay device is closed')
        path = next(self.paths, None)
        if path is None:
            return None
        self.sequence += 1
        return Frame(self.sequence, load_image(path), time.monotonic_ns(), 'replay-host-read')

    def submit(self, action):
        if self.closed:
            raise RuntimeError('Replay device is closed')
        self.actions.append(action)
        if action.kind == 'activate':
            self.foreground = True
        elif action.kind == 'move_client':
            self.cursor_position = self.client_to_screen(action.values['x'], action.values['y'])
        elif action.kind == 'move_relative':
            self.cursor_position = (self.cursor_position[0] + action.values['dx'],
                                    self.cursor_position[1] + action.values['dy'])
        if action.kind.endswith('_down'):
            self.held.add((action.kind[:-5], action.values.get('contact',
                           action.values.get('key', action.values.get('button')))))
        elif action.kind.endswith('_up'):
            self.held.discard((action.kind[:-3], action.values.get('contact',
                              action.values.get('key', action.values.get('button')))))

    def release_all(self):
        self.held.clear()

    def save_actions(self, path):
        Path(path).write_text(json.dumps([{'kind': action.kind, 'values': dict(action.values)}
                                          for action in self.actions], ensure_ascii=False, indent=2),
                              encoding='utf-8')

    def close(self):
        self.release_all()
        self.closed = True
