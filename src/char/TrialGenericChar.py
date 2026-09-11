"""Fallback rotation used only for unregistered trial party members."""
from src.char.BaseChar import BaseChar


class TrialGenericChar(BaseChar):
    def do_perform(self):
        self.wait_intro(1.2)
        self.click_echo(time_out=0)
        self.click_liberation()
        self.click_resonance()
        self.continues_normal_attack(1.5)
        if self.is_forte_full():
            self.heavy_attack()
        if len(self.task.chars) > 1:
            self.switch_next_char()
