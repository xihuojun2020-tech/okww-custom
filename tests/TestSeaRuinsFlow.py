"""No game input: state-machine safety checks with controlled observations."""
import unittest
from unittest.mock import Mock, patch
from src.task.AutoSeaRuinsTask import AutoSeaRuinsTask, SeaPhaseEnded
from src.task.BaseCombatTask import NotInCombatException


class TestSeaRuinsFlow(unittest.TestCase):
    def task(self):
        t = Mock()
        t.frame = object()
        t._floor = 7
        t.in_team_and_world.return_value = True
        return t

    def test_start_walks_until_exact_prompt_then_single_f(self):
        t = self.task()
        t.in_combat.return_value = False
        t._prompt.side_effect = [False, False, True]
        AutoSeaRuinsTask._start_combat(t)
        self.assertEqual([c.args[0] for c in t.send_key.call_args_list], ['w', 'f'])
        t._release.assert_called_once()

    def test_start_timeout_never_blindly_presses_f(self):
        t = self.task()
        t.in_combat.return_value = False
        t._prompt.return_value = False
        with self.assertRaisesRegex(RuntimeError, '未找到F'):
            AutoSeaRuinsTask._start_combat(t)
        self.assertTrue(all(c.args[0] == 'w' for c in t.send_key.call_args_list))
        t._release.assert_called_once()

    def test_wave_gap_is_not_completion(self):
        t = self.task()
        t.combat_once.side_effect = [NotInCombatException(), SeaPhaseEnded()]
        AutoSeaRuinsTask._fight(t, 0)
        self.assertEqual(t.combat_once.call_count, 2)
        t._wait.assert_called_once()
        self.assertIsNone(t._observing_half)
        self.assertTrue(t.skip_combat_check)

    def test_lower_transition_recenters_once_aligns_then_walks(self):
        t = self.task()
        t._prompt.side_effect = [False, False, True]
        t._upper_end.return_value = True
        with patch('src.task.AutoSeaRuinsTask.vision.exit_marker', side_effect=[(.8,.3,.9),(.5,.3,.9)]):
            AutoSeaRuinsTask._enter_lower(t)
        t.middle_click.assert_called_once()
        t._turn.assert_called_once()
        self.assertEqual([c.args[0] for c in t.send_key.call_args_list], ['w', 'f'])
        self.assertGreaterEqual(t._release.call_count, 3)

    def test_lost_upper_state_stops_without_f(self):
        t = self.task()
        t._prompt.return_value = False
        t._upper_end.return_value = False
        with self.assertRaisesRegex(RuntimeError, '提示消失'):
            AutoSeaRuinsTask._enter_lower(t)
        t.send_key.assert_not_called()
        self.assertGreaterEqual(t._release.call_count, 2)

    def test_turn_relative_input_is_foreground_only_and_clamped(self):
        t = self.task()
        t.hwnd.hwnd = 123
        t.width = 1000
        with patch('src.task.AutoSeaRuinsTask.win32gui.GetForegroundWindow', return_value=123) as foreground, \
                patch('src.task.AutoSeaRuinsTask.win32api.mouse_event') as move:
            AutoSeaRuinsTask._turn(t, .8)
            self.assertEqual(move.call_args.args[1], 120)
            foreground.return_value = 456
            with self.assertRaisesRegex(RuntimeError, '前台'):
                AutoSeaRuinsTask._turn(t, .8)
            move.assert_called_once()

    def test_continue_checks_announced_destination_before_click(self):
        t = self.task()
        t._result.return_value = True
        t.ocr.return_value = [Mock(name='unused')]
        t.ocr.return_value[0].name = '即将前往涡流-第9层'
        def navigate(label, source, target, **kwargs):
            self.assertIsNone(source(t.frame))
            t.ocr.return_value[0].name = '即将前往涡流-第8层'
            self.assertIsNotNone(source(t.frame))
            target(t.frame)
            t._detail.assert_called_with(t.frame, 8)
        t.navigate_ui.side_effect = navigate
        AutoSeaRuinsTask._continue(t)

    def test_preset_sidebar_is_closed_before_requiring_floor_digit(self):
        t = self.task()
        t._detail.return_value = False
        AutoSeaRuinsTask._close_presets(t)
        t.send_key.assert_called_once_with('esc')
        t._wait.assert_called_once()
