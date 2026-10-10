"""Generic rotation for trial party members and unconfirmed combat identities."""
from src.char.BaseChar import BaseChar


class TrialGenericChar(BaseChar):
    def do_perform(self):
        self.wait_intro(1.2)
        self.click_echo(time_out=0)
        self.click_liberation()
        if self.__dict__.get('_identity_unconfirmed', False):
            self.click_resonance(time_out=1.5)
        else:
            self.click_resonance()
        self.continues_normal_attack(1.5)
        if self.is_forte_full():
            self.heavy_attack()
        if len(self.task.chars) > 1:
            self.switch_next_char()
