"""Per-combat observations; no input or invented buff/skill success."""
from collections import Counter, deque
import time


class RotationState:
    def __init__(self, chars):
        self.started = time.monotonic()
        self.rows = {c.index: dict(slot=c.index + 1, script=c.name, identity=str(c.char_name),
                                  confidence=round(c.confidence, 3), role=str(c.char_type),
                                  switches=0, field_seconds=0.0, turns=0, actions=Counter())
                     for c in chars if c is not None}
        self.support_attempts = set()
        self.current = None
        self.since = None
        self.turn_started = None
        self.turn_actions = 0
        self.turn_finished = False
        self.quick_main_exits = 0
        self.events = Counter()
        self.recent = deque(maxlen=12)

    def begin(self, char):
        now = time.monotonic()
        if self.current != char.index:
            self._close(now)
            self.current, self.since = char.index, now
        self.turn_started = now
        self.turn_actions = sum(self.rows[char.index]['actions'].values())
        self.turn_finished = False
        self.rows[char.index]['turns'] += 1

    def finish_turn(self, char):
        if self.turn_started is None or self.turn_finished:
            return False
        self.turn_finished = True
        if char.is_main_dps:
            self.support_attempts.clear()
            duration = time.monotonic() - self.turn_started
            acted = sum(self.rows[char.index]['actions'].values()) > self.turn_actions
            self.quick_main_exits = self.quick_main_exits + 1 if duration < .5 and not acted else 0
            return self.quick_main_exits >= 3
        self.support_attempts.add(char.index)
        self.rows[char.index]['actions']['support_preparation_attempt'] += 1
        return False

    def main_due(self, chars, current):
        supports = {c.index for c in chars if c and not c.is_main_dps}
        return not current.is_main_dps and bool(supports) and supports <= self.support_attempts

    def _close(self, now):
        if self.current in self.rows and self.since is not None:
            self.rows[self.current]['field_seconds'] += max(0, now - self.since)
        self.since = None

    def switched(self, target):
        now = time.monotonic()
        self._close(now)
        self.rows[target.index]['switches'] += 1
        self.current, self.since = target.index, now
        self.turn_started = None

    def action(self, char, name):
        self.rows[char.index]['actions'][name] += 1

    def snapshot(self):
        now = time.monotonic()
        rows = []
        for index, row in self.rows.items():
            active = max(0, now - self.since) if index == self.current and self.since is not None else 0
            rows.append({**row, 'field_seconds': round(row['field_seconds'] + active, 3),
                         'actions': dict(row['actions'])})
        return dict(elapsed=round(now - self.started, 3), chars=rows,
                    events=dict(self.events), recent=list(self.recent))
