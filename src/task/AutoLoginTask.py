import time
from ok import TriggerTask, Logger
from src.scene.WWScene import WWScene
from src.task.BaseWWTask import BaseWWTask

logger = Logger.get_logger(__name__)


class AutoLoginTask(BaseWWTask, TriggerTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {'_enabled': False}
        self.trigger_interval = 1
        self.name = "🔑 Auto Login"
        self.description = "Auto Login After Game Starts"

    def disable(self):
        self._ui_tick_navigation = None
        self._login_restart_wait_until = 0
        return super().disable()

    def run(self):
        if self.logged_in:
            return False
        restart_until = getattr(self, '_login_restart_wait_until', 0)
        if time.monotonic() < restart_until:
            return False
        if restart_until:
            pending = getattr(self, '_ui_tick_navigation', None)
            old_window = pending['context'][0] if pending else None
            if getattr(self.hwnd, 'hwnd', None) == old_window and not self.in_team_and_world():
                raise RuntimeError('客户端更新后未确认重启，停止自动输入，请检查启动状态')
            self._ui_tick_navigation = None
            self._login_restart_wait_until = 0
        self._login_tick_dispatched = False
        pending = getattr(self, '_ui_tick_navigation', None)
        result = self.wait_login(background=True)
        if pending is not None and pending is getattr(self, '_ui_tick_navigation', None) and not self._login_tick_dispatched:
            # Missing/transition frames still consume the original deadline.
            # A real source observation was already made by wait_login when it
            # found a button; do not count the cached frame twice.
            from src.task.trigger_navigation import advance
            advance(self, pending['step'], lambda frame:None, lambda frame:False, identity=None)
        return bool(result or self._login_tick_dispatched)
