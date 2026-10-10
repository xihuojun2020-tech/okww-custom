"""Deterministic frame replay: real recognition, no OS or game input."""

import json
import time
from pathlib import Path

from gameframe.api import Frame
from gameframe.vision import load_image


class ReplayDevice:
    capabilities = frozenset({'frames', 'keyboard', 'mouse', 'relative-mouse', 'multitouch'})

    def __init__(self, paths):
        self.paths = iter(Path(path) for path in paths)
        self.sequence = 0
        self.actions = []
        self.held = set()
        self.closed = False

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
