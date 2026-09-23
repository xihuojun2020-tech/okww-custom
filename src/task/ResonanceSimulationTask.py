"""Manual-navigation, automatic-combat controller for 群声共振模拟域."""
import ctypes
import math
import os
import queue
import threading
import time

import win32gui
import win32process

from ok import PostMessageInteraction

from src.activity_catalog import ACTIVITIES
from src.runtime.game_runtime_errors import GameProcessLost
from src.task.BaseWWTask import BaseWWTask
from src.task.resonance_simulation import liberation_ready, skill_bar_visible


class ResonanceSimulationTask(BaseWWTask):
    navigation_section = 'activities'
    activity_category = '限时活动'
    VK_OEM_2 = 0xBF

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = ACTIVITIES['resonance_simulation']
        self.description = '手动移动和选择奖励；技能栏可见时持续自动战斗。按 /? 键暂停或继续。'
        self.group_name = '限时活动'
        self.supported_languages = ['zh_CN']
        self.support_schedule_task = False
        self.default_config.update({'Skill Interval': 2.0})
        self.config_description.update({
            'Skill Interval': 'E技能尝试间隔秒数；Q仅在检测到完整黄色充能圆环时释放。',
        })
        self._held_keys = set()
        self._held_mouse = set()
        self._manual_paused = False

    def _settings(self):
        self._skill_interval = float(self.config['Skill Interval'])
        if not math.isfinite(self._skill_interval) or not .5 <= self._skill_interval <= 10:
            raise ValueError('技能间隔必须在0.5至10秒之间')

    def _foreground(self):
        window = self.hwnd
        if window is None or not window.exists:
            raise GameProcessLost('游戏窗口已断开，停止群声共振任务')
        return win32gui.GetForegroundWindow() in (window.hwnd, getattr(window, 'top_hwnd', None))

    def _input_context_allowed(self):
        return self._foreground() or isinstance(self.executor.interaction, PostMessageInteraction)

    def _input_ready(self):
        executor = self.executor
        executor.check_enabled(check_pause=False)
        self._guard_account_input()
        return (not executor.paused and not executor.exit_event.is_set()
                and not self._manual_paused and self._input_context_allowed())

    def _hotkey_context(self):
        try:
            if self._foreground():
                return True
        except GameProcessLost:
            return False
        foreground = win32gui.GetForegroundWindow()
        return bool(foreground and win32process.GetWindowThreadProcessId(foreground)[1] == os.getpid())

    def _slash_pressed(self):
        return bool(ctypes.windll.user32.GetAsyncKeyState(self.VK_OEM_2) & 0x8000)

    def _watch_hotkey(self, stop, events):
        # Capture short taps even while the task thread is reading a game frame.
        down = self._slash_pressed()
        while not stop.wait(.02):
            pressed = self._slash_pressed()
            if pressed and not down:
                events.put(self._hotkey_context())
            down = pressed

    def _apply_hotkeys(self, events):
        while True:
            try:
                accepted = events.get_nowait()
            except queue.Empty:
                return
            if accepted:
                self._manual_paused = not self._manual_paused
                self._release()
                self.log_info('群声共振快捷键：' + ('暂停' if self._manual_paused else '继续'))
            else:
                self.log_info('群声共振快捷键已忽略：焦点不在游戏或OK-WW')

    def _activity_status(self, status):
        if getattr(self, '_last_activity_status', None) != status:
            self._last_activity_status = status
            self.info_set('活动状态', status)

    def _release(self):
        errors = []
        for key in tuple(self._held_keys):
            try:
                self.executor.interaction.send_key_up(key)
                self._held_keys.discard(key)
            except Exception as error:
                errors.append(error)
        for key in tuple(self._held_mouse):
            try:
                self.executor.interaction.mouse_up(key=key)
                self._held_mouse.discard(key)
            except Exception as error:
                errors.append(error)
        if errors:
            raise RuntimeError('群声共振输入释放失败，停止任务') from errors[0]

    def _pulse(self, attack=False, skill=None):
        if not self._input_ready():
            return
        interaction = self.executor.interaction
        try:
            if skill:
                self._held_keys.add(skill)
                interaction.send_key_down(skill, activate=False)
            if attack and self._input_ready():
                self._held_mouse.add('left')
                interaction.mouse_down(key='left')
            deadline = time.monotonic() + .08
            while time.monotonic() < deadline and self._input_ready():
                time.sleep(min(.02, max(0, deadline - time.monotonic())))
        finally:
            self._release()

    def run(self):
        self._settings()
        hotkey_stop = threading.Event()
        hotkey_events = queue.SimpleQueue()
        hotkey_thread = threading.Thread(target=self._watch_hotkey, args=(hotkey_stop, hotkey_events), daemon=True)
        hotkey_thread.start()
        visible_frames = 0
        ready_frames = 0
        next_skill = 0
        next_liberation = 0
        try:
            self._activity_status('等待技能栏；移动和奖励选择由玩家操作')
            while True:
                self.executor.check_enabled(check_pause=False)
                self._apply_hotkeys(hotkey_events)
                if self.executor.paused or self._manual_paused:
                    self._release()
                    status = '程序已暂停' if self.executor.paused else '已手动暂停；按 /? 键继续'
                    self._activity_status(status)
                    time.sleep(.08)
                    continue
                if not self._input_context_allowed():
                    self._release()
                    visible_frames = ready_frames = 0
                    self._activity_status('等待游戏回到前台')
                    time.sleep(.15)
                    continue
                self.next_frame()
                frame = self.require_game_frame()
                visible = skill_bar_visible(frame)
                visible_frames = min(2, visible_frames + 1) if visible else 0
                if visible_frames < 2:
                    ready_frames = 0
                    self._activity_status('等待技能栏；不会操作移动或界面')
                    self.sleep(.08)
                    continue
                now = time.monotonic()
                ready_frames = min(2, ready_frames + 1) if liberation_ready(frame) else 0
                skill = None
                if ready_frames >= 2 and now >= next_liberation:
                    skill = 'q'
                    next_liberation = now + 1.5
                elif now >= next_skill:
                    skill = 'e'
                    next_skill = now + self._skill_interval
                self._activity_status('自动战斗中；按 /? 键暂停')
                self._pulse(attack=True, skill=skill)
                self.sleep(.04)
        finally:
            hotkey_stop.set()
            hotkey_thread.join(timeout=.5)
            self._release()
