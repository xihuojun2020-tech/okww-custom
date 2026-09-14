import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from src.char.Qingxiao import Qingxiao
from src.char.BaseChar import BaseChar


class TestQingxiaoSolo(unittest.TestCase):
    def make_char(self):
        task = SimpleNamespace(chars=[])
        char = Qingxiao(task, 0)
        task.chars = [char]
        char.has_all_buff = Mock(side_effect=AssertionError('Solo cannot require team buffs'))
        for name, result in [('handle_heavy', False), ('click_liberation', False),
                             ('cast_enhanced_resonance', False), ('click_resonance', (False, 0)),
                             ('click_echo', False), ('f_break', None),
                             ('continues_normal_attack', None), ('switch_next_char', None)]:
            setattr(char, name, Mock(return_value=result))
        return char

    def test_solo_casts_normal_skill_without_intro_or_enhanced_skill(self):
        char = self.make_char()
        char.click_resonance.return_value = (True, 0)
        char.do_perform()
        char.click_liberation.assert_called_once()
        char.click_resonance.assert_called_once_with(send_click=False, time_out=1.5)
        char.continues_normal_attack.assert_called_once()
        char.switch_next_char.assert_not_called()

    def test_solo_casts_ready_liberation_without_teammate_buffs(self):
        char = self.make_char()
        char.click_liberation.return_value = True
        char.do_perform()
        char.click_liberation.assert_called_once_with(wait_if_cd_ready=0)
        char.click_resonance.assert_not_called()

    def test_disabled_liberation_uses_real_helper_and_never_sends_key(self):
        char = self.make_char()
        char.task.use_liberation = False
        char.click_liberation = BaseChar.click_liberation.__get__(char)
        char.send_liberation_key = Mock()
        char.do_perform()
        char.send_liberation_key.assert_not_called()
        char.click_resonance.assert_called_once()

    def test_heavy_state_keeps_character_specific_handling(self):
        char = self.make_char()
        char.handle_heavy.return_value = 'qingxiao_h2'
        char.do_perform()
        char.f_break.assert_called_once()
        char.click_liberation.assert_not_called()

    def test_enhanced_skill_is_not_followed_by_duplicate_normal_skill(self):
        char = self.make_char()
        char.cast_enhanced_resonance.return_value = True
        char.do_perform()
        char.click_resonance.assert_not_called()

    def test_cooldowns_fall_back_to_echo_and_normal_attack(self):
        char = self.make_char()
        char.do_perform()
        char.click_echo.assert_called_once_with(time_out=0)
        char.continues_normal_attack.assert_called_once_with(0.2)

    def test_multi_team_keeps_existing_setup_gate(self):
        char = self.make_char()
        char.task.chars.append(object())
        char.has_all_buff = Mock(return_value=False)
        char.do_perform()
        char.cast_enhanced_resonance.assert_called_once()
        char.switch_next_char.assert_called_once()
        char.click_resonance.assert_not_called()
        char.click_liberation.assert_not_called()


if __name__ == '__main__':
    unittest.main()
