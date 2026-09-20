from ok import TriggerTask, Logger
from src.task.SkipBaseTask import SkipBaseTask

logger = Logger.get_logger(__name__)


class AutoDialogTask(TriggerTask, SkipBaseTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {'_enabled': True}
        self.skip = None
        self.trigger_interval = 0.5
        self.name = "⏭️ Skip Dialog during Quests"

    def disable(self):
        self._ui_tick_navigation = None
        self._skip_requested = False
        self.trigger_interval = 0.5
        return super().disable()

    def _skip_confirmation(self):
        warning = self.find_story_skip_warning()
        self._skip_warning_visible = warning is not None
        if warning:
            if warning.checked is False:
                return warning.checkbox
            return warning.confirm if warning.checked is True else None
        button = self.find_story_skip_confirmation()
        if button:
            return button
        button = self.find_one(['skip_quest_confirm','skip_quest_confirm_new'], threshold=.8)
        if button:
            return button
        if getattr(self, '_skip_requested', False) and self.find_one('skip_dialog_check'):
            return self.find_one(['confirm_btn_hcenter_vcenter','confirm_btn_highlight_hcenter_vcenter'])
        return None

    def run(self):
        from src.task.trigger_navigation import advance
        world = self.in_team_and_world()
        confirm = None if world else self._skip_confirmation()
        warning_unknown = not world and not confirm and getattr(self, '_skip_warning_visible', False)
        confirm_step = {'skip_story_checkbox': '剧情跳过勾选',
                        'skip_story_warning_confirm': '剧情跳过弹窗确认'}.get(
                            getattr(confirm, 'name', None), '剧情跳过确认')
        skip = None if world or confirm or warning_unknown else self.find_skip()
        pending = getattr(self, '_ui_tick_navigation', None)
        # Poll quickly only while a bounded skip operation is in progress.
        # Keep three fresh-frame confirmations; never replace them with a timed click.
        self.trigger_interval = 0.15 if not world and (confirm or skip or pending) else 0.5
        if pending:
            step = pending['step']
            reached = world or (step == '剧情跳过' and confirm is not None) or (
                step != '剧情跳过' and ((confirm is not None and confirm_step != step)
                                      or (confirm is None and skip is not None)))
            button = skip if step == '剧情跳过' else confirm
            def click_pending(box):
                self.click_box(box, after_sleep=0)
                if step == '剧情跳过':
                    self._skip_requested = True
            handled = advance(self, step, lambda frame:None if reached else button,
                              lambda frame:reached, identity=step,
                              action=click_pending, attempts=1 if step in ('剧情跳过', '剧情跳过勾选') else 3,
                              timeout=60, retry_after=60 if step in ('剧情跳过', '剧情跳过勾选') else 3)
            if reached and (world or step in ('剧情跳过确认', '剧情跳过弹窗确认')):
                self._skip_requested=False
            return handled
        if world:
            self._skip_requested=False
            return False
        if confirm or skip:
            step = confirm_step if confirm else '剧情跳过'
            def click(button):
                self.click_box(button, after_sleep=0)
                if step == '剧情跳过':
                    self._skip_requested = True
            return advance(self, step, lambda frame:confirm or skip, lambda frame:False,
                           identity=step, action=click, attempts=1 if step in ('剧情跳过', '剧情跳过勾选') else 3,
                           timeout=60, retry_after=60 if step in ('剧情跳过', '剧情跳过勾选') else 3)
        if warning_unknown:
            return False  # Do not bypass an ambiguous checkbox through legacy confirmation.
        if self.check_skip(nonblocking=True):
            return True
        return self.skip_message()

    def skip_message(self):
        if self.find_one('message', horizontal_variance=0.15):
            if message_dialog := self.find_one('message_dialog', vertical_variance=0.4, horizontal_variance=0.2):
                click = message_dialog.copy(y_offset=2.5 * message_dialog.height)
                click.width = self.width_of_screen(0.63)
                self.click(click, after_sleep=0.2)
                self.log_info(f'click {click}')
                return True
