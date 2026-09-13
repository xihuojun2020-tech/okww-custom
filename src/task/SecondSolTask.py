"""Foreground-only F taps for a manually opened activity."""
import random
import time

import win32gui
from ok import BaseTask
from src.activity_catalog import ACTIVITIES


class SecondSolTask(BaseTask):
    diagnostic_visual_idle = True
    navigation_section = "activities"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = ACTIVITIES['second_sol']
        self.description = "手动进入活动后开始，约每秒短按 F；切出游戏时等待，活动结束后请手动停止。"
        self.group_name = "限时活动"
        self.support_schedule_task = False

    def _game_in_foreground(self):
        window = self.hwnd
        if window is None or not window.exists:
            raise RuntimeError('游戏窗口已断开，停止活动按键')
        foreground = win32gui.GetForegroundWindow()
        return bool(foreground and foreground in (window.hwnd, getattr(window, 'top_hwnd', None)))

    def run(self):
        count = 0
        while True:
            # Reset/check before the foreground probe: pausing here must not leave a stale focus check.
            self.executor.reset_scene()
            if not self._game_in_foreground():
                self.info_set('活动状态', '等待游戏回到前台')
                self.executor.sleep(0.2)
                continue
            started = time.monotonic()
            interval = random.uniform(0.85, 1.15)
            hold = random.uniform(0.05, 0.10)
            interaction = self.executor.interaction
            try:
                interaction.send_key('f', down_time=hold)
            finally:
                # Cleanup bypasses task pause/stop checks, including a partially failed tap.
                interaction.send_key_up('f')
            count += 1
            self.info_set('活动状态', '持续按 F，活动结束后请手动停止')
            self.info_set('按键次数', count)
            self.executor.sleep(max(0, interval - (time.monotonic() - started)))
