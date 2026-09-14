import re
from ok import TriggerTask, Logger
from src.task.BaseWWTask import BaseWWTask

logger = Logger.get_logger(__name__)


class FastTravelTask(BaseWWTask, TriggerTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {'_enabled': False}
        self.name = "✈️ Fast Travel"
        self.description = 'Auto Click Fast Travel in Map'
        self.match = [re.compile(r'Travel'), '快速旅行', '前往', 'Proceed']

    def disable(self):
        self._ui_tick_navigation = None
        self._travel_requested = False
        return super().disable()

    def run(self):
        from src.task.trigger_navigation import advance
        def source(frame):
            travel = self.find_one('gray_teleport', frame=frame)
            if not travel or self.find_one('remove_custom', frame=frame):
                return None
            results = self.ocr(.7, .89, 1, 1, frame=frame, match=self.match)
            return travel if results else None
        pending = getattr(self, '_ui_tick_navigation', None)
        requested = getattr(self, '_travel_requested', False)
        if requested and (pending is None or pending['step'] == '后台传送确认'):
            handled = advance(self, '后台传送确认', self._travel_confirmation,
                              lambda frame:self.in_team_and_world(frame=frame),
                              identity='travel_confirmation', timeout=120)
            if self.in_team_and_world() and not getattr(self, '_ui_tick_navigation', None):
                self._travel_requested = False
            return handled
        def dispatch(button):
            self._travel_requested = True
            x, y = button.center()
            self.click_relative(x/self.width, y/self.height)
        return advance(self, '后台快速旅行', source,
                       lambda frame:self.in_team_and_world(frame=frame) or (
                           getattr(self, '_travel_requested', False) and self._travel_confirmation(frame)),
                       identity=self._travel_identity, action=dispatch, timeout=120)
