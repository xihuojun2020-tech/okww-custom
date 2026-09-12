"""Current-account character trials; every transition is confirmed on screen."""
import re
import time

import numpy as np
from ok import TaskDisabledException

from src.char.BaseChar import BaseChar
from src.char.TrialGenericChar import TrialGenericChar
from src.task.BaseCombatTask import BaseCombatTask, CharDeadException, CombatStateUnknown, NotInCombatException
from src.task.WWOneTimeTask import WWOneTimeTask
from src.task.character_trial import compact, exact_button, reward_state, start_prompt, detect_portraits, unique_match, merge_view, portrait_selected


class TrialTimeout(RuntimeError):
    pass


class TrialFinished(Exception):
    """Interrupt a rotation only after two fresh completion observations."""


class CharacterTrialTask(WWOneTimeTask, BaseCombatTask):
    navigation_section = 'activities'
    activity_category = '常驻活动'
    owns_switch_healer_config = True
    LIST = (.08, .14, .22, .82)
    TITLE = (.76, .11, .99, .20)
    REWARD = (.89, .79, .99, .87)
    ENTER = (.76, .88, .99, .95)
    NAME = (.26, .66, .39, .73)
    HINT = (.01, .20, .26, .32)
    INTERACT = (.61, .47, .83, .56)
    NEXT = (.79, .86, .97, .95)
    INTRO = (.39, .16, .67, .24)
    OBTAIN = (.40, .22, .61, .30)
    DISMISS = (.39, .85, .62, .93)
    EXIT_MESSAGE = (.39, .43, .62, .52)
    EXIT_CONFIRM = (.55, .58, .76, .67)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = 'Character Trial'
        self.description = 'Complete current character trials and claim rewards. Available rewards are claimed directly.'
        self.group_name = '常驻活动'
        self.supported_languages = ['zh_CN']
        self.support_schedule_task = False
        self.default_config.update({'Trial Combat Timeout': 180})
        self.config_description['Trial Combat Timeout'] = 'Maximum combat seconds per character (60–600).'
        self.skip_combat_check = True
        self._battle_deadline = None
        self._trial_map = False
        self._frame_serial = 0
        self._last_done_frame = -1
        self._done_count = 0
        self._held_keys = set()
        self._held_mouse = set()
        self.last_result = None

    def validate_config(self, key, value):
        if key == 'Trial Combat Timeout' and (type(value) not in (int, float) or not 60 <= value <= 600):
            return 'Trial Combat Timeout must be between 60 and 600.'

    def _guard(self):
        self.executor.check_enabled()
        scan_deadline = getattr(self, '_scan_deadline', None)
        if scan_deadline is not None and time.monotonic() >= scan_deadline:
            raise TrialTimeout('角色列表扫描超时')
        if self._battle_deadline is not None and time.monotonic() >= self._battle_deadline:
            raise TrialTimeout('角色试用战斗超时')

    def next_frame(self):
        self._guard()
        result = super().next_frame()
        self._frame_serial += 1
        self.require_game_frame()
        return result

    def click(self, *args, **kwargs):
        self._guard()
        return super().click(*args, **kwargs)

    def send_key(self, *args, **kwargs):
        self._guard()
        return super().send_key(*args, **kwargs)

    def send_key_down(self, key, *args, **kwargs):
        self._guard()
        self._held_keys.add(key)
        return super().send_key_down(key, *args, **kwargs)

    def send_key_up(self, key):
        result = super().send_key_up(key)
        self._held_keys.discard(key)
        return result

    def mouse_down(self, *args, **kwargs):
        self._guard()
        self._held_mouse.add(kwargs.get('key', 'left'))
        return super().mouse_down(*args, **kwargs)

    def mouse_up(self, name=None, key='left'):
        result = super().mouse_up(name=name, key=key)
        self._held_mouse.discard(key)
        return result

    def _release(self):
        # Cleanup must bypass normal task-enabled checks after a stop.
        for key in tuple(self._held_keys):
            try:
                self.executor.interaction.send_key_up(self.validate_key(key))
                self._held_keys.discard(key)
            except Exception as error:
                self.log_warning(f'试用释放按键失败：{error}')
        for key in tuple(self._held_mouse):
            try:
                self.executor.interaction.mouse_up(key=key)
                self._held_mouse.discard(key)
            except Exception as error:
                self.log_warning(f'试用释放鼠标失败：{error}')

    def switch_healer_enabled(self):
        return False

    def revive_action(self):
        # A trial must never enter the overworld teleport/heal recovery path.
        return False

    def _stage(self, text):
        self.info_set('试用阶段', text)
        self.log_info(text)

    def _ocr(self, region):
        return self.ocr(*region, frame=self.require_game_frame())

    def _button(self, region, text):
        return exact_button(self._ocr(region), text)

    def _click_button(self, region, text):
        button = self._button(region, text)
        if button is None:
            raise RuntimeError(f'未唯一定位按钮：{text}')
        self.click(button)

    def _wait(self, probe, message, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.next_frame()
            value = probe()
            if value:
                return value
            self.sleep(.2)
        raise TrialTimeout(message)

    def _stable(self, probe, message, timeout=15):
        previous = None
        def read():
            nonlocal previous
            value = probe()
            stable = value is not None and value == previous
            previous = value
            return (value,) if stable else None
        return self._wait(read, message, timeout)[0]

    def _page(self):
        return bool(self._button(self.TITLE, '初露峥嵘') and self._button(self.ENTER, '前往试用'))

    def _open(self):
        self.next_frame()
        if self._page():
            return
        if not self._button((.02, .03, .18, .10), '推荐活动'):
            self.ensure_main(time_out=60)
            self.send_key('f1')
            self._wait(lambda: self._button((.02, .03, .18, .10), '推荐活动'), '无法打开活动页')
        # Scan both directions; never click a fixed activity row.
        for direction in (1, -1):
            previous, unchanged = None, 0
            for _ in range(16):
                self.next_frame()
                boxes = self._ocr(self.LIST)
                target = exact_button(boxes, '初露峥嵘')
                if target:
                    self.click(target)
                    self._wait(self._page, '无法确认初露峥嵘页面')
                    return
                signature = tuple(compact(b.name) for b in boxes)
                unchanged = unchanged + 1 if signature and signature == previous else 0
                if unchanged >= 3:
                    break
                previous = signature
                self._guard()
                self.scroll_relative(.15, .50, direction)
                self.sleep(.35)
        raise TrialTimeout('活动列表中未找到初露峥嵘')

    def _view(self, timeout=15):
        previous = None
        def read():
            nonlocal previous
            if not self._page():
                return None
            view = detect_portraits(self.require_game_frame())
            cards = view[0]
            stable = previous is not None and len(cards) == len(previous[0]) and all(
                abs(a.x-b.x) < self.width*.004 and unique_match(a.image, cards) == i
                for i, (a, b) in enumerate(zip(previous[0], cards)))
            previous = view
            return view if stable else None
        return self._wait(read, '头像列表无法稳定识别', timeout)

    def _scroll_view(self, before, direction):
        if not before[0]:
            raise RuntimeError('头像列表为空，不能拖拽')
        original = before
        after = before
        for attempt in range(1, 4):
            self._guard()
            self.next_frame()
            if not self._page():
                raise RuntimeError('滚动前角色试用页面已改变')
            x, y = after[0][len(after[0])//2].center
            self.move(x, y)
            self.sleep(.15)
            self._guard()
            self._drag_portraits(after, direction)
            deadline = time.monotonic() + 1.5
            # Stable old frames are not proof of a failed input: wait for response.
            previous_delta = None
            while time.monotonic() < deadline:
                self._guard()
                after = self._view(timeout=2)
                delta = self._scroll_displacement(original, after)
                if abs(delta) >= self.width*.008:
                    if previous_delta is not None and abs(delta-previous_delta) < self.width*.004:
                        self.log_info(f'头像滚动已确认：方向={direction} 尝试={attempt} 位移={delta:.1f}')
                        return after, delta
                    previous_delta = delta
                else:
                    previous_delta = None
                self.sleep(.1)
            delta = self._scroll_displacement(original, after)
            self.log_info(f'头像滚动观察：方向={direction} 尝试={attempt} 坐标=({x},{y}) '
                          f'位移={delta:.1f} 头像={len(after[0])} 截断={after[1:]} '
                          f'输入=横向拖拽/{type(self.executor.interaction).__name__}')
            if abs(delta) >= self.width*.008:
                raise TrialTimeout('头像滚动尚未稳定，停止以防漏角色')
        return after, self._scroll_displacement(original, after)

    def _drag_portraits(self, view, direction):
        cards = view[0]
        if direction not in (-1, 1) or len(cards) < 3:
            raise RuntimeError('头像不足，不能保证拖拽重叠')
        pitch = float(np.median(np.diff([card.x for card in cards])))
        x, y = cards[len(cards)//2].center
        end_x = round(x + direction*pitch)
        if pitch <= 0 or not cards[0].x < end_x < cards[-1].x+cards[-1].width:
            raise RuntimeError('头像拖拽范围无效')
        self._guard()
        # Framework swipe performs down/move/up; retain cleanup ownership on errors.
        self._held_mouse.add('left')
        try:
            self.swipe(x, y, end_x, y, duration=.5, after_sleep=.1)
        finally:
            self.executor.interaction.mouse_up(key='left')
            self._held_mouse.discard('left')
        self._guard()

    def _scroll_displacement(self, before, after):
        moves = []
        for card in before[0]:
            index = unique_match(card.image, after[0])
            if index is not None:
                moves.append(after[0][index].x - card.x)
        if len(moves) < 2:
            raise RuntimeError('拖拽步进失去头像重叠，停止以防漏角色')
        displacement = float(np.median(moves))
        if any(abs(move-displacement) > self.width*.008 for move in moves):
            raise RuntimeError('头像滚动位移不一致，停止以防错误匹配')
        return displacement

    def _edge(self, view, direction, side):
        unchanged = 0
        for _ in range(24):
            after, delta = self._scroll_view(view, direction)
            unchanged = unchanged + 1 if abs(delta) < self.width*.008 else 0
            view = after
            if unchanged >= 3:
                if view[1 if side == 'left' else 2]:
                    raise RuntimeError('拖拽未覆盖边缘截断头像')
                return view
        raise TrialTimeout('无法确认头像列表边界')

    def _scan(self):
        self._scan_deadline = time.monotonic() + 90
        try:
            return self._scan_list()
        finally:
            self._scan_deadline = None

    def _scan_list(self):
        self._stage('扫描本期角色列表')
        before = self._view()
        # Confirm the drag direction from actual content displacement.
        for direction in (1, -1):
            after, delta = self._scroll_view(before, direction)
            if abs(delta) >= self.width*.008:
                self._toward_left = direction if delta > 0 else -direction
                break
            before = after
        else:
            raise RuntimeError('头像拖拽未生效，无法确认完整名单')
        view = self._edge(after, self._toward_left, 'left')
        known, unchanged = list(view[0]), 0
        for _ in range(24):
            after, delta = self._scroll_view(view, -self._toward_left)
            if delta > self.width*.008:
                raise RuntimeError('头像滚动方向发生变化')
            known = merge_view(known, after[0])
            unchanged = unchanged + 1 if abs(delta) < self.width*.008 else 0
            view = after
            if unchanged >= 3:
                if view[2]:
                    raise RuntimeError('右侧仍有未覆盖头像')
                if not 5 <= len(known) <= 6:
                    raise RuntimeError(f'发现{len(known)}个角色，布局超出已验证范围')
                return known
        raise TrialTimeout('角色列表扫描超时')

    def _select(self, target):
        view = self._view()
        for direction in (self._toward_left, -self._toward_left):
            unchanged = 0
            for _ in range(24):
                index = unique_match(target.image, view[0])
                if index is not None:
                    card = view[0][index]
                    self.click(*card.center)
                    self.sleep(.3)
                    def selected():
                        cards, _, _ = detect_portraits(self.require_game_frame())
                        i = unique_match(target.image, cards)
                        if i is None:
                            return None
                        return True if portrait_selected(self.require_game_frame(), cards[i]) else None
                    self._stable(selected, '无法确认目标头像已选中')
                    name = ''.join(b.name for b in self._ocr(self.NAME))
                    self.info_set('试用角色', name or '未识别名称（按头像核对）')
                    return
                after, delta = self._scroll_view(view, direction)
                unchanged = unchanged + 1 if abs(delta) < self.width*.008 else 0
                view = after
                if unchanged >= 3:
                    break
        raise RuntimeError('返回页面后无法重新定位目标角色')

    def _state(self):
        return self._stable(lambda: reward_state(self._ocr(self.REWARD)) if self._page() else None,
                            '无法确认角色奖励状态')

    def _claim(self, target):
        self._stage('领取试用奖励')
        self._select(target)
        if self._state() != 'claim':
            raise RuntimeError('领奖前角色状态已变化')
        button = self._button(self.REWARD, '领取')
        if button is None:
            raise RuntimeError('领取按钮不唯一')
        self.click(button)
        self._wait(lambda: self._button(self.OBTAIN, '获得') and self._button(self.DISMISS, '点击空白处继续'),
                   '未出现获得奖励弹窗')
        self._click_button(self.DISMISS, '点击空白处继续')
        self._wait(self._page, '奖励弹窗未关闭')
        self._select(target)
        if self._state() != 'complete':
            raise RuntimeError('领取后未确认已完成')
        self.screenshot('character_trial_reward_complete')

    def _map_ready(self):
        return bool(self.in_team()[0] and not self._button(self.NEXT, '下一页') and not self._page())

    def _enter(self):
        self._stage('进入角色试用')
        self.chars = []
        self.reset_to_false('new character trial')
        self._trial_map = True
        self._done_count = 0
        self._last_done_frame = -1
        button = self._button(self.ENTER, '前往试用')
        if button is None:
            raise RuntimeError('未找到前往试用按钮')
        self.click(button)
        for _ in range(6):
            def loaded():
                if self._button(self.INTRO, '战斗特色') and self._button(self.NEXT, '下一页'):
                    return 'intro'
                if self._map_ready():
                    return 'map'
            state = self._wait(loaded, '试用加载或介绍页面超时', 60)
            if state == 'map':
                self._stable(lambda: True if self._map_ready() else None, '试用地图未稳定')
                return
            self._click_button(self.NEXT, '下一页')
            self.sleep(.5)
        raise TrialTimeout('角色介绍页数超出上限')

    def _start(self):
        self._stage('寻找开启挑战')
        end = time.monotonic() + 20
        while time.monotonic() < end:
            self.next_frame()
            if start_prompt(self._ocr(self.INTERACT), self.height):
                break
            if not self._map_ready():
                raise RuntimeError('前进时试用地图状态丢失')
            try:
                self.send_key_down('w')
                self.sleep(.25)
            finally:
                self._release()
        else:
            raise TrialTimeout('未找到F开启挑战交互')
        self._battle_deadline = time.monotonic() + self.config.get('Trial Combat Timeout', 180)
        for attempt in range(2):
            self.next_frame()
            if not start_prompt(self._ocr(self.INTERACT), self.height):
                raise RuntimeError('开启挑战交互发生变化')
            self.send_key('f')
            try:
                self._wait(lambda: self.in_combat(), '开启挑战后未进入战斗', 10)
                return
            except TrialTimeout:
                if attempt or not start_prompt(self._ocr(self.INTERACT), self.height):
                    raise

    def _finished(self):
        if self._last_done_frame == self._frame_serial:
            return self._done_count >= 2
        self._last_done_frame = self._frame_serial
        self._done_count = self._done_count + 1 if self._button(self.HINT, '离开模拟领域') else 0
        return self._done_count >= 2

    def sleep_check(self):
        self._guard()
        if self._battle_deadline is not None:
            self.next_frame()
            if self._finished():
                raise TrialFinished()
        return super().sleep_check()

    def in_combat(self, target=False):
        self._guard()
        if self._battle_deadline is not None and self._finished():
            raise TrialFinished()
        return super().in_combat(target)

    def in_team(self, frame=None):
        result = super().in_team(frame)
        if result[0] or not self._trial_map:
            return result
        # Solo trials have no numbered teammate markers. Require independent HUD
        # evidence and no names in the two lower slots before accepting one slot.
        names = [self.ocr(.88, y, .98, y+.045, frame=frame) for y in (.23, .35, .47)]
        hp = ''.join(b.name for b in self.ocr(.39, .94, .60, .985, frame=frame))
        if names[0] and not names[1] and not names[2] and re.search(r'\d+\s*/\s*\d+', hp):
            return True, 0, 1
        return result

    def load_chars(self):
        loaded = super().load_chars()
        if loaded:
            for i, char in enumerate(self.chars):
                if type(char) is BaseChar:
                    generic = TrialGenericChar(
                        self, i, char_name=char.char_name if char.char_name != 'unknown' else f'trial_unknown_{i}',
                        confidence=char.confidence, ring_index=char.ring_index,
                        char_type=char.char_type, buff_time=char.buff_time)
                    generic.is_current_char = char.is_current_char
                    self.chars[i] = generic
                    self.log_info(f'试用队伍槽位{i+1}使用通用轮转')
        return loaded

    def _fight(self):
        self._stage('角色试用自动战斗')
        recoveries = 0
        try:
            while True:
                self.skip_combat_check = False
                try:
                    self.combat_once(wait_combat_time=10)
                except CharDeadException:
                    raise
                except (CombatStateUnknown, NotInCombatException):
                    recoveries += 1
                    if recoveries > 1:
                        raise
                finally:
                    self.skip_combat_check = True
                    self._release()
                def phase():
                    if self._finished():
                        return 'complete'
                    if self.in_combat():
                        return 'combat'
                if self._wait(phase, '脱战后无法确认试用完成或下一波敌人', 20) == 'complete':
                    return
        except TrialFinished:
            return
        finally:
            self.skip_combat_check = True
            self._battle_deadline = None
            self._release()

    def _leave(self):
        self._stage('确认离开模拟领域')
        self._stable(lambda: True if self._button(self.HINT, '离开模拟领域') else None,
                     '未确认离开模拟领域，不执行退出')
        self.send_key('esc')
        self._wait(lambda: self._button(self.EXIT_MESSAGE, '确认离开') and
                   self._button(self.EXIT_CONFIRM, '确认'), '未找到确认离开弹窗')
        self._click_button(self.EXIT_CONFIRM, '确认')
        self._wait(self._page, '未返回初露峥嵘活动页', 60)
        self._trial_map = False
        self.reset_to_false('trial returned to activity')

    def _process(self, target):
        self._select(target)
        state = self._state()
        if state == 'complete':
            return 'already_complete'
        if state == 'pending':
            self._enter()
            try:
                self._start()
                self._fight()
            except TrialFinished:
                self._battle_deadline = None
            self._leave()
            self._select(target)
            if self._state() != 'claim':
                raise RuntimeError('试用返回后奖励未变为领取')
        self._claim(target)
        return 'trial_claimed' if state == 'pending' else 'direct_claimed'

    def run(self):
        super().run()
        self.last_result = {'direct_claimed': 0, 'trial_claimed': 0, 'already_complete': 0, 'failed': 0, 'complete': False}
        self.skip_combat_check = True
        try:
            timeout = self.config.get('Trial Combat Timeout', 180)
            if self.validate_config('Trial Combat Timeout', timeout):
                raise ValueError('Trial Combat Timeout must be between 60 and 600.')
            self._open()
            targets = self._scan()
            for index, target in enumerate(targets):
                self.info_set('试用进度', f'{index+1}/{len(targets)}')
                outcome = self._process(target)
                self.last_result[outcome] += 1
                self.info_set('试用统计', f'直接领取 {self.last_result["direct_claimed"]}，'
                              f'试用后领取 {self.last_result["trial_claimed"]}，'
                              f'原已完成 {self.last_result["already_complete"]}')
            self._stage('复核全部角色奖励')
            for target in targets:
                self._select(target)
                if self._state() != 'complete':
                    raise RuntimeError('最终复核发现角色未完成')
            self.last_result['complete'] = True
            self._stage(f'本期{len(targets)}个角色奖励已全部确认完成')
        except TaskDisabledException:
            raise
        except Exception:
            self.last_result['failed'] += 1
            try:
                self.screenshot('character_trial_failed')
            except Exception as error:
                self.log_warning(f'试用错误截图保存失败：{error}')
            raise
        finally:
            self._battle_deadline = None
            self.skip_combat_check = True
            self._trial_map = False
            self._release()
