import unittest
from unittest.mock import Mock, patch
from types import MethodType
import numpy as np
import cv2
from src.task import sea_ruins_vision as vision
from ok import TaskDisabledException
from src.task.AutoSeaRuinsTask import AutoSeaRuinsTask, SeaExitMarkerLost


class TestSeaExitRecovery(unittest.TestCase):
    def setup_walk(self):
        t = Mock()
        t.frame = np.zeros((720, 1280, 3), np.uint8)
        t.width, t.height, t._exit_detours = 1280, 720, 0
        t._backstep_sea_exit = MethodType(AutoSeaRuinsTask._backstep_sea_exit, t)
        t.in_team_and_world.return_value = True
        now = [0.]
        def walk(find, **kw):
            self.assertLessEqual(kw['time_out'], 1.)
            now[0] += kw['time_out']
            return False
        def send(key, down_time):
            self.assertLessEqual(down_time, .25)
            now[0] += down_time
        t.walk_to_box.side_effect = walk
        t.send_key.side_effect = send
        target = Mock()
        target.center.return_value = (640, 120)
        return t, now, Mock(return_value=target)

    def test_stall_has_three_bounded_detours_and_releases(self):
        t, now, find = self.setup_walk()
        with patch('src.task.AutoSeaRuinsTask.time.monotonic', side_effect=lambda: now[0]):
            with self.assertRaisesRegex(RuntimeError, '3轮'):
                AutoSeaRuinsTask._walk_sea_exit(t, find, time_out=60, end_condition=lambda: False)
        self.assertEqual(t._exit_detours, 3)
        t.middle_click.assert_not_called()
        self.assertEqual([c.args[0] for c in t.send_key.call_args_list],
                         ['s'] * 12)
        self.assertLess(now[0], 60)
        t._release.assert_called()
        t.ensure_in_front.assert_not_called()

    def test_prompt_during_detour_stops_before_next_key(self):
        t, now, find = self.setup_walk()
        with patch('src.task.AutoSeaRuinsTask.time.monotonic', side_effect=lambda: now[0]):
            self.assertTrue(AutoSeaRuinsTask._walk_sea_exit(t, find, time_out=60,
                end_condition=lambda: t.send_key.call_count == 1))
        self.assertEqual(t.send_key.call_count, 1)

    def test_deadline_during_backstep_never_extends_budget(self):
        t, now, find = self.setup_walk()
        with patch('src.task.AutoSeaRuinsTask.time.monotonic', side_effect=lambda: now[0]):
            self.assertFalse(AutoSeaRuinsTask._walk_sea_exit(t, find, time_out=10.1,
                end_condition=lambda: False))
        self.assertAlmostEqual(now[0], 10.1)
        t.middle_click.assert_not_called()
        self.assertTrue(all(c.args[0] == 's' for c in t.send_key.call_args_list))

    def test_state_loss_and_cancel_during_backstep_release(self):
        for error in (RuntimeError('upper state lost'), TaskDisabledException()):
            t, now, find = self.setup_walk()
            def ended():
                if t.send_key.call_count:
                    raise error
                return False
            with patch('src.task.AutoSeaRuinsTask.time.monotonic', side_effect=lambda: now[0]):
                with self.assertRaises(type(error)):
                    AutoSeaRuinsTask._walk_sea_exit(t, find, time_out=60, end_condition=ended)
            self.assertEqual(t.send_key.call_count, 1)
            t._release.assert_called()

    def test_scene_progress_avoids_detour_and_heading_restarts(self):
        t, now, find = self.setup_walk()
        def walk(probe, **kw):
            now[0] += kw['time_out']
            t.frame[:] += 10
            return t.walk_to_box.call_count == 8
        t.walk_to_box.side_effect = walk
        with patch('src.task.AutoSeaRuinsTask.time.monotonic', side_effect=lambda: now[0]):
            self.assertTrue(AutoSeaRuinsTask._walk_sea_exit(t, find, time_out=60, end_condition=lambda: False))
        self.assertEqual(t.walk_to_box.call_count, 8)
        self.assertTrue(all(c.kwargs['time_out'] <= 1 for c in t.walk_to_box.call_args_list))
        t.send_key.assert_not_called()

    def test_arrived_without_marker_does_not_move(self):
        t, now, find = self.setup_walk()
        find.side_effect = SeaExitMarkerLost()
        with patch('src.task.AutoSeaRuinsTask.time.monotonic', side_effect=lambda: now[0]):
            self.assertTrue(AutoSeaRuinsTask._walk_sea_exit(t, find, time_out=60, end_condition=lambda: True))
        find.assert_not_called()
        t.walk_to_box.assert_not_called()
        t.send_key.assert_not_called()

    def test_animated_scene_still_backs_away_from_off_center_marker(self):
        t, now, find = self.setup_walk()
        find.return_value.center.return_value = (1000, 400)
        def walk(probe, **kw):
            now[0] += kw['time_out']
            t.frame[:] += 10  # moving water defeats the static-scene stall check
            return t.walk_to_box.call_count == 8
        t.walk_to_box.side_effect = walk
        with patch('src.task.AutoSeaRuinsTask.time.monotonic', side_effect=lambda: now[0]):
            self.assertTrue(AutoSeaRuinsTask._walk_sea_exit(t, find, time_out=60,
                end_condition=lambda: False))
        t.middle_click.assert_not_called()
        self.assertEqual(t._exit_detours, 1)
        self.assertEqual([c.args[0] for c in t.send_key.call_args_list], ['s'] * 4)

    def test_brief_off_center_marker_does_not_recenter(self):
        t, now, find = self.setup_walk()
        def probe():
            target = Mock()
            target.center.return_value = (1000 if 8 <= now[0] < 11 else 640, 400)
            return target
        def walk(target, **kw):
            now[0] += kw['time_out']
            t.frame[:] += 10
            return t.walk_to_box.call_count == 14
        t.walk_to_box.side_effect = walk
        with patch('src.task.AutoSeaRuinsTask.time.monotonic', side_effect=lambda: now[0]):
            self.assertTrue(AutoSeaRuinsTask._walk_sea_exit(t, probe, time_out=60,
                end_condition=lambda: False))
        t.middle_click.assert_not_called()

    def test_marker_crossing_uses_s_until_prompt_then_stops(self):
        t, now, find = self.setup_walk()
        frames = [cv2.imread(f'tests/fixtures/sea_ruins/exit_cross_{side}_20260927.png')
                  for side in ('left', 'right')]
        def probe():
            t.frame = frames[int(now[0] >= 2)]
            x, y, _ = vision.exit_marker(t.frame)
            find.return_value.center.return_value = (x*t.width, y*t.height)
            return find.return_value
        with patch('src.task.AutoSeaRuinsTask.time.monotonic', side_effect=lambda: now[0]):
            self.assertTrue(AutoSeaRuinsTask._walk_sea_exit(t, probe, time_out=20,
                end_condition=lambda: t.send_key.call_count == 2))
        self.assertEqual([c.args[0] for c in t.send_key.call_args_list], ['s', 's'])
        t.middle_click.assert_not_called()
        self.assertEqual(t.walk_to_box.call_count, 2)

    def test_backstep_without_world_never_moves(self):
        t, now, find = self.setup_walk()
        t.in_team_and_world.return_value = False
        with self.assertRaisesRegex(RuntimeError, '地图状态'):
            t._backstep_sea_exit(60, lambda: False)
        t.send_key.assert_not_called()
        t._release.assert_called()

    def test_backstep_clips_each_key_to_remaining_deadline(self):
        t, now, find = self.setup_walk()
        with patch('src.task.AutoSeaRuinsTask.time.monotonic', side_effect=lambda: now[0]):
            self.assertFalse(t._backstep_sea_exit(.4, lambda: False))
        self.assertEqual([c.args[0] for c in t.send_key.call_args_list], ['s', 's'])
        self.assertAlmostEqual(now[0], .4)

    def test_detour_budget_survives_marker_recovery_restart(self):
        t, now, find = self.setup_walk()
        t._exit_detours = 3
        with patch('src.task.AutoSeaRuinsTask.time.monotonic', side_effect=lambda: now[0]):
            with self.assertRaisesRegex(RuntimeError, '3轮'):
                AutoSeaRuinsTask._walk_sea_exit(t, find, time_out=60, end_condition=lambda: False)
        t.send_key.assert_not_called()
