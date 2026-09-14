import unittest
import itertools
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.char.BaseChar import BaseChar, CharType, Elements
from src.char.CharFactory import char_dict
from src.char.Chisa import Chisa
from src.char.Aemeath import Aemeath
from src.char.Camellya import Camellya
from src.char.Danjin import Danjin
from src.char.Denia import Denia
from src.char.Encore import Encore
from src.char.HavocRover import HavocRover
from src.char.Hiyuki import Hiyuki
from src.char.Jinhsi import Jinhsi
from src.char.Linnai import Linnai
from src.char.Lucilla import Lucilla
from src.char.Augusta import Augusta
from src.char.Cartethyia import Cartethyia
from src.char.Jiyan import Jiyan
from src.char.Xiangliyao import Xiangliyao


def task_stub():
    return SimpleNamespace(chars=[], char_config={}, config={}, use_liberation=True,
                           in_liberation=False, debug=False, mouse_up=Mock(), mouse_down=Mock(),
                           send_key=Mock(), get_current_char=Mock(), has_char=Mock(return_value=None))


def solo(cls=BaseChar, **kwargs):
    task = task_stub()
    if cls.__name__ == 'Cartethyia':
        with patch.object(cls, 'init_template'):
            char = cls(task, 0, **kwargs)
    else:
        char = cls(task, 0, **kwargs)
    char.is_current_char = True
    task.chars = [char]
    task.get_current_char.return_value = char
    return char


class TestAllSoloRotations(unittest.TestCase):
    def test_every_registered_output_routes_solo_and_multi_separately(self):
        covered = set()
        for label, entry in char_dict.items():
            if entry['char_type'] not in (CharType.MAIN_DPS, CharType.SUB_DPS):
                continue
            with self.subTest(label=label):
                char = solo(entry['cls'], char_name=label, char_type=entry['char_type'])
                char.has_intro = char.has_sub_dps_intro = True
                char.perform_solo = Mock()
                char.do_perform = Mock()
                char.perform()
                char.perform_solo.assert_called_once()
                char.do_perform.assert_not_called()
                self.assertFalse(char.has_intro)
                self.assertFalse(char.has_sub_dps_intro)
                char.task.chars.append(object())
                char.has_intro = True
                char.perform()
                char.do_perform.assert_called_once()
                self.assertTrue(char.has_intro)
                covered.add(entry['canonical_name'])
        self.assertGreater(len(covered), 35)

    def test_chisa_output_configuration_and_healer_unchanged(self):
        char = solo(Chisa, char_type=CharType.HEALER)
        char.perform_solo = Mock()
        char.do_perform = Mock()
        char.perform()
        char.do_perform.assert_called_once()
        char.task.char_config['Chisa DPS'] = True
        char.perform()
        char.perform_solo.assert_called_once()

    def test_default_solo_retains_character_rotation(self):
        # The independent native rotation is not replaced with generic key spam.
        char = solo()
        char.do_perform = Mock()
        BaseChar.perform_solo(char)
        char.do_perform.assert_called_once()

    def test_generic_output_uses_skills_without_waiting_for_intro_or_switch(self):
        char = solo()
        for method in ('wait_down', 'wait_intro', 'click_echo', 'click_liberation',
                       'click_resonance', 'continues_normal_attack', 'switch_next_char'):
            setattr(char, method, Mock())
        char.perform()
        char.click_echo.assert_called_once()
        char.click_liberation.assert_called_once_with(wait_if_cd_ready=0)
        char.click_resonance.assert_called_once()
        char.wait_intro.assert_not_called()
        char.switch_next_char.assert_not_called()

    def test_single_member_means_actual_team_not_only_one_alive(self):
        char = solo()
        self.assertTrue(char.is_solo)
        for members in ([], [object()], [char, None], [char, object()]):
            char.task.chars = members
            self.assertFalse(char.is_solo)

    def test_no_self_switch_at_combat_end_even_when_switch_allowed(self):
        char = solo()
        char.switch_other_char(allow_auto_combat=True)
        char.task.send_key.assert_not_called()

    def test_character_specific_end_callbacks_do_not_switch_to_self(self):
        for cls in (Augusta, Cartethyia, Camellya, Aemeath):
            with self.subTest(character=cls.__name__):
                char = solo(cls)
                char.is_cartethyia = False
                char.on_combat_end(char.task.chars)
                char.task.send_key.assert_not_called()

    def test_solo_liberation_switch_guards_availability_and_raw_sender(self):
        char = solo()
        char.task.use_liberation = False
        char.available = Mock(return_value=True)
        char.get_liberation_key = Mock(return_value='r')
        self.assertFalse(char.liberation_available())
        self.assertFalse(char.click_liberation())
        self.assertFalse(char.send_liberation_key())
        char.task.send_key.assert_not_called()
        char.available.assert_not_called()

    def test_solo_full_concerto_does_not_block_liberation_attempt(self):
        char = solo()
        char.get_current_con = Mock(side_effect=AssertionError('No solo concerto cap'))
        char.liberation_available = Mock(return_value=False)
        char.has_cd = Mock(return_value=True)
        char.click_liberation(con_less_than=0.5, wait_if_cd_ready=0)
        char.liberation_available.assert_called()

    def test_rover_all_elements_dispatch_without_team_insert(self):
        expected = {Elements.SPECTRO: 'perform_spectro_routine', Elements.HAVOC: 'perform_havoc_routine',
                    Elements.WIND: 'perform_wind_routine'}
        for element in (*Elements, -1):
            with self.subTest(element=element):
                char = solo(HavocRover, ring_index=element)
                char.init = Mock()
                char.sleep = Mock()
                char.continues_normal_attack = Mock()
                char._in_zani_liber_insert_window = Mock(side_effect=AssertionError('No teammate insert'))
                for method in (*expected.values(), 'perform_basic_routine'):
                    setattr(char, method, Mock())
                char.perform()
                getattr(char, expected.get(element, 'perform_basic_routine')).assert_called_once()

    def test_rover_havoc_normal_duration_does_not_depend_on_switch_time(self):
        char = solo(HavocRover, ring_index=Elements.HAVOC)
        for method in ('wait_down', 'heavy_click_forte', 'click_liberation', 'click', 'continues_normal_attack'):
            setattr(char, method, Mock())
        char.click_resonance = Mock(return_value=(False, 0))
        char.click_echo = Mock(return_value=False)
        char.last_switch_time = -10000
        char.perform_havoc_routine()
        char.continues_normal_attack.assert_called_once_with(1.1)

    def test_aemeath_starts_skills_without_buff_or_intro(self):
        char = solo(Aemeath)
        char.has_all_buff = Mock(side_effect=AssertionError('No teammate buffs'))
        char.handle_heavy = Mock(return_value=False)
        char.lib = Mock(return_value=False)
        char.enhance_e_available = Mock(return_value=False)
        char.click_resonance = Mock(return_value=(True, 0))
        char.click_echo = Mock()
        char.continues_normal_attack = Mock()
        char.perform()
        char.lib.assert_called_once()
        char.click_resonance.assert_called_once()
        self.assertFalse(char.must_cast_lib2_this_turn)

    def test_jinhsi_starts_from_available_skill_without_intro(self):
        char = solo(Jinhsi)
        char.resonance_available = Mock(return_value=True)
        char.handle_intro = Mock()
        char.perform()
        char.handle_intro.assert_called_once()
        self.assertFalse(char.has_intro)

    def test_jinhsi_no_cooldown_transition_returns_without_false_state(self):
        char = solo(Jinhsi)
        char.has_cd = Mock(return_value=False)
        char.continues_normal_attack = Mock()
        char.send_resonance_key = Mock()
        with patch('src.char.Jinhsi.time.time', side_effect=itertools.count(step=4)):
            char.handle_intro()
        char.continues_normal_attack.assert_called_once()
        self.assertFalse(char.incarnation)

    def test_hiyuki_missing_long_marker_still_has_basic_skill_start(self):
        char = solo(Hiyuki)
        char.has_long_action = Mock(return_value=False)
        char.has_long_action2 = Mock(return_value=False)
        char.perform_solo_basic = Mock()
        char.perform()
        char.perform_solo_basic.assert_called_once()

    def test_hiyuki_known_stance_keeps_special_rotation(self):
        char = solo(Hiyuki)
        char.has_long_action = Mock(return_value=False)
        char.has_long_action2 = Mock(return_value=True)
        char.do_perform = Mock()
        char.perform()
        char.do_perform.assert_called_once()

    def test_camellya_full_concerto_keeps_enhanced_heavy_and_releases_input(self):
        char = solo(Camellya)
        char.click_liberation = Mock()
        char.ephemeral_ready = Mock(return_value=True)
        char.is_con_full = Mock(return_value=True)
        char.ephemeral_cast = Mock()
        char.heavy_attack = Mock(side_effect=RuntimeError('interrupted'))
        with self.assertRaises(RuntimeError):
            char.perform()
        char.ephemeral_cast.assert_called_once()
        char.task.mouse_up.assert_called_once()

    def test_lucilla_long_cooldown_does_not_prevent_charging(self):
        char = solo(Lucilla)
        char.try_liberation = Mock(return_value=False)
        char.energy_full = Mock(return_value=False)
        char.charge_once = Mock()
        char.click_echo = Mock()
        char.continues_normal_attack = Mock()
        char.perform()
        char.charge_once.assert_called_once()

    def test_lucilla_ready_form_uses_existing_transformation(self):
        char = solo(Lucilla)
        char.try_liberation = Mock(return_value=True)
        char.charge_once = Mock()
        char.perform()
        char.try_liberation.assert_called_once()
        char.charge_once.assert_not_called()

    def test_danjin_can_spend_full_forte_without_intro(self):
        char = solo(Danjin)
        char.click_liberation = Mock(return_value=False)
        char.is_forte_full = Mock(return_value=True)
        for method in ('heavy_attack', 'sleep', 'normal_attack', 'switch_next_char'):
            setattr(char, method, Mock())
        char.perform()
        char.heavy_attack.assert_called_once()

    def test_encore_solo_open_world_can_attempt_liberation(self):
        char = solo(Encore)
        char.still_in_liberation = Mock(return_value=False)
        char.click_resonance = Mock(return_value=(False, 0))
        char.need_fast_perform = Mock(return_value=False)
        char.is_open_world_auto_combat = Mock(return_value=True)
        char.click_liberation = Mock(return_value=True)
        char.n4 = Mock()
        char.switch_next_char = Mock()
        char.perform()
        char.click_liberation.assert_called_once()
        char.n4.assert_called_once()

    def test_denia_full_concerto_does_not_skip_ready_skill(self):
        char = solo(Denia)
        char.time_elapsed_accounting_for_freeze = Mock(side_effect=[0, 0, 2])
        char.is_con_full = Mock(return_value=True)
        char.cycle_start = Mock()
        char.cycle_sleep = Mock()
        char.click_resonance = Mock(return_value=(True, 0))
        char.switch_next_char = Mock()
        char.perform()
        char.click_resonance.assert_called()

    def test_linnai_full_concerto_does_not_skip_second_kick(self):
        char = solo(Linnai)
        char.is_con_full = Mock(return_value=True)
        char.wait_for_accelerate_ready = Mock(return_value=True)
        char.wait_after_resonance_kick = Mock()
        char.click_resonance = Mock(return_value=(True, 0))
        char.click_liberation = Mock(return_value=False)
        char.task.jump = Mock()
        def wait_until(fun, **kwargs):
            if fun.__name__ == 'click_second_resonance':
                return fun()
            return True
        char.task.wait_until = wait_until
        char.perform_under_intro()
        char.click_resonance.assert_called_once()
        char.click_liberation.assert_called_once()

    def test_jiyan_solo_charge_loop_has_deadline(self):
        char = solo(Jiyan)
        for method in ('click_liberation', 'is_forte_full', 'is_con_full', 'resonance_available', 'echo_available'):
            setattr(char, method, Mock(return_value=False))
        char.switch_next_char = Mock()
        with patch('src.char.Jiyan.time.monotonic', side_effect=[0, 3]):
            char.perform()
        char.switch_next_char.assert_called_once()

    def test_xiangliyao_solo_skill_wait_has_deadline(self):
        char = solo(Xiangliyao)
        char.wait_down = Mock()
        char.click_liberation = Mock(return_value=False)
        char.still_in_liberation = Mock(return_value=True)
        char.click_resonance = Mock(return_value=(False, 0))
        char.switch_next_char = Mock()
        with patch('src.char.Xiangliyao.time.monotonic', side_effect=[0, 3]):
            char.perform()
        char.switch_next_char.assert_called_once()


if __name__ == '__main__':
    unittest.main()
