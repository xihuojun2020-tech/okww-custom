"""No game input: state-machine safety checks with controlled observations."""
import unittest
from unittest.mock import Mock, patch
from src.task.AutoSeaRuinsTask import AutoSeaRuinsTask, SeaPhaseEnded
from src.task.BaseCombatTask import NotInCombatException


class TestSeaRuinsFlow(unittest.TestCase):
    def test_open_unknown_map_never_clicks_arrow(self):
        t = self.task()
        t._wait.side_effect = [object(), RuntimeError('无法定位')]
        with self.assertRaisesRegex(RuntimeError, '无法定位'):
            AutoSeaRuinsTask._open(t)
        t.click_relative.assert_not_called()

    def test_open_clicks_verified_boat_then_checks_floor(self):
        t = self.task()
        t._wait.side_effect = [object(), (.72, .51), True]
        AutoSeaRuinsTask._open(t)
        t.click_relative.assert_called_once_with(.72, .51)
        t._wait.call_args.args[0](t.frame)
        t._detail.assert_called_once_with(t.frame, 7)

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

    def test_lower_transition_reuses_background_walker(self):
        t = self.task()
        t._prompt.return_value = True
        t._upper_end.return_value = True
        def walk(find, **kwargs):
            self.assertEqual(kwargs['time_out'], 60)
            find()
            return kwargs['end_condition']()
        t.walk_to_box.side_effect = walk
        with patch('src.task.AutoSeaRuinsTask.vision.exit_marker', return_value=(.8,.3,.9)):
            AutoSeaRuinsTask._enter_lower(t)
        t.ensure_in_front.assert_not_called()
        t.middle_click.assert_called_once()
        t.box_of_screen.assert_called_once_with(.795, .295, .805, .305)
        self.assertEqual([c.args[0] for c in t.send_key.call_args_list], ['f'])
        self.assertGreaterEqual(t._release.call_count, 3)

    def test_lost_upper_state_stops_without_f(self):
        t = self.task()
        t._prompt.return_value = False
        t._upper_end.return_value = False
        t.walk_to_box.side_effect = lambda find, **kw: kw['end_condition']()
        with self.assertRaisesRegex(RuntimeError, '提示消失'):
            AutoSeaRuinsTask._enter_lower(t)
        t.send_key.assert_not_called()
        self.assertGreaterEqual(t._release.call_count, 2)

    def test_missing_marker_stops_and_releases_without_f(self):
        t = self.task()
        t.walk_to_box.side_effect = lambda find, **kw: find()
        with patch('src.task.AutoSeaRuinsTask.vision.exit_marker', return_value=None):
            with self.assertRaisesRegex(RuntimeError, '标记丢失'):
                AutoSeaRuinsTask._enter_lower(t)
        t.send_key.assert_not_called()
        self.assertGreaterEqual(t._release.call_count, 2)

    def test_walking_timeout_and_disappeared_prompt_do_not_press_f(self):
        for result in (False, True):
            t = self.task()
            t.walk_to_box.return_value = result
            t._prompt.return_value = False
            with self.assertRaises(RuntimeError):
                AutoSeaRuinsTask._enter_lower(t)
            t.send_key.assert_not_called()

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
