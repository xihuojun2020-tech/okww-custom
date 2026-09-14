import math
import re
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import List

import numpy as np

from ok import BaseTask, Logger, find_boxes_by_name, og, find_color_rectangles, mask_white, Box
from ok import calculate_color_percentage as calculate_frame_color_percentage
from ok import CannotFindException
import cv2

from src.Labels import Labels
from src.scene.WWScene import WWScene
from src.runtime.game_runtime_errors import FrameUnavailable, GameProcessLost
from src.win32_login_input import send_input_click

logger = Logger.get_logger(__name__)
number_re = re.compile(r'(\d+)')
stamina_re = re.compile(r'(\d+)/(\d+)')
LOGIN_TEXTS = ["登录", re.compile('Log', re.IGNORECASE), '登入']
CONNECT_TEXTS = [
    '点击连接',
    '點擊連接',
    re.compile(r'Click\s+(?:to\s+)?(?:Connect|Start)', re.IGNORECASE),
]
LOGIN_BUTTON_RE = re.compile(r'^(?:登录|登入|登錄|Log\s*In)$', re.IGNORECASE)
CONNECT_BUTTON_RE = re.compile(
    r'^(?:点击连接|點擊連接|Click\s+(?:to\s+)?(?:Connect|Start))$',
    re.IGNORECASE,
)
LOGIN_CLICK_SETTLE_TIME = 4  # seconds; keep below AutoLoginTask trigger_interval (5) so triggers don't overlap
f_white_color = {
    'r': (235, 255),  # Red range
    'g': (235, 255),  # Green range
    'b': (235, 255)  # Blue range
}
processed_feature = False
WIDE_MODE_UI_SCALE = 0.75


def normalize_monthly_hour(value):
    if type(value) is not int:
        raise ValueError('Monthly Card Time 必须是整数 0–23（0 表示午夜）')
    if value == 24:
        return 0
    if not 0 <= value <= 23:
        raise ValueError('Monthly Card Time 必须在 0–23 范围内（0 表示午夜）')
    return value


class BaseWWTask(BaseTask):
    map_zoomed = False

    def navigate_ui(self, step, source, target, *, action=None, timeout=18,
                    attempts=3, identity=None, loading=None, screenshots=False, on_status=None, retry_after=3):
        """Opt-in semantic navigation, never used to repeat resource submissions."""
        from src.task.ui_transition import (Observation, PageState, Policy, present,
                                            run_transition, TransitionContextChanged)
        from src.runtime.navigation_status import publish
        from ok import TaskDisabledException
        executor = self.executor
        old_deadline = getattr(executor, '_ui_transition_deadline', None)
        deadline = min(time.monotonic()+timeout, old_deadline) if old_deadline is not None else time.monotonic()+timeout
        window = getattr(self, 'hwnd', None)
        original_hwnd = getattr(window, 'hwnd', None)
        original_profile = getattr(self, '_verified_profile_id', None)
        original_task = getattr(executor, 'current_task', None)
        selected = None
        size = None
        logged = None
        pictures = 0
        def guard():
            executor.check_enabled()
            self._guard_account_input()
            special = getattr(self, '_guard', None)
            if callable(special):
                special()
            if (getattr(self, '_verified_profile_id', None) != original_profile
                    or getattr(executor, 'current_task', None) is not original_task
                    or getattr(getattr(self, 'hwnd', None), 'hwnd', None) != original_hwnd):
                raise TransitionContextChanged('任务、账号或窗口已变化')
            if window is not None and not getattr(window, 'exists', True):
                raise GameProcessLost('游戏窗口已断开')
        def capture():
            self.next_frame()
            frame = self.require_game_frame()
            return frame, getattr(executor, '_last_frame_time', None) or id(frame)
        def observe(frame):
            nonlocal selected, size
            size = frame.shape[:2]
            reached = present(target(frame))
            selected = source(frame)
            available = present(selected)
            if reached and available:
                return Observation(PageState.UNKNOWN)
            if reached:
                return Observation(PageState.TARGET)
            if not available:
                return Observation(PageState.LOADING if loading and present(loading(frame)) else PageState.UNKNOWN)
            point = None
            if hasattr(selected, 'center'):
                x, y = selected.center()
                point = (x/size[1], y/size[0])
            key = identity(frame) if callable(identity) else identity
            return Observation(PageState.SOURCE, (key, size), point)
        def act(observation):
            if size != (self.height, self.width):
                raise TransitionContextChanged('游戏分辨率已变化，请重新定位')
            if action:
                action(selected)
            elif observation.point is not None:
                self.click_relative(*observation.point)
            else:
                raise TransitionContextChanged('没有明确的导航输入目标')
        def notify(operation, status, machine, frame):
            nonlocal logged, pictures
            if on_status:
                on_status(operation, status, machine, frame)
            stamp = (status, machine.attempts)
            publish(operation, type(self).__name__, step, status, machine.attempts,
                    time.monotonic()-machine.started, machine.deadline-time.monotonic(),
                    max_attempts=attempts, error=machine.error)
            if stamp != logged:
                self.info_set('导航状态', f'{step}：{status}｜输入 {machine.attempts}/{attempts} 次')
                self.log_info(f'ui_transition id={operation} step={step} state={status} attempt={machine.attempts} '
                              f'elapsed={time.monotonic()-machine.started:.2f} '
                              f'size={size} normalized={machine.last_point} error={machine.error}')
                logged = stamp
            if screenshots and frame is not None and pictures < 8 and status in ('准备点击', '已到达目标', '停止/失败'):
                try:
                    safe = frame.copy()
                    safe[:round(len(safe)*.025)] = 0
                    safe[round(len(safe)*.975):] = 0
                    self.screenshot(f'nav_{step}_{operation[:8]}_{machine.attempts}_{status}', frame=safe)
                    pictures += 1
                except TaskDisabledException:
                    raise
                except Exception as error:
                    # Evidence is best effort; never use it to replay game input.
                    self.log_warning(f'导航截图保存失败：{type(error).__name__}')
        executor._ui_transition_deadline = deadline
        try:
            frame, machine = run_transition(capture, observe, act, guard,
                policy=Policy(timeout=timeout, max_attempts=attempts, retry_after=retry_after), deadline=deadline,
                notify=notify, clock=time.monotonic, pause=self.sleep, cancel_errors=(TaskDisabledException,))
            return frame
        finally:
            executor._ui_transition_deadline = old_deadline

    def swipe(self, from_x, from_y, to_x, to_y, duration=.5, after_sleep=.1, settle_time=0):
        from ok import PostMessageInteraction
        interaction = self.executor.interaction
        if not isinstance(interaction, PostMessageInteraction):
            return super().swipe(from_x, from_y, to_x, to_y, duration,
                                 after_sleep=after_sleep, settle_time=settle_time)
        from src.runtime.post_message_drag import drag
        self.executor.reset_scene()
        try:
            drag(interaction, from_x, from_y, to_x, to_y, duration, settle_time, self.sleep)
        finally:
            self.executor.reset_scene()
        if after_sleep:
            self.sleep(after_sleep)

    def ocr(self, *args, **kwargs):
        from src.runtime.ocr_reuse import cached_ocr
        return cached_ocr(self, super().ocr, args, kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.monthly_card_config = self.get_global_config('Monthly Card Config')
        if self.monthly_card_config.get('Monthly Card Time') == 24:
            # Persist the legacy midnight value before the bounded GUI editor
            # can clamp 24 to 23 and change the user's intended schedule.
            self.monthly_card_config['Monthly Card Time'] = 0
        self.char_config = self.get_global_config('Character Config')
        self.key_config = self.get_global_config('Game Hotkey')  # 游戏热键配置
        self.next_monthly_card_start = 0
        self.scene: WWScene | None = None

    def require_game_frame(self):
        """Return a current frame and distinguish capture loss from missing assets."""
        nullable_frame = getattr(self.executor, 'nullable_frame', None)
        if getattr(self.executor, 'debug', False) and callable(nullable_frame):
            debug_frame = nullable_frame()
            if debug_frame is not None:
                return debug_frame
        hwnd = getattr(self, 'hwnd', None)
        connected = getattr(self.executor, 'connected', None)
        if (hwnd is not None and not getattr(hwnd, 'exists', False)) or (
                callable(connected) and not connected()):
            raise GameProcessLost('游戏进程或目标窗口已断开')
        frame = self.executor.frame
        if frame is not None:
            return frame
        raise FrameUnavailable('游戏窗口存在，但当前无法取得截图')

    def get_box_by_name(self, name):
        if isinstance(name, Box) or name in {
                'full_screen', 'right', 'bottom_right', 'top_right', 'left',
                'bottom_left', 'top_left', 'bottom', 'top'}:
            return super().get_box_by_name(name)
        self.require_game_frame()
        return super().get_box_by_name(name)

    def calculate_color_percentage(self, color, box):
        """Calculate against one validated frame, including when ``box`` is already resolved."""
        frame = self.require_game_frame()
        box = self.get_box_by_name(box)
        percentage = calculate_frame_color_percentage(frame, color, box)
        box.confidence = percentage
        self.draw_boxes(box.name, box)
        return percentage

    @property
    def logged_in(self):
        return og.my_app.logged_in

    @logged_in.setter
    def logged_in(self, value):
        og.my_app.logged_in = value

    def is_open_world_auto_combat(self):
        from src.task.AutoCombatTask import AutoCombatTask
        from src.task.TacetTask import TacetTask
        from src.task.DailyTask import DailyTask
        if isinstance(self, AutoCombatTask):
            if not self.in_realm():
                return True
        elif isinstance(self, (TacetTask, DailyTask)):
            return True
        return False

    def zoom_map(self, esc=True):
        if not self.map_zoomed:
            self.log_info('zoom map to max')
            self.map_zoomed = True
            self.send_key('m', after_sleep=1)
            self.click_relative(0.94, 0.33, after_sleep=0.5)
            if esc:
                self.send_key('esc', after_sleep=1)

    def validate(self, key, value):
        message = self.validate_config(key, value)
        if message:
            return False, message
        else:
            return True, None

    def absorb_echo_text(self, ignore_config=False):
        if self.game_lang == 'zh_CN' or self.game_lang == 'en_US' or self.game_lang == 'zh_TW':
            return re.compile(r'(吸收|Absorb)')
        else:
            return None

    @property
    def absorb_echo_feature(self):
        return self.get_feature_by_lang('absorb')

    def get_feature_by_lang(self, feature):
        lang_feature = feature + '_' + self.game_lang
        if self.feature_exists(lang_feature):
            return lang_feature
        else:
            return None

    def set_check_monthly_card(self, next_day=False):
        if self.monthly_card_config.get('Check Monthly Card'):
            now = datetime.now()
            hour = normalize_monthly_hour(self.monthly_card_config.get('Monthly Card Time'))
            next_popup = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if now >= next_popup or next_day:
                next_popup += timedelta(days=1)
            next_monthly_card_start_date_time = next_popup - timedelta(seconds=30)
            self.next_monthly_card_start = next_monthly_card_start_date_time.timestamp()
            logger.info('set next monthly card start time to {}'.format(next_monthly_card_start_date_time))
        else:
            self.next_monthly_card_start = 0

    @property
    def f_search_box(self):
        f_search_box = self.get_box_by_name('pick_up_f_hcenter_vcenter')
        f_search_box = f_search_box.copy(x_offset=-f_search_box.width * 0.3,
                                         width_offset=f_search_box.width * 0.65,
                                         height_offset=f_search_box.height * 6.5,
                                         y_offset=-f_search_box.height * 5,
                                         name='search_dialog')
        return f_search_box

    def find_f_with_claim_text(self):
        return self.find_f_with_text(target_text=[re.compile('领取|領取|Claim', re.IGNORECASE)])

    def find_f_with_text(self, target_text=None):
        f = self.find_one(Labels.pick_up_f_hcenter_vcenter, box=self.f_search_box, threshold=0.8)
        if not f:
            return None
        if not target_text:
            return f

        start = time.time()
        percent = 0.0
        while time.time() - start < 1:
            percent = self.calculate_color_percentage(f_white_color, f)
            if percent > 0.5:
                break
            self.next_frame()
            self.log_debug(f'f white color percent: {percent} wait')
        if percent < 0.5:
            return None

        if target_text:
            search_text_box = f.copy(x_offset=f.width * 5.2, width_offset=f.width * 6, height_offset=4.5 * f.height,
                                     y_offset=-0.8 * f.height, name='search_text_box')
            text = self.ocr(box=search_text_box, match=target_text)
            logger.debug(f'found f with text {text}, target_text {target_text}')
            if text:
                if text[0].y > search_text_box.y + f.height * 1:
                    logger.debug(f'found f with text {text} below, target_text {target_text}')
                    self.scroll_relative(0.5, 0.5, 1)
                return f
        else:
            return f

    def has_target(self):
        return False

    def walk_to_yolo_echo(self, time_out=8, update_function=None, echo_threshold=0.5):
        last_direction = None
        start = time.time()
        no_echo_start = 0
        while time.time() - start < time_out:
            self.next_frame()
            if self.pick_f():
                self.log_debug('pick echo success')
                self._stop_last_direction(last_direction)
                return True
            if self.in_combat():
                self.log_debug('pick echo has_target return fail')
                self._stop_last_direction(last_direction)
                return False
            echos = self.find_echos(threshold=echo_threshold)
            if not echos:
                if no_echo_start == 0:
                    no_echo_start = time.time()
                elif time.time() - no_echo_start > 3:
                    self.log_debug(f'walk front to_echo, no echos found, break')
                    break
                next_direction = 'w'
            else:
                no_echo_start = 0
                echo = echos[0]
                center_distance = echo.center()[0] - self.width_of_screen(0.5)
                threshold = 0.05 if not last_direction else 0.15
                if abs(center_distance) < self.height_of_screen(threshold):
                    if echo.y + echo.height > self.height_of_screen(0.65):
                        next_direction = 's'
                    else:
                        next_direction = 'w'
                elif center_distance > 0:
                    next_direction = 'd'
                else:
                    next_direction = 'a'
            last_direction = self._walk_direction(last_direction, next_direction)
            if update_function is not None:
                update_function()
        self._stop_last_direction(last_direction)

    def _walk_direction(self, last_direction, next_direction):
        if next_direction != last_direction:
            self._stop_last_direction(last_direction)
            if next_direction:
                self.send_key_down(next_direction)
        return next_direction

    def _stop_last_direction(self, last_direction):
        if last_direction:
            self.send_key_up(last_direction)
            self.sleep(0.01)
        return None

    def walk_to_box(self, find_function, time_out=30, end_condition=None, y_offset=0.05, x_threshold=0.07,
                    use_hook=False):
        start = time.time()
        while time.time() - start < time_out:
            if ended := self.do_walk_to_box(find_function, time_out=time_out - (time.time() - start),
                                            end_condition=end_condition, y_offset=y_offset,
                                            x_threshold=x_threshold, use_hook=use_hook):
                return ended

    def do_walk_to_box(self, find_function, time_out=30, end_condition=None, y_offset=0.05, x_threshold=0.07,
                       use_hook=False):
        if find_function:
            self.wait_until(lambda: (not end_condition or end_condition()) or find_function(), raise_if_not_found=True,
                            time_out=time_out)
        last_direction = None
        start = time.time()
        ended = False
        running = False
        last_target = None
        centered = False
        while time.time() - start < time_out:
            self.next_frame()
            if end_condition:
                ended = end_condition()
                if ended:
                    logger.info(f'do_walk_to_box ended {ended}')
                    break
            treasure_icon = find_function()
            if isinstance(treasure_icon, list):
                if len(treasure_icon) > 0:
                    treasure_icon = treasure_icon[0]
                else:
                    treasure_icon = None
            if treasure_icon:
                last_target = treasure_icon
            if last_target is None:
                next_direction = self.opposite_direction(last_direction)
                self.log_info('find_function not found, change to opposite direction')
            else:
                x, y = last_target.center()
                y = max(0, y - self.height_of_screen(y_offset))
                x_abs = abs(x - self.width_of_screen(0.5))
                threshold = 0.04 if not last_direction else x_threshold
                centered = centered or x_abs <= self.width_of_screen(threshold)
                if not centered:
                    if x > self.width_of_screen(0.5):
                        next_direction = 'd'
                    else:
                        next_direction = 'a'
                else:
                    if last_direction == 's':
                        center = 0.45
                    elif last_direction == 'w':
                        center = 0.6
                    else:
                        center = 0.5
                    if y > self.height_of_screen(center):
                        next_direction = 's'
                    else:
                        next_direction = 'w'
            if next_direction != last_direction:
                if last_direction:
                    self.send_key_up(last_direction)
                    self.sleep(0.001)
                last_direction = next_direction
                if next_direction:
                    self.send_key_down(next_direction)
            if running:
                if not self.find_one('on_the_wall', threshold=0.7):
                    self.log_info('not on the wall, stop running')
                    self.mouse_up(key='right')
            else:
                if next_direction == 'w' and self.find_one('on_the_wall', threshold=0.7):
                    self.log_info('on the wall, start running')
                    running = True
                    self.mouse_down(key='right')
                    self.sleep(0.1)
            if use_hook and next_direction == 'w':
                if self.find_one('tool_teleport', 0.75):
                    self.send_key(self.key_config['Tool Key'])
                    self.sleep(3)
                    continue
        if last_direction:
            self.send_key_up(last_direction)
            self.sleep(0.001)
        if running:
            self.send_key_up(self.key_config.get('Dodge Key'))
        if not end_condition:
            return last_direction is not None
        else:
            return ended

    def opposite_direction(self, direction):
        if direction == 'w':
            return 's'
        elif direction == 's':
            return 'w'
        elif direction == 'a':
            return 'd'
        elif direction == 'd':
            return 'a'
        else:
            return 'w'

    def get_direction(self, location_x, location_y, screen_width, screen_height, centered, current_direction):
        """
        Determines the direction ('w', 'a', 's', 'd') closest to the screen center.
        Args:
            location_x: The x-coordinate of the point.
            location_y: The y-coordinate of the point.
            screen_width: The width of the screen.
            screen_height: The height of the screen.
        Returns:
            A string "w", "a", "s", or "d".
        """
        if screen_width <= 0 or screen_height <= 0:
            # Handle invalid dimensions, default based on horizontal position
            return "a" if location_x < screen_width / 2 else "d"
        center_x = screen_width / 2
        center_y = screen_height / 2
        # Calculate vector from point towards the center
        delta_x = center_x - location_x
        delta_y = center_y - location_y
        # Determine dominant direction based on vector magnitude
        direction = None
        if (abs(delta_x) > abs(delta_y) or (not current_direction and abs(delta_x) > 0.05 * screen_height)
                or abs(delta_x) > 0.15 * screen_height):
            # More horizontal movement needed
            return "a" if delta_x > 0 else "d"

            # More vertical movement needed (or equal)
        return "w" if delta_y > 0 else "s"

    def find_treasure_icon(self):
        return self.find_one('treasure_icon', box=self.box_of_screen(0.03, 0.1, 0.97, 0.81, hcenter=True, vcenter=True),
                             threshold=0.8,
                             target_height=720)

    def click(self, x=-1, y=-1, move_back=False, name=None, interval=-1, move=False, down_time=0.01, after_sleep=0,
              key="left"):
        self._guard_account_input()
        if x == -1 and y == -1:
            x = self.width_of_screen(0.5)
            y = self.height_of_screen(0.5)
            move = False
            down_time = 0.01
        else:
            down_time = 0.2
        return super().click(x, y, move_back, name, interval, move=move, down_time=down_time, after_sleep=after_sleep,
                             key=key)

    @contextmanager
    def account_input_guard(self, guard):
        """Keep the same identity guard for nested farming tasks on this executor."""
        executor = getattr(self, 'executor', None)
        if executor is None:
            yield
            return
        previous = getattr(executor, '_account_input_guard', None)
        executor._account_input_guard = previous or guard
        try:
            yield
        finally:
            executor._account_input_guard = previous

    def _guard_account_input(self):
        guard = getattr(getattr(self, 'executor', None), '_account_input_guard', None)
        if callable(guard):
            guard()

    def send_key(self, *args, **kwargs):
        self._guard_account_input()
        return super().send_key(*args, **kwargs)

    def send_key_down(self, *args, **kwargs):
        self._guard_account_input()
        return super().send_key_down(*args, **kwargs)

    def mouse_down(self, *args, **kwargs):
        self._guard_account_input()
        return super().mouse_down(*args, **kwargs)

    def scroll(self, *args, **kwargs):
        self._guard_account_input()
        return super().scroll(*args, **kwargs)

    def check_for_monthly_card(self):
        if self.should_check_monthly_card():
            start = time.time()
            logger.info(f'check_for_monthly_card start check')
            if self.in_combat():
                logger.info(f'check_for_monthly_card in combat return')
                return time.time() - start
            if self.in_team_and_world():
                logger.info(f'check_for_monthly_card in team send sleep until monthly card popup')
                monthly_card = self.wait_until(self.handle_monthly_card, time_out=120, raise_if_not_found=False)
                logger.info(f'wait monthly card end {monthly_card}')
                cost = time.time() - start
                return cost
        return 0

    def in_realm(self):
        return not bool(getattr(self, 'treat_as_not_in_realm', False)) and self.find_one('illusive_realm_exit',
                                                                                         threshold=0.7,
                                                                                         frame_processor=convert_bw) and self.in_team() and not self.find_one(
            'world_earth_icon', threshold=0.55,
            frame_processor=convert_bw)

    def in_world(self):
        return self.find_one('world_earth_icon', threshold=0.55,
                             frame_processor=convert_bw) and self.in_team() and not self.find_one('illusive_realm_exit',
                                                                                                  threshold=0.7,
                                                                                                  frame_processor=convert_bw)

    def in_illusive_realm(self):
        return self.find_one('new_realm_4') and self.in_realm() and self.find_one('illusive_realm_menu', threshold=0.6)

    def walk_until_f(self, direction='w', time_out=1, raise_if_not_found=True, backward_time=0, target_text=None,
                     check_combat=False, running=False):
        logger.info(f'walk_until_f direction {direction} target_text: {target_text}')
        if not self.find_f_with_text(target_text=target_text):
            # 视角朝前
            self.middle_click(after_sleep=0.2)
            if backward_time > 0:
                if self.send_key_and_wait_f('s', raise_if_not_found, backward_time, target_text=target_text,
                                            running=running, check_combat=check_combat):
                    logger.info('walk backward found f')
                    return True
            if self.send_key_and_wait_f(direction, raise_if_not_found, time_out, target_text=target_text,
                                        running=running, check_combat=check_combat):
                logger.info('walk forward found f')
                return True
            return False
        else:
            return True

    def get_stamina(self, time_out=0, screenshot_on_failure=True):
        boxes = self.wait_ocr(0.49, 0.0, 0.92, 0.10, raise_if_not_found=False,
                              match=[number_re, stamina_re], time_out=time_out)
        if not boxes:
            if screenshot_on_failure:
                self.screenshot('stamina_error')
            return -1, -1, -1
        current = -1
        back_up = 0
        for box in boxes:
            if match := stamina_re.search(box.name):
                current = int(match.group(1))
            elif match := number_re.search(box.name):
                back_up = int(match.group(1))
        self.info_set('current_stamina', current)
        self.info_set('back_up_stamina', back_up)
        return current, back_up, current + back_up

    @staticmethod
    def project_stamina_after_use(current, back_up, used):
        current = max(int(current), 0)
        back_up = max(int(back_up), 0)
        remaining_cost = max(int(used), 0)
        from_current = min(current, remaining_cost)
        current -= from_current
        remaining_cost -= from_current
        back_up = max(back_up - remaining_cost, 0)
        return current, back_up, current + back_up

    def get_verified_stamina(self):
        """An unreadable resource bar is not an empty resource bar."""
        for attempt in range(3):
            self.executor.check_enabled()
            self.next_frame()
            self.require_game_frame()
            current, reserve, total = self.get_stamina(time_out=1, screenshot_on_failure=False)
            if min(current, reserve, total) >= 0:
                return current, reserve, total
            self.log_warning(f'体力读数未知，重新识别资源栏 ({attempt + 1}/3)')
            self.sleep(.5)
        self.screenshot('stamina_unreadable', frame=self.require_game_frame())
        raise RuntimeError('体力读数持续未知，未按体力不足结束；账号保留待补跑')

    @staticmethod
    def daily_stamina_budget(activity_ready, once):
        if activity_ready:
            return 0
        return 200 if int(once) == 40 else 180

    @staticmethod
    def should_use_backup_stamina(activity_ready, current, back_up, budget):
        if activity_ready is not False or int(current) >= int(budget):
            return False
        return int(current) + int(back_up) >= int(budget)

    def use_stamina(self, once=60, must_use=0, allow_backup=False, max_claims=2):
        if max_claims not in (1, 2):
            raise ValueError('max_claims must be 1 or 2')
        self.sleep(1)
        if not self.has_claim_stamina():
            raise RuntimeError('未确认体力领取界面，停止消费')
        current, back_up, total = self.get_stamina()
        if min(current, back_up, total) < 0:
            raise RuntimeError('体力读数无效，停止消费')
        requested_before = must_use
        policy = getattr(getattr(self, 'executor', None), '_daily_reserve_policy', None)
        if policy is not None:
            if policy.pending_conversion:
                raise RuntimeError('上次备用转换结果尚未确认，停止所有后续消费')
            if not policy.profile_id:
                allow_backup = False
            if not policy.budget_initialized:
                policy.remaining = max(0, must_use)
                policy.budget_initialized = True
            allow_backup = allow_backup and policy.allowance(current, once) > 0
        if (total if allow_backup else current) < once:
            if policy is not None and current < once and not policy.full_seen:
                policy.refresh_required = True
            self.log_info(f'体力消费停止：current={current}, reserve={back_up}, allow_backup={allow_backup}, remaining={must_use}')
            self.back(after_sleep=1)  # Close the claim prompt before the caller exits.
            return False, 0
        if max_claims == 2 and current >= once * 2 and (must_use <= 0 or must_use >= once * 2):
            used = once * 2
            use_double = True
            logger.info(f"当前体力大于等于双倍, {current} >= {once * 2}")
        elif max_claims == 2 and allow_backup and must_use >= once * 2 and total >= once * 2:
            used = once * 2
            use_double = True
            logger.info(f"当前加备用大于日常剩余所需, 使用双倍, {must_use} >= {once} and {total} >= {once * 2}")
        else:
            used = once
            use_double = False
            logger.info(f"使用单倍体力")
        if use_double:
            btn = self.click_dialog_right_button()
        else:
            btn = self.click_dialog_left_button()
        before_balance = (current, back_up, total)
        if self.wait_feature('gem_add_stamina', horizontal_variance=0.4, vertical_variance=0.05,
                             time_out=2, settle_time=0.5):  # 看是否需要使用备用体力
            if not allow_backup:
                self.log_info('本轮策略禁止使用备用体力，停止刷取')
                self.back(after_sleep=1)
                if self.has_claim_stamina():
                    self.back(after_sleep=1)
                return False, 0
            from src.task.daily_reserve_policy import conversion_amount, conversion_matches
            limit = max(0, min(used, must_use if must_use > 0 else used) - current)
            if policy is not None:
                limit = min(limit, policy.allowance(current, used))
            self.next_frame()
            amount = conversion_amount(self.ocr(0.20, 0.20, 0.80, 0.80))
            if amount is None or amount > limit or amount > back_up:
                self.log_info(f'备用体力转换已拦截：数量={amount}，本次上限={limit}；不接受默认批量转换')
                self.screenshot('reserve_conversion_blocked')
                self.back(after_sleep=1)
                if self.has_claim_stamina():
                    self.back(after_sleep=1)
                return False, 0
            confirm = self.ocr(0.55, 0.60, 0.80, 0.80, match=re.compile(r'^确认$'))
            if len(confirm) != 1:
                self.back(after_sleep=1)
                raise RuntimeError('备用体力确认按钮不唯一，未执行转换')
            if policy is not None and amount > policy.allowance(current, used):
                policy.refresh_required = True
                self.back(after_sleep=1)
                if self.has_claim_stamina():
                    self.back(after_sleep=1)
                self.log_info('备用体力授权在确认前失效，已取消转换')
                return False, 0
            self.log_info(f'备用体力转换请求：current={current}, reserve={back_up}, amount={amount}, limit={limit}')
            # Keep the latch set on an uncertain result, including user interruption.
            if policy is not None:
                policy.pending_conversion = True
            self.screenshot('reserve_conversion_pending')
            self.click(confirm[0], after_sleep=1)
            self.back(after_sleep=1)
            # Observe both balances after conversion, before the final claim click.
            # Conversion must conserve total stamina (allow one regenerated point).
            converted = (-1, -1, -1)
            if self.has_claim_stamina():
                converted = self.get_stamina()
            if not conversion_matches((current, back_up, total), converted, amount):
                self.screenshot('reserve_conversion_unconfirmed')
                raise RuntimeError('备用体力转换余额不符合授权数量，停止消费，不重复确认')
            before_balance = converted
            if policy is not None:
                policy.pending_conversion = False
            self.screenshot('reserve_conversion_confirmed')
            self.log_info(f'备用体力转换已核验：before={(current, back_up, total)}, after={converted}, amount={amount}')
            # Re-find the claim button after the modal closes; do not reuse stale coordinates.
            if use_double:
                self.click_dialog_right_button()
            else:
                self.click_dialog_left_button()

        projected = self.project_stamina_after_use(current, back_up, used)
        current, back_up, total = self._confirm_stamina_used(total, used, before_balance=before_balance)
        must_use -= used
        if policy is not None:
            policy.spend(used)
        logger.info(f'confirmed stamina: current={current} back_up={back_up} total={total}; projected={projected}')
        if requested_before > 0 and must_use <= 0:
            can_continue = False
            logger.info('daily stamina budget completed')
        elif (current if not allow_backup else total) < once:
            logger.info(f"current stamina: {current} not enough to continue")
            can_continue = False
            if policy is not None and not policy.full_seen and policy.remaining >= once:
                policy.refresh_required = True
        else:
            can_continue = True
        return can_continue, used

    def refresh_daily_reserve_after_exit(self):
        policy = getattr(getattr(self, 'executor', None), '_daily_reserve_policy', None)
        if policy is not None and policy.refresh_required:
            policy.refresh_required = False
            if callable(policy.refresh):
                policy.refresh()
            self.log_info('已返回大世界复核每日活跃度；本次未确认的备用领取已取消，不自动重复战斗或转换')

    def get_settlement_stamina(self):
        # The result page hides the top resource bar. Anchor on its retry button,
        # then read only the remaining stamina underneath (never reward quantities).
        if not self.ocr(0.54, 0.80, 0.74, 0.90, match=re.compile(
                r'重新挑[战戰]|再次挑[战戰]|Repeat\s*Challenge|Challenge\s*Again|Retry', re.I)):
            return -1
        boxes = self.ocr(0.57, 0.90, 0.68, 0.95)
        values = []
        for box in boxes:
            text = re.sub(r'\s+', '', box.name)
            match = re.fullmatch(r'(?:(?:剩余|剩餘|Remaining)[:：]?)?(\d{1,3})', text, re.I)
            if match and 0 <= int(match.group(1)) <= 240:
                values.append(int(match.group(1)))
        return values[0] if len(values) == 1 else -1

    def _confirm_stamina_used(self, before_total, used, before_balance=None):
        def confirmed():
            if self.has_claim_stamina():
                return False
            balance = self.get_stamina(time_out=0.5, screenshot_on_failure=False)
            # A short claim can overlap one naturally regenerated stamina point.
            if min(balance) >= 0 and used - 1 <= before_total - balance[2] <= used:
                return balance
            if before_balance is not None and before_balance[0] >= used:
                remaining = self.get_settlement_stamina()
                if remaining >= 0 and used - 1 <= before_balance[0] - remaining <= used:
                    # No reserve was consumed: retain the last observed reserve,
                    # rather than treating its absence on this page as zero.
                    backup = before_balance[1]
                    logger.info(f'confirmed settlement stamina: current={remaining} retained_backup={backup}')
                    return remaining, backup, remaining + backup
            return False

        balance = self.wait_until(confirmed, time_out=8, raise_if_not_found=False)
        if not balance:
            self.screenshot('stamina_claim_unconfirmed', frame=self.frame)
            raise RuntimeError('领奖后未确认体力扣除，停止记账和再次挑战')
        return balance

    def send_key_and_wait_f(self, direction, raise_if_not_found, time_out, running=False, target_text=None,
                            check_combat=False):
        if time_out <= 0:
            return
        self.send_key_down(direction)
        if running:
            self.sleep(0.1)
            self.mouse_down(key='right')
        f_found = self.wait_until(
            lambda: self.find_f_with_text(target_text=target_text) or (check_combat and self.in_combat()),
            time_out=time_out,
            raise_if_not_found=False)
        self.send_key_up(direction)
        if running:
            self.sleep(0.1)
            self.mouse_up(key='right')
        if not f_found:
            if raise_if_not_found:
                raise CannotFindException('cant find the f to enter')
            else:
                logger.warning(f"can't find the f to enter")
                return False
        return f_found

    def run_until(self, condiction, direction, time_out, raise_if_not_found=False, running=False, target=False,
                  post_walk=0):
        if time_out <= 0:
            return
        self.send_key_down(direction)
        if running:
            self.sleep(0.1)
            logger.debug(f'run_until condiction {condiction} direction {direction}')
            self.mouse_down(key='right')
        start = time.time()
        result = None
        while time.time() - start < time_out:
            if result := condiction():
                break
            if target:
                self.middle_click(interval=0.5)
            self.sleep(0.02)
        if result and post_walk:
            self.sleep(post_walk)
        self.send_key_up(direction)
        if running:
            self.sleep(0.1)
            self.mouse_up(key='right')

        if raise_if_not_found and not result:
            raise Exception('wait condition failed while walking')
        return result

    def is_moving(self):
        return False

    def handle_claim_button(self):
        while self.wait_until(self.has_claim, raise_if_not_found=False, time_out=1.5):
            self.sleep(0.5)
            self.send_key('esc')
            self.sleep(0.5)
            logger.info(f"handle_claim_button found a claim reward")
            return True

    def has_claim_stamina(self):
        return not self.in_team()[0] and self.find_one('claim_stamina_sign')

    def has_claim(self):
        return not self.in_team()[0] and self.find_one('claim_cancel_button_hcenter_vcenter', horizontal_variance=0.05,
                                                       vertical_variance=0.1, threshold=0.8)

    def test_absorb(self):
        # self.set_image('tests/images/absorb.png')
        image = cv2.imread('tests/images/absorb.png')
        result = self.executor.ocr_lib(image, use_det=True, use_cls=False, use_rec=True)
        self.logger.info(f'ocr_result {result}')

    def find_echos(self, threshold=0.3):
        """
        Main function to load ONNX model, perform inference, draw bounding boxes, and display the output image.

        Args:
            onnx_model (str): Path to the ONNX model.
            input_image (ndarray): Path to the input image.

        Returns:
            list: List of dictionaries containing detection information such as class_id, class_name, confidence, etc.
        """
        # Load the ONNX model
        ret = og.my_app.yolo_detect(self.frame, threshold=threshold, label=0)

        for box in ret:
            box.y += box.height * 1 / 3
            box.height = 1
        self.draw_boxes("echo", ret)
        return ret

    def yolo_find_all(self, threshold=0.3):
        """
        Main function to load ONNX model, perform inference, draw bounding boxes, and display the output image.

        Args:
            onnx_model (str): Path to the ONNX model.
            input_image (ndarray): Path to the input image.

        Returns:
            list: List of dictionaries containing detection information such as class_id, class_name, confidence, etc.
        """
        # Load the ONNX model
        boxes = og.my_app.yolo_detect(self.frame, threshold=threshold, label=-1)
        ret = sorted(boxes, key=lambda detection: detection.confidence, reverse=True)
        return ret

    def pick_echo(self):
        if self.find_f_with_text(target_text=self.absorb_echo_text()):
            self.send_key('f')
            if not self.handle_claim_button():
                self.log_debug('found a echo picked')
                return True

    def pick_f(self, handle_claim=True):
        if self.find_one('pick_up_f_hcenter_vcenter', box=self.f_search_box, threshold=0.8):
            self.send_key('f', after_sleep=1)
            if not handle_claim:
                return True
            if not self.handle_claim_button():
                self.log_debug('found a echo picked')
                return True

    def is_pick_f(self):
        f = self.find_one('pick_up_f_hcenter_vcenter', box=self.f_search_box,
                          threshold=0.8)
        if not f:
            return False
        dialog_search = f.copy(x_offset=f.width * 3, width_offset=f.width * 1.8, height_offset=f.height * 2,
                               y_offset=-f.height,
                               name='search_dialog')
        dialog_3_dots = self.find_feature('dialog_3_dots', box=dialog_search,
                                          threshold=0.6)
        return bool(dialog_3_dots)

    def walk_to_treasure(self, send_f=True, raise_if_not_found=True):
        self.log_info('start walk_to_treasure')
        if not self.walk_to_box(self.find_treasure_icon, end_condition=self.find_f_with_claim_text):
            if not self.walk_to_box(self.find_treasure_icon, end_condition=self.find_f_with_text):
                raise Exception(f'can not walk to treasure!')
        if send_f:
            self.walk_until_f(time_out=2, backward_time=0, raise_if_not_found=raise_if_not_found)
        self.sleep(1)

    def yolo_find_echo(self, use_color=False, turn=True, update_function=None, time_out=8, threshold=0.5):
        max_echo_count = 0
        if self.pick_echo():
            self.sleep(0.5)
            return True, True
        front_box = self.box_of_screen(0.35, 0.35, 0.65, 0.53, hcenter=True)
        color_threshold = 0.02
        for i in range(4):
            if turn:
                self.center_camera()
            echos = self.find_echos(threshold=threshold)
            max_echo_count = max(max_echo_count, len(echos))
            self.log_debug(f'max_echo_count {max_echo_count}')
            if echos:
                self.log_info(f'yolo found echo {echos}')
                # return self.walk_to_box(self.find_echos, time_out=15, end_condition=self.pick_echo), max_echo_count > 1
                return self.walk_to_yolo_echo(update_function=update_function, time_out=time_out), max_echo_count > 1
            if use_color:
                color_percent = self.calculate_color_percentage(echo_color, front_box)
                self.log_debug(f'pick_echo color_percent:{color_percent}')
                if color_percent > color_threshold:
                    # if self.debug:
                    #     self.screenshot('echo_color_picked')
                    self.log_debug(f'found color_percent {color_percent} > {color_threshold}, walk now')
                    # return self.walk_to_box(self.find_echos, time_out=15, end_condition=self.pick_echo), max_echo_count > 1
                    return self.walk_to_yolo_echo(update_function=update_function), max_echo_count > 1
            if not turn and i == 0:
                return False, max_echo_count > 1
            self.send_key('a', down_time=0.05)
            self.sleep(0.5)

        self.center_camera()
        return False, max_echo_count > 1

    def center_camera(self):
        self.click(0.5, 0.5, down_time=0.2, key='middle')
        self.sleep(1)

    def turn_direction(self, direction):
        if direction != 'w':
            self.send_key(direction, down_time=0.05, after_sleep=0.5)
        self.center_camera()

    def walk_find_echo(self, backward_time=1, time_out=3):
        if self.walk_until_f(time_out=time_out, backward_time=backward_time, target_text=self.absorb_echo_text(),
                             raise_if_not_found=False, check_combat=True):  # find and pick echo
            logger.debug(f'farm echo found echo move forward walk_until_f to find echo')
            return self.pick_f()

    def incr_drop(self, dropped):
        if dropped:
            self.info['Echo Count'] = self.info.get('Echo Count', 0) + 1
            self.info['Echo per Hour'] = round(
                self.info.get('Echo Count', 0) / max(time.time() - self.start_time, 1) * 3600)

    def should_check_monthly_card(self):
        if self.next_monthly_card_start > 0:
            if 0 < time.time() - self.next_monthly_card_start < 120:
                return True
        return False

    def sleep(self, timeout):
        return super().sleep(timeout - self.check_for_monthly_card())

    def wait_in_team_and_world(self, time_out=10, raise_if_not_found=True, esc=False):
        success = self.wait_until(self.in_team_and_world, time_out=time_out, raise_if_not_found=raise_if_not_found,
                                  post_action=lambda: self.back(after_sleep=2) if esc else None)
        if success:
            self.sleep(0.5)
        return success

    def esc_world_confirm(self, send_esc=True):
        if send_esc:
            self.send_key('esc', after_sleep=1)
        self.click_dialog_right_button()
        self.wait_in_team_and_world(time_out=120)

    def click_dialog_right_button(self):
        confirm = self.find_one([
            Labels.confirm_btn_hcenter_vcenter,
            Labels.confirm_btn_highlight_hcenter_vcenter,
        ])
        if not confirm:
            raise CannotFindException(self.tr("can't find dialog right button"))
        self.click(confirm, after_sleep=2)
        return confirm

    def esc_cancel(self, send_esc=True):
        if send_esc:
            self.send_key('esc', after_sleep=1)
        self.click_dialog_left_button()
        self.wait_in_team_and_world(time_out=120)

    def click_dialog_left_button(self) -> Box:
        cancel = self.find_one([
            Labels.cancel_button_hcenter_vcenter,
            Labels.cancel_button_highlight_hcenter_vcenter,
        ])
        if not cancel:
            raise CannotFindException(self.tr("can't find dialog left button"))
        self.click(cancel, after_sleep=2)
        return cancel

    def ensure_main(self, esc=True, time_out=30):
        self.info_set('current task', f'wait main esc={esc}')
        if not self.logged_in:
            time_out = 600
        if not self.wait_until(lambda: self.is_main(esc=esc), time_out=time_out, raise_if_not_found=False):
            raise Exception('Please start in game world and in team!')
        self.sleep(0.5)
        self.info_set('current task', f'in main esc={esc}')

    def is_main(self, esc=True):
        if self.in_team_and_world():
            self.logged_in = True
            if self.in_realm():
                self.esc_world_confirm()
            return True
        if self.wait_login():
            return False
        if self.handle_monthly_card():
            return False
        if esc:
            self.log_debug('main esc')
            self.back(after_sleep=2)
            return False

    def _main_window_identity(self):
        """Return the trusted PC game HWND and PID, or ``(0, 0)``."""
        try:
            import win32gui
            import win32process

            hwnd = int(getattr(getattr(self, 'hwnd', None), 'hwnd', 0) or 0)
            if not hwnd or not win32gui.IsWindow(hwnd):
                return 0, 0
            pid = int(win32process.GetWindowThreadProcessId(hwnd)[1] or 0)
            return (hwnd, pid) if pid else (0, 0)
        except Exception:
            return 0, 0

    def _main_box_center_screen(self, box):
        """Map a box from the current WGC frame to a live screen point."""
        try:
            origin = self.hwnd.get_capture_origin()
            if not origin:
                return None
            return (
                int(origin[0] + box.x + box.width / 2),
                int(origin[1] + box.y + box.height / 2),
            )
        except Exception:
            return None

    def _click_login_box(self, target, after_sleep=0.5):
        """Click a PC login box through the verified SendInput boundary."""
        box = target[0] if isinstance(target, (list, tuple)) and target else target
        if box is None:
            return False
        executor = getattr(self, 'executor', None)
        check_enabled = getattr(executor, 'check_enabled', None)
        if callable(check_enabled) and check_enabled() is False:
            return False
        hwnd, pid = self._main_window_identity()
        point = self._main_box_center_screen(box)
        if not hwnd or not pid or point is None:
            self.log_warning('登录点击未投递：无法确认主窗口、PID 或当前 WGC 坐标')
            return False
        delivery = send_input_click(hwnd, pid, point)
        self._last_login_click_delivery = delivery
        if not delivery.delivered:
            self.log_warning(
                f'登录点击未投递：{delivery.reason}；目标HWND={delivery.target_hwnd or "?"}，'
                f'前台HWND={delivery.foreground_hwnd or "?"}，命中HWND={delivery.hit_hwnd or "?"}'
            )
            return False
        if after_sleep:
            self.sleep(after_sleep)
        return True

    def _exact_login_button_boxes(self, texts, boundary=None):
        """Return only complete login-button labels, never status text."""
        candidates = self.find_boxes(texts, boundary=boundary, match=LOGIN_TEXTS) or []
        return [
            box for box in candidates
            if LOGIN_BUTTON_RE.fullmatch((getattr(box, 'name', '') or '').strip())
        ]

    def _connect_button_boxes(self, texts, boundary=None):
        """Return exact title-screen connect entries inside the requested area."""
        candidates = self.find_boxes(texts, boundary=boundary, match=CONNECT_TEXTS) or []
        return [
            box for box in candidates
            if CONNECT_BUTTON_RE.fullmatch((getattr(box, 'name', '') or '').strip())
        ]

    def wait_login(self, background=False):
        click = self._login_click_tick if background else self._click_login_box
        if not self.logged_in:
            if self.in_team_and_world():
                if background and getattr(self, '_ui_tick_navigation', None):
                    from src.task.trigger_navigation import advance
                    pending = self._ui_tick_navigation
                    advance(self, pending['step'], lambda frame:None, lambda frame:True, identity=None)
                if background and getattr(self, '_login_monthly_seen', False):
                    self.set_check_monthly_card(next_day=True)
                    self._login_monthly_seen = False
                self.logged_in = True
                return True
            if background:
                if self.find_monthly_card() is not None:
                    button = self.box_of_screen(.49,.88,.51,.90, name='monthly_card')
                    click(button, after_sleep=0)
                    return False
            else:
                self.handle_monthly_card()
            if login_close := self.find_one('login_close', horizontal_variance=0.15, vertical_variance=0.1):
                if click(login_close, after_sleep=1):
                    self.log_info('关闭公告!')
                return False
            texts = self.ocr(log=self.debug)
            if background and getattr(self, '_login_monthly_seen', False):
                dismiss = self.find_boxes(texts, match=[re.compile(r'^点击空白处继续$'),
                                                      re.compile(r'^點擊空白處繼續$')])
                if dismiss:
                    click(dismiss, after_sleep=0)
                    return False

            login_box = self.box_of_screen(0.3, 0.3, 0.7, 0.7, hcenter=True, vcenter=True)
            connect_box = self.box_of_screen(0.25, 0.75, 0.75, 1.0)
            if connect := self._connect_button_boxes(texts, boundary=connect_box):
                if click(connect, after_sleep=1):
                    self.log_info('点击连接入口!')
                return False
            if login := self._exact_login_button_boxes(texts, boundary=login_box):
                if not self.find_boxes(texts, boundary=login_box, match="+86"):
                    # the game may be auto logging in with saved credentials, wait and
                    # confirm the login button is still there before clicking (#1356)
                    if background:
                        click(login, after_sleep=1)
                        return False
                    self.sleep(LOGIN_CLICK_SETTLE_TIME)
                    texts = self.ocr(log=self.debug)
                    login = self._exact_login_button_boxes(texts, boundary=login_box)
                    if login and not self.find_boxes(texts, boundary=login_box,
                                                     match="+86"):
                        if click(login, after_sleep=1):
                            self.log_info('点击登录按钮!')
                return False
            if agree := self.find_boxes(texts, boundary=login_box, match="同意"):
                self.log_debug(f'found agree {agree}')
                if self.find_boxes(texts, boundary=login_box, match=re.compile("隐私")):
                    if click(agree, after_sleep=1):
                        self.log_info('点击同意按钮!')
                return False
            if self.find_boxes(texts, match=[re.compile("游戏即将重启"), re.compile('遊戲即將重啟')]):
                if not background:
                    self.sleep(0.2)
                self.log_info('游戏更新成功, 游戏即将重启')
                click(
                    self.find_boxes(texts, match=["确认", "確認"]), after_sleep=60)
                if background:
                    return False  # Reconnection is observed on later ticks, never a 90s sleep.
                result = self.start_device()
                self.log_info(f'start_device end {result}')
                self.sleep(30)
                return False

            if start := self.find_boxes(texts, boundary='bottom_right', match=["开始游戏", re.compile("进入游戏")]):
                if not self.find_boxes(texts, boundary='bottom_right', match=LOGIN_TEXTS):
                    if click(start, after_sleep=0):
                        self.log_info(f'点击开始游戏! {start}')
                    return False
            if switch_login := self.find_one(Labels.switch_account, vertical_variance=0.1, threshold=0.7):
                if boxes := self.find_boxes(texts, boundary=self.box_of_screen(0.37, 0.63, 0.63, 0.99, hcenter=True,
                                                                               vcenter=True)):
                    self.log_info(f'wait_login {switch_login} {boxes}')
                    click(switch_login, after_sleep=3)
                    return False

    def _login_click_tick(self, target, after_sleep=0):
        from src.task.trigger_navigation import advance
        box = target[0] if isinstance(target, (list, tuple)) and target else target
        if box is None:
            return False
        stage = '自动登录：' + str(box.name)
        pending = getattr(self, '_ui_tick_navigation', None)
        if pending and pending['step'] != stage:
            # A different, positively classified login page proves the previous
            # navigation ended. Do not also input on the new page in this tick.
            return advance(self, pending['step'], lambda frame:None, lambda frame:True, identity=None)
        def dispatch(button):
            if not self._click_login_box(button, after_sleep=0):
                raise RuntimeError('自动登录输入未投递，停止本步')
            self._login_tick_dispatched = True
            if button.name == 'monthly_card':
                self._login_monthly_seen = True
            if after_sleep >= 60:
                self._login_restart_wait_until = time.monotonic()+after_sleep
        return advance(self, stage, lambda frame:box, lambda frame:False,
                       identity=stage, action=dispatch,
                       attempts=1 if box.name == 'monthly_card' or after_sleep >= 60 else 3,
                       initial_delay=LOGIN_CLICK_SETTLE_TIME if LOGIN_BUTTON_RE.fullmatch(str(box.name)) else 0)

    def in_team_and_world(self, frame=None):
        return self.in_team(frame=frame)[
            0]  # and self.find_one(f'gray_book_button', threshold=0.7, canny_lower=50, canny_higher=150)

    def get_angle_between(self, my_angle, angle):
        if my_angle > angle:
            to_turn = angle - my_angle
        else:
            to_turn = -(my_angle - angle)
        if to_turn > 180:
            to_turn -= 360
        elif to_turn < -180:
            to_turn += 360
        return to_turn

    def get_my_angle(self):
        return self.rotate_arrow_and_find()[0]

    def rotate_arrow_and_find(self):
        original_mat = self.get_feature_by_name('arrow').mat
        # One template generation per content/size, retaining only the latest
        # set. Resolution changes and in-place feature edits invalidate it.
        key = (original_mat.shape, original_mat.dtype.str, original_mat.tobytes())
        cached = getattr(self, '_arrow_rotation_cache', None)
        if cached is None or cached[0] != key:
            h, w = original_mat.shape[:2]
            center = (w // 2, h // 2)
            templates = tuple(cv2.warpAffine(original_mat, cv2.getRotationMatrix2D(center, -angle, 1.0), (w, h))
                              for angle in range(360))
            self._arrow_rotation_cache = key, templates
        else:
            templates = cached[1]
        max_conf, max_angle, max_target = 0, 0, None
        target_box = self.get_box_by_name('arrow')
        for angle, template in enumerate(templates):
            target = self.find_one(box=target_box, template=template, threshold=0.01)
            if target and target.confidence > max_conf:
                max_conf, max_angle, max_target = target.confidence, angle, target
        return max_angle, max_target

    def get_mini_map_turn_angle(self, feature, threshold=0.72, x_offset=0, y_offset=0):
        box = self.get_box_by_name('box_minimap')
        target = self.find_one(feature, box=box, threshold=threshold)
        if not target:
            self.log_info(f'Can not find {feature} on minimap')
            return None
        else:
            self.log_debug(f'found {box} on minimap')
        target.x += target.width * x_offset
        target.y += target.height * y_offset
        direction_angle = calculate_angle_clockwise(box, target)
        my_angle = self.get_my_angle()
        to_turn = self.get_angle_between(my_angle, direction_angle)
        self.log_info(f'angle: {my_angle}, to_turn: {to_turn}')
        return to_turn

    def _stop_movement(self, current_direction):
        """Releases keys and mouse to stop character movement."""
        if current_direction is not None:
            self.mouse_up(key='right')
            self.send_key_up(current_direction)

    def _navigate_based_on_angle(self, angle, current_direction, current_adjust):
        """
        Core navigation logic to adjust movement based on a target angle.
        This contains the shared logic from the original functions.

        Returns a tuple: (new_direction, new_adjust, should_continue)
        - new_direction: The updated movement direction ('w', 'a', 's', 'd').
        - new_adjust: The updated adjustment state.
        - should_continue: A boolean indicating if the calling loop should `continue`.
        """
        # 1. Handle minor adjustments if already moving forward
        if current_direction == 'w':
            if 10 <= angle <= 80:
                minor_adjust = 'd'
            elif -80 <= angle <= -10:
                minor_adjust = 'a'
            else:
                minor_adjust = None

            if minor_adjust:
                self.send_key_down(minor_adjust)
                self.sleep(0.1)
                self.middle_click(down_time=0.1)
                self.send_key_up(minor_adjust)
                self.sleep(0.01)
                # Tell the caller to continue to the next loop iteration
                return current_direction, current_adjust, True

        # 2. Clean up any previous adjustments
        if current_adjust:
            self.send_key_up(current_adjust)
            current_adjust = None

        # 3. Determine the major new direction based on the angle
        if -45 <= angle <= 45:
            new_direction = 'w'
        elif 45 < angle <= 135:
            new_direction = 'd'
        elif -135 < angle <= -45:
            new_direction = 'a'
        else:
            new_direction = 's'

        # 4. Change direction if needed
        if current_direction != new_direction:
            self.log_info(f'changed direction {angle} {current_direction} -> {new_direction}')
            if current_direction:
                self.mouse_up(key='right')
                self.send_key_up(current_direction)
                self.wait_until(self.in_combat, time_out=0.2)
            self.turn_direction(new_direction)
            self.send_key_down('w')
            self.wait_until(self.in_combat, time_out=0.2)
            self.mouse_down(key='right')
            current_direction = 'w'  # After turning, we always move forward
            self.wait_until(self.in_combat, time_out=1)

        return current_direction, current_adjust, False

    def in_team(self, frame=None):
        c1 = self.find_one('char_1_text', threshold=0.8, frame=frame)
        c2 = self.find_one('char_2_text', threshold=0.8, frame=frame)
        c3 = self.find_one('char_3_text', threshold=0.8, frame=frame)
        arr = [c1, c2, c3]
        # logger.debug(f'in_team check {arr}')
        current = -1
        exist_count = 0
        for i in range(len(arr)):
            if arr[i] is None:
                if current == -1:
                    current = i
            else:
                exist_count += 1
        if exist_count == 2 or exist_count == 1:
            self.logged_in = True
            return True, current, exist_count + 1
        if exist_count == 0 and self._single_member_hud(frame):
            self.logged_in = True
            return True, 0, 1
        return False, -1, exist_count + 1

    def _single_member_hud(self, frame=None):
        # Missing switch digits alone also occurs in menus/loading/cutscenes.
        # Require the player's health HUD and exactly the first party health bar.
        # The companion portrait in story quests has no party health bar.
        kwargs = dict(frame=frame, threshold=0.75, use_gray_scale=True,
                      horizontal_variance=0.002, vertical_variance=0.002)
        if not self.find_one('solo_player_health', **kwargs):
            return False
        kwargs['mask_function'] = self._party_health_outline_mask
        first_health = self.find_one('solo_party_health', **kwargs)
        for top in (0.382, 0.506):
            box = self.box_of_screen(0.907, top, 0.962, top + 0.023)
            if self.find_one('solo_party_health', box=box, **kwargs):
                return False
        if first_health:
            return True
        # The translucent party bar includes the world behind it; do not make
        # that small template the only positive cue for a solo character.
        # Reuse registered full-size portraits (story companion icons are smaller).
        from src.char.CharFactory import char_names
        names = list(char_names)
        def portrait(index):
            return self.find_one(names, box=self.get_box_by_name(f'box_char_{index}'),
                                 threshold=0.8, frame=frame)
        return bool(portrait(1) and not portrait(2) and not portrait(3))

    @staticmethod
    def _party_health_outline_mask(template):
        # Match the frame, not the fill: current HP may be anywhere from 0–100%.
        height, width = template.shape[:2]
        mask = np.full((height, width), 255, dtype=np.uint8)
        mask[round(height * 0.25):round(height * 0.85),
             round(width * 0.05):round(width * 0.95)] = 0
        return mask

    def find_monthly_card(self):
        return self.find_one('monthly_card', threshold=0.65, horizontal_variance=0.05, vertical_variance=0.05)

    def handle_monthly_card(self):
        monthly_card = self.find_monthly_card()
        # self.screenshot('monthly_card1')
        if monthly_card is not None:
            # self.screenshot('monthly_card1')
            self.log_info('monthly_card found click')
            self.click_relative(0.50, 0.89)
            self.sleep(2)
            # self.screenshot('monthly_card2')
            self.click_relative(0.50, 0.89)
            self.sleep(2)
            self.wait_until(self.in_team_and_world, time_out=10,
                            post_action=lambda: self.click_relative(0.50, 0.89, after_sleep=1))
            # self.screenshot('monthly_card3')
            self.set_check_monthly_card(next_day=True)
        # logger.debug(f'check_monthly_card {monthly_card}')
        return monthly_card is not None

    @property
    def game_lang(self):
        if '鸣潮' in self.hwnd_title or self.is_browser():
            return 'zh_CN'
        elif 'Wuthering' in self.hwnd_title:
            return 'en_US'
        elif '鳴潮' in self.hwnd_title:
            return 'zh_TW'
        return 'unknown_lang'

    def open_esc_menu(self):
        self.send_key_down('alt')
        self.sleep(0.05)
        self.click_relative(0.95, 0.04)
        self.send_key_up('alt')
        self.sleep(0.5)

    BOOK_TABS = {'target': '培养目标', 'ningsu': '凝素领域', 'moni': '模拟领域', 'qiangdi': '讨伐强敌',
                 'wuyin': '无音清剿', 'zhange': '战歌重奏', 'canxiang': '残象聚落'}

    def _book_tab(self, name, frame):
        titles = self.ocr(.02, .02, .32, .10, frame=frame)
        if not any(str(box.name).strip() == '素材获取' for box in titles):
            return None
        boxes = self.ocr(.14, .12, .35, .90, frame=frame)
        matches = [box for box in boxes if str(box.name).strip() == self.BOOK_TABS[name]]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _book_tab_highlight(frame, button):
        # Full guidebook fixtures: selected card is pale, other cards are dark.
        height, width = frame.shape[:2]
        center_y = (button.y + button.height/2)/height
        crop = frame[max(0, round((center_y-.025)*height)):min(height, round((center_y+.025)*height)),
                     round(.27*width):round(.29*width)]
        if not crop.size:
            return False
        return float(np.mean(np.min(crop, axis=2) > 150)) >= .75

    def _unselected_book_tab(self, name, frame):
        button = self._book_tab(name, frame)
        return button if button is not None and not self._book_tab_highlight(frame, button) else None

    def _book_tab_ready(self, name, frame):
        button = self._book_tab(name, frame)
        if button is None or not self._book_tab_highlight(frame, button):
            return False
        controls = self.ocr(.82, .16, .97, .91, frame=frame)
        return any(str(box.name).strip() in ('前往', '直接挑战', '挑战') for box in controls)

    def open_boss_book(self, name, after_sleep=2):
        self.log_info(f'open_boss_book {name}')
        if self.game_lang == 'zh_CN' and name in self.BOOK_TABS:
            self.navigate_ui('指南页签：'+self.BOOK_TABS[name],
                lambda frame:self._unselected_book_tab(name, frame),
                lambda frame:self._book_tab_ready(name, frame), identity=name)
            return
        # Other locales and the scrolled nightmare entry retain their legacy flow.
        x = 0.24
        self.sleep(0.4)
        if name == 'ningsu':
            y = 0.4
        elif name == 'moni':
            y = 0.3
        elif name == 'qiangdi':
            y = 0.49
        elif name == 'wuyin':
            y = 0.73
        elif name == 'zhange':
            y = 0.61
        elif name == 'canxiang':
            y = 0.83
        elif name == 'mengyan':
            self.click_relative(0.356, 0.882, after_sleep=after_sleep)
            y = 0.86
        else:
            raise Exception(f'unknown_lang {name}')
        self.click_relative(x, y, after_sleep=after_sleep, name=name)

    def openF2Book(self, feature="gray_book_all_monsters"):
        if hasattr(self, 'reset_to_false'):
            self.reset_to_false('opening book')
        self.ensure_main()
        book_key = self.key_config.get('Guidebook Key', self.key_config.get('索拉指南', 'f2'))
        inputs = 0
        def open_book(_):
            nonlocal inputs
            inputs += 1
            if inputs == 1:
                self.send_key(book_key)
            else:
                # The icon is a fallback only while the world HUD is still proven.
                try:
                    self.send_key_down('alt')
                    self.sleep(.05)
                    self.click_relative(.77, .05)
                finally:
                    self.send_key_up('alt')

        self.navigate_ui('打开索拉指南',
            lambda frame: self.in_team_and_world(frame=frame),
            lambda frame: self.find_one(feature, box='box_gray_book', threshold=.3, frame=frame),
            action=open_book, identity=feature)
        # Tab selection is an existing single action: the gray icon does not
        # prove which content tab is selected, so it is not automatically retried.
        gray_book_boss = self.wait_book(feature)
        if gray_book_boss is None:
            raise CannotFindException('指南页签消失，停止点击')
        self.click_box(gray_book_boss, after_sleep=1.5)
        return gray_book_boss

    def _travel_button(self, frame):
        self._check_travel_unavailable(frame)
        for name in ('fast_travel_custom', 'gray_teleport'):
            if button := self.find_one(name, threshold=.7, frame=frame):
                return button
        return None

    def _check_travel_unavailable(self, frame):
        texts = self.ocr(.65, .55, 1, .95, frame=frame) or []
        message = ''.join(str(box.name) for box in texts)
        if re.search(r'无法快速到达|無法快速到達|无法传送|無法傳送|cannot.*(?:travel|teleport)', message, re.I):
            target = ' / '.join(self._travel_identity(frame))
            raise RuntimeError(f'目标不可快速到达：{target}；保留原目标待补跑，不替换账号设置')

    def wait_book_target_state(self):
        def detect():
            frame = self.require_game_frame()
            self._check_travel_unavailable(frame)
            # A map close icon can match team_close. Only the challenge action
            # positively identifies formation; never use the shared X icon.
            return (self.find_one(['fast_travel_custom', 'gray_teleport', 'remove_custom'], frame=frame)
                    or self._team_start_button(frame) or self._single_challenge_entry(frame))
        return self.wait_until(detect, time_out=10, settle_time=.5, raise_if_not_found=True)

    def _single_challenge_entry(self, frame):
        boxes = self.ocr(.7, .78, 1, .98, frame=frame,
                         match=re.compile(r'^(?:单人挑战|單人挑戰|Solo Challenge)$', re.I)) or []
        if boxes:
            boxes[0].name = 'team_entry'
            return boxes[0]

    def _team_start_button(self, frame):
        if button := self.find_one('team_start_challenge', frame=frame):
            return button
        boxes = self.ocr(.7, .78, 1, .98, frame=frame,
                         match=re.compile(r'^(?:开启挑战|開啟挑戰|开始挑战|開始挑戰|Start Challenge)$', re.I)) or []
        if boxes:
            boxes[0].name = 'team_start_challenge'
            return boxes[0]

    def _travel_identity(self, frame):
        names = tuple(str(box.name).strip() for box in self.ocr(.65,.10,.97,.32,frame=frame)
                      if str(box.name).strip())
        if not names:
            raise RuntimeError('无法确认传送目标名称，停止输入')
        return names

    def _travel_confirmation(self, frame):
        if not self.find_one('skip_dialog_check', frame=frame):
            return None
        message = ''.join(str(box.name) for box in self.ocr(.2,.3,.8,.6,frame=frame))
        if not re.search(r'传送|傳送|快速旅行|Teleport|Travel', message, re.IGNORECASE):
            return None
        return self.find_one(['confirm_btn_hcenter_vcenter','confirm_btn_highlight_hcenter_vcenter'], frame=frame)

    def _navigate_travel(self):
        submitted = False
        def click(button):
            nonlocal submitted
            submitted = True
            self.click(button)
        def source(frame):
            button = self._travel_button(frame)
            if button is None and self.find_one('remove_custom', frame=frame):
                raise RuntimeError('当前目标只有移除标记，不能作为传送操作')
            return button
        frame = self.navigate_ui('传送目标', source,
            lambda frame:submitted and (self.in_team_and_world(frame=frame) or self._travel_confirmation(frame)),
            action=click, identity=self._travel_identity, timeout=120)
        if submitted and self._travel_confirmation(frame):
            self.navigate_ui('传送确认',self._travel_confirmation,
                lambda frame:self.in_team_and_world(frame=frame) and not self._travel_confirmation(frame),
                identity='travel_confirmation', timeout=120)
        return True

    def click_traval_button(self):
        frame = self.require_game_frame()
        if self._travel_button(frame) is None:
            if self.find_one('remove_custom', frame=frame):
                raise RuntimeError('当前仅有移除标记，不能传送')
            return False
        return self._navigate_travel()

    def click_confirm(self, timeout=1):
        return self.wait_click_feature(
            ['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter'],
            relative_x=-1, raise_if_not_found=False,
            threshold=0.6,
            time_out=timeout)

    def click_skip_dialog_confirm(self):
        skip_dialog_confirm = self.find_one(
            ['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter'],
            horizontal_variance=0.1,
            vertical_variance=0.1,
        )
        if not skip_dialog_confirm:
            return False

        skip_dialog_check = self.find_one(
            'skip_dialog_check',
            horizontal_variance=0.1,
            vertical_variance=0.1,
        )
        if not skip_dialog_check:
            check_feature = self.get_feature_by_name('skip_dialog_check')
            wide_check_template = cv2.resize(
                check_feature.mat,
                (0, 0),
                fx=WIDE_MODE_UI_SCALE,
                fy=WIDE_MODE_UI_SCALE,
                interpolation=cv2.INTER_AREA,
            )
            skip_dialog_check = self.find_one(
                'skip_dialog_check',
                box=self.box_of_screen(0.35, 0.45, 0.55, 0.65),
                template=wide_check_template,
            )
        if not skip_dialog_check:
            return False

        logger.info('confirm dialog exists, click confirm')
        self.sleep(0.5)
        self.click(skip_dialog_check)
        self.sleep(0.5)
        self.click(skip_dialog_confirm)
        self.sleep(0.2)
        return True

    def wait_click_skip_dialog_confirm(self, time_out=3):
        return self.wait_until(
            self.click_skip_dialog_confirm,
            time_out=time_out,
            raise_if_not_found=False,
        )

    def click_team_challenge(self):
        def source(frame):
            self._check_travel_unavailable(frame)
            return self._single_challenge_entry(frame)
        frame = self.navigate_ui('确认编队挑战入口', source, self._team_start_button, timeout=15)
        button = self._team_start_button(frame)
        if button is None:
            raise CannotFindException('编队挑战按钮消失，停止输入')
        self.click(button, after_sleep=1)
        self.wait_click_skip_dialog_confirm()

    def wait_click_travel(self):
        return self._navigate_travel()

    def wait_book(self, feature="gray_book_all_monsters", time_out=3):
        gray_book_boss = self.wait_until(
            lambda: self.find_one(feature, box='box_gray_book',
                                  threshold=0.3),
            time_out=time_out, settle_time=1)
        logger.info(f'found gray_book_boss {gray_book_boss}')
        # if self.debug:
        #     self.screenshot(feature)
        return gray_book_boss

    def check_main(self):
        if not self.in_team()[0]:
            self.click_relative(0, 0)
            self.send_key('esc')
            self.sleep(1)
            if not self.in_team()[0]:
                raise Exception('must be in game world and in teams')
        return True

    def _find_book_scroll_top(self):
        box = self.box_of_screen(0.969, 0.191, 0.978, 0.271, name="bar")
        self.draw_boxes(boxes=box, color="blue")
        min_width = self.width_of_screen(5 / 2560)
        min_height = self.height_of_screen(10 / 1440)
        boxes = find_color_rectangles(self.frame, book_bar_color, min_width, min_height, threshold=0.8, box=box)
        if not boxes:
            return 424 / 2160
        bar = boxes[0]
        self.draw_boxes(boxes=bar, color="red")
        bar_top = bar.y / self.height
        return bar_top

    def click_on_book_target(self, serial_number: int, total_number: int, structure: list[int] = None):
        def get_cross_count(structure, sn):
            current_sum = 0
            cross_count = 0
            for s in structure:
                current_sum += s
                if sn > current_sum:
                    cross_count += 1
                else:
                    break
            return cross_count

        self.sleep(0.5)
        bar_bottom = 0.8806
        bar_x = 0.9730
        separator = 0.01
        cross_count = 0
        container_max_rows = 4
        target_index = -1

        bar_top = self._find_book_scroll_top()

        if serial_number <= container_max_rows:
            target_index = serial_number - 1
        else:
            container_h = bar_bottom - bar_top
            if structure:
                cross_count = get_cross_count(structure, serial_number)
                cross_count += 1
                container_h -= len(structure) * separator
            item_h = container_h / total_number
            height = item_h * serial_number
            to_click_y = min(bar_top + height + cross_count * separator, bar_bottom)
            self.click(bar_x, to_click_y, after_sleep=1)
        btns = self.find_feature('boss_proceed', box=self.box_of_screen(0.9113, 0.229, 0.9613, 0.861), threshold=0.8)
        if not btns:
            raise Exception("can't find boss_proceed")
        if target_index > -1:
            if target_index < len(btns):
                target = btns[target_index]
            else:
                # Fallback: not enough visible rows, scroll to bring target into view
                container_h = bar_bottom - bar_top
                if structure:
                    cross_count = get_cross_count(structure, serial_number)
                    cross_count += 1
                    container_h -= len(structure) * separator
                item_h = container_h / total_number
                height = item_h * serial_number
                to_click_y = min(bar_top + height + cross_count * separator, bar_bottom)
                self.click(bar_x, to_click_y, after_sleep=1)
                btns = self.find_feature('boss_proceed', box=self.box_of_screen(0.9113, 0.229, 0.9613, 0.861), threshold=0.8)
                if not btns:
                    raise Exception("can't find boss_proceed after scroll")
                target = max(btns, key=lambda box: box.y)
        else:
            target = max(btns, key=lambda box: box.y)
        self.draw_boxes(boxes=target, color="red")
        self.click(target, after_sleep=1)
        feature = self.wait_book_target_state()
        if feature.name == 'remove_custom':
            raise RuntimeError('指南目标没有可用传送或挑战入口，停止；未移除标记')
        return feature.name in ('team_start_challenge', 'team_entry')

    def change_time_to_night(self):
        logger.info('change time to night')
        self.send_key("esc")
        self.sleep(1)
        self.click_relative(0.71, 0.96)
        self.sleep(2)
        self.click_relative(0.19, 0.14)
        self.sleep(1)

        # 调整时间到晚上
        for _ in range(3):
            self.click_relative(0.82, 0.53)
            self.sleep(1)

        self.click_relative(0.52, 0.90)
        self.sleep(6)
        self.send_key("esc")
        self.sleep(1)
        self.send_key("esc")
        self.sleep(1)

    def jump(self, after_sleep=0.01):
        self.send_key(self.key_config.get('Jump Key'), after_sleep=after_sleep)


book_bar_color = {
    "r": (190, 255),
    "g": (190, 255),
    "b": (190, 255),
}

echo_color = {
    'r': (200, 255),  # Red range
    'g': (150, 220),  # Green range
    'b': (130, 170)  # Blue range
}


def calculate_angle_clockwise(box1, box2):
    """
    Calculates angle (radians) from horizontal right to line (x1,y1)->(x2,y2).
    Positive clockwise, negative counter-clockwise.
    """
    x1, y1 = box1.center()
    x2, y2 = box2.center()
    dx = x2 - x1
    dy = y2 - y1
    # math.atan2(dy, dx) gives angle from positive x-axis, positive CCW.
    # Negate for positive CW convention.

    degree = math.degrees(math.atan2(dy, dx))
    if degree < 0:
        degree += 360
    return degree


lower_white = np.array([244, 244, 244], dtype=np.uint8)
lower_white_none_inclusive = np.array([240, 240, 240], dtype=np.uint8)
upper_white = np.array([255, 255, 255], dtype=np.uint8)
black = np.array([0, 0, 0], dtype=np.uint8)


def isolate_white_text_to_black(cv_image):
    """
    Converts pixels in the near-white range (244-255) to black,
    and all others to white.
    Args:
        cv_image: Input image (NumPy array, BGR).
    Returns:
        Black and white image (NumPy array), where matches are black.
    """
    match_mask = cv2.inRange(cv_image, black, lower_white_none_inclusive)
    output_image = cv2.cvtColor(match_mask, cv2.COLOR_GRAY2BGR)

    return output_image


def convert_bw(cv_image):
    match_mask = cv2.inRange(cv_image, lower_white, upper_white)
    output_image = cv2.cvtColor(match_mask, cv2.COLOR_GRAY2BGR)
    return output_image


lower_icon_white = np.array([210, 210, 210], dtype=np.uint8)
upper_icon_white = np.array([244, 244, 244], dtype=np.uint8)


def convert_dialog_icon(cv_image):
    match_mask = cv2.inRange(cv_image, lower_icon_white, upper_icon_white)
    output_image = cv2.cvtColor(match_mask, cv2.COLOR_GRAY2BGR)
    return output_image


def binarize_for_matching(image, threshold=244):
    """
    Converts a colored image to a binary image based on a brightness threshold.

    The rule is: pixels with a value of 240-255 become pure white (255),
    and all other pixels become pure black (0).

    Args:
        image (np.array): The input BGR image from OpenCV.

    Returns:
        np.array: The resulting binary image (single channel, 8-bit).
    """
    # Convert the image to grayscale for a single brightness value per pixel.
    # This is more robust than checking individual R, G, B channels.

    gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Apply the binary threshold.
    # Pixels > 239 will be set to 255 (white).
    # Pixels <= 239 will be set to 0 (black).
    # cv2.THRESH_BINARY is the type of thresholding we want.
    _, binary_image = cv2.threshold(gray_image, threshold, 255, cv2.THRESH_BINARY)
    return binary_image
