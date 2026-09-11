import time

from src.char.BaseChar import BaseChar


class Rebecca(BaseChar):
    LIB_HOLD_DURATION = 5.2
    LIB_ENTER_DURATION = 0.8
    LIB_REENTER_WINDOW = 17.0
    NORMAL_ATTACK_DURATION = 0.5
    ATTACK_DURATION = 1.0
    ATTACK_TIMEOUT = 2.2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.check_f_on_switch = False
        self._last_liberation_at = -1

    def _in_reenter_window(self):
        return (self._last_liberation_at >= 0 and
                self.time_elapsed_accounting_for_freeze(self._last_liberation_at) < self.LIB_REENTER_WINDOW)

    def do_perform(self):
        # Only a confirmed previous liberation permits the short cooldown rotation.
        reenter = self._in_reenter_window()
        if reenter:
            self.click_resonance(click_f=False)
            start = time.time()
            while not self.is_con_full() and time.time() - start < self.ATTACK_TIMEOUT:
                self.continues_normal_attack(self.NORMAL_ATTACK_DURATION)
        else:
            self._build_forte_sequence()
        return self.switch_next_char()

    def _build_forte_sequence(self):
        self.continues_normal_attack(1.3 if self.has_intro else 1.8)
        start = time.time()
        while not self.resonance_available() and time.time() - start < 2:
            self.sleep(0.1)
        count = 2 if self.has_intro else 3
        for index in range(count):
            self.click_resonance(post_sleep=1 if index == 2 else 1.5, click_f=False)
        start = time.time()
        while not self.is_mouse_forte_full() and time.time() - start < 4:
            self.click()
            self.sleep(0.1)
        if self.is_mouse_forte_full():
            self.check_combat()
            try:
                self.task.mouse_down()
                self.sleep(1.5)
            finally:
                self.task.mouse_up()
        if self.echo_available():
            self.click_echo()
        if self.liberation_available():
            self.perform_hmg_mode()

    def perform_hmg_mode(self):
        # Use the local cast confirmation instead of recording cooldown after blind R presses.
        if not self.click_liberation(send_click=True, click_f=False):
            return False
        self.record_liberation_use()
        start = time.time()
        last_liberation = start
        while time.time() - start < self.LIB_HOLD_DURATION:
            self.click(interval=0.08)
            now = time.time()
            if now - last_liberation > 0.9:
                self.send_liberation_key()
                last_liberation = now
            self.sleep(0.01)
        self._last_liberation_at = time.time()
        return True
