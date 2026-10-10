"""Pack-owned combat scheduling and input over a GameFrame device.

This module contains no ok-script or GUI imports. The runtime owns release_all;
production combat code may still release its individual held inputs on unwind.
"""

import time

from gameframe.api import Action, Cancelled
from src.runtime.game_runtime_errors import FrameUnavailable


class NativeCombatExecutor:
    def __init__(self, context, *, scene=None, feature_set=None,
                 stop_exception=Cancelled, wait_exception=TimeoutError, pause=None,
                 wait_scene_timeout=10, wait_until_settle_time=-1):
        self.context = context
        self.exit_event = context.stop
        self.scene = scene
        self.feature_set = feature_set
        self.stop_exception = stop_exception
        self.wait_exception = wait_exception
        self.pause_event = pause
        self.current_task = None
        self.interaction = self
        self.method = self
        self.wait_scene_timeout = wait_scene_timeout
        self.wait_until_settle_time = wait_until_settle_time
        self._frame = None
        self._last_frame_time = 0
        self._diagnostic_frame = None
        self.width = self.height = 0
        self.connected = False

    @property
    def paused(self):
        return self.pause_event is not None and self.pause_event.is_set()

    def check_enabled(self, check_pause=True):
        if (self.exit_event.is_set() or
                (self.current_task is not None and not self.current_task._enabled) or
                (check_pause and self.paused)):
            raise self.stop_exception('Combat execution interrupted')

    def _call(self, operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except Cancelled as error:
            if self.stop_exception is Cancelled:
                raise
            raise self.stop_exception(str(error)) from error

    def reset_scene(self, check_enabled=True):
        if check_enabled:
            self.check_enabled()
        self._frame = None
        if self.scene is not None:
            self.scene.reset()

    def nullable_frame(self):
        return self._frame

    @property
    def frame(self):
        self.check_enabled()
        if self._frame is None:
            self.next_frame()
        return self._frame

    def next_frame(self, time_out=6):
        self.reset_scene()
        deadline = None if time_out is None else time.monotonic() + time_out
        while True:
            self.check_enabled()
            budget = .1 if deadline is None else min(.1, max(0, deadline - time.monotonic()))
            capture_started = time.monotonic()
            try:
                captured = self._call(self.context.device.next_frame, budget)
            except Exception:
                self.connected = False
                raise
            self.check_enabled()
            if captured is not None:
                break
            self.connected = False
            if deadline is not None and time.monotonic() >= deadline:
                raise FrameUnavailable('No new device frame')
            # Replay EOF returns immediately; spend this frame budget rather than spin.
            remaining_budget = max(0, budget - (time.monotonic() - capture_started))
            self._call(self.context.sleep, min(remaining_budget, max(0, deadline - time.monotonic()))
                       if deadline is not None else remaining_budget)
        self._frame = captured.image
        self.height, self.width = captured.image.shape[:2]
        self._last_frame_time = time.time()
        self._diagnostic_frame = (self._frame, self._last_frame_time,
                                  time.monotonic())
        self.connected = True
        return self._frame

    def sleep(self, timeout):
        self.reset_scene()
        deadline = time.monotonic() + max(0, timeout)
        while True:
            self.check_enabled()
            task = self.current_task
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if task is not None and task.sleep_check_interval >= 0 and not task.in_sleep_check:
                due = task.sleep_check_interval - (time.time() - task.last_sleep_check_time)
                if due <= 0:
                    task.in_sleep_check = True
                    try:
                        self.next_frame()
                        task.sleep_check()
                        self.reset_scene()
                    finally:
                        task.last_sleep_check_time = time.time()
                        task.in_sleep_check = False
                    continue
                remaining = min(remaining, due)
            # Pause can be set independently of the stop event.
            self._call(self.context.sleep, min(remaining, .1))

    def wait_condition(self, condition, time_out=0, pre_action=None,
                       post_action=None, settle_time=-1, raise_if_not_found=False):
        self.reset_scene()
        deadline = time.monotonic() + (time_out or self.wait_scene_timeout)
        settling_since = None
        required = self.wait_until_settle_time if settle_time == -1 else settle_time
        while True:
            self.check_enabled()
            if pre_action is not None:
                pre_action()
            self.next_frame(time_out=max(0, deadline - time.monotonic()))
            result = condition()
            self.check_enabled()
            now = time.monotonic()
            if result:
                if required <= 0:
                    return result
                if settling_since is None:
                    settling_since = now
                elif now - settling_since >= required:
                    return result
            else:
                settling_since = None
                if post_action is not None:
                    post_action()
            if time.monotonic() >= deadline:
                if raise_if_not_found:
                    raise self.wait_exception('Condition wait timed out')
                return None

    def _act(self, kind, **values):
        self.check_enabled()
        self.reset_scene(check_enabled=False)
        self._call(self.context.act, kind, **values)
        self.check_enabled()

    def send_key_down(self, key):
        self._act('key_down', key=key)

    def send_key_up(self, key):
        # Releasing existing input must remain possible after stop or pause.
        self.reset_scene(check_enabled=False)
        self.context.device.submit(Action('key_up', {'key': key}))

    def send_key(self, key, down_time=.02):
        self.send_key_down(key)
        try:
            self.sleep(down_time)
        finally:
            self.send_key_up(key)

    def mouse_down(self, x=-1, y=-1, name=None, key='left'):
        if x >= 0 and y >= 0:
            self.move(x, y)
        self._act('button_down', button=key)

    def mouse_up(self, name=None, key='left'):
        self.reset_scene(check_enabled=False)
        self.context.device.submit(Action('button_up', {'button': key}))

    def click(self, x=-1, y=-1, move_back=False, name=None, move=True,
              down_time=.02, key='left'):
        if move_back:
            raise NotImplementedError('Device cursor read/restore is required for move_back')
        self.mouse_down(x if move else -1, y if move else -1, name=name, key=key)
        try:
            self.sleep(down_time)
        finally:
            self.mouse_up(key=key)

    def move(self, x, y):
        self._act('move_client', x=int(x), y=int(y))

    def move_relative(self, dx, dy):
        self._act('move_relative', dx=int(dx), dy=int(dy))

    def input_text(self, text):
        self._act('text', text=text)

    def scroll(self, x, y, count):
        self.move(x, y)
        self._act('scroll', clicks=count)

    def swipe(self, from_x, from_y, to_x, to_y, duration=.5,
              settle_time=0):
        self.move(from_x, from_y)
        self.sleep(.1)
        try:
            self.mouse_down()
            steps = max(1, round(duration / .01))
            for step in range(1, steps + 1):
                fraction = step / steps
                self.move(round(from_x + (to_x - from_x) * fraction),
                          round(from_y + (to_y - from_y) * fraction))
                self.sleep(duration / steps)
            if settle_time > 0:
                self.sleep(settle_time)
        finally:
            self.mouse_up()

    def on_run(self):
        self.check_enabled()

    def should_capture(self):
        return self.connected
