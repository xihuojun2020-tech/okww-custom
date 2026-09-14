import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

from ok import TaskDisabledException
from src.task.BaseWWTask import BaseWWTask
from src.task.DomainTask import DomainTask
from src.task.DailyTask import DailyTask


class TestDailyFailureRecovery(unittest.TestCase):
    def stamina_task(self, values):
        task = Mock(spec=BaseWWTask)
        task.executor = Mock()
        task.get_stamina.side_effect = values
        return task

    def test_unknown_retries_fresh_frames_then_accepts_real_zero(self):
        task = self.stamina_task([(-1, 122, 121), (0, 122, 122)])
        self.assertEqual((0, 122, 122), BaseWWTask.get_verified_stamina(task))
        self.assertEqual(2, task.next_frame.call_count)
        task.screenshot.assert_not_called()

    def test_persistent_unknown_is_failure_not_insufficient_stamina(self):
        task = self.stamina_task([(-1, 122, 121)] * 3)
        with self.assertRaisesRegex(RuntimeError, '待补跑'):
            BaseWWTask.get_verified_stamina(task)
        self.assertEqual(3, task.get_stamina.call_count)
        task.screenshot.assert_called_once()

    def test_stamina_cancellation_propagates_before_ocr(self):
        task = self.stamina_task([])
        task.executor.check_enabled.side_effect = TaskDisabledException()
        with self.assertRaises(TaskDisabledException):
            BaseWWTask.get_verified_stamina(task)
        task.get_stamina.assert_not_called()

    def test_map_close_icon_is_not_formation(self):
        task = Mock(spec=BaseWWTask)
        travel = SimpleNamespace(name='fast_travel_custom')
        task.find_one.side_effect = lambda names, **kw: travel if 'fast_travel_custom' in names else None
        task.wait_until.side_effect = lambda predicate, **kw: predicate()
        self.assertIs(travel, BaseWWTask.wait_book_target_state(task))
        self.assertNotIn('team_close', task.find_one.call_args.args[0])

    def test_disabled_travel_reports_target_without_click(self):
        task = Mock(spec=BaseWWTask)
        task.ocr.return_value = [SimpleNamespace(name='附近信标无法快速到达')]
        task._travel_identity.return_value = ('方擎西峰无音区',)
        with self.assertRaisesRegex(RuntimeError, '方擎西峰无音区'):
            BaseWWTask._check_travel_unavailable(task, object())
        task.click.assert_not_called()

    def test_world_overlay_wait_does_not_escape_again(self):
        task = Mock(spec=DomainTask)
        task.wait_until.return_value = True
        DomainTask.make_sure_in_world(task)
        task.send_key.assert_not_called()
        task.ensure_main.assert_not_called()

    def test_world_signal_inside_realm_is_not_exit(self):
        task = Mock(spec=DomainTask)
        task.in_team_and_world.return_value = True
        task.in_realm.return_value = True
        self.assertFalse(DomainTask._returned_to_world(task))
        task.next_frame.assert_called_once()

    def test_unknown_exit_times_out_without_escape_spam(self):
        task = Mock(spec=DomainTask)
        task.teleport_timeout = 100
        task.wait_until.return_value = False
        task.in_realm.return_value = False
        with self.assertRaisesRegex(RuntimeError, '退出副本'):
            DomainTask.make_sure_in_world(task)
        task.send_key.assert_not_called()
        task.screenshot.assert_called_once()

    def test_unknown_map_never_returns_generic_close_as_formation(self):
        task = Mock(spec=BaseWWTask)
        task.find_one.return_value = None
        task._team_start_button.return_value = None
        task._single_challenge_entry.return_value = None
        task.wait_until.side_effect = lambda predicate, **kw: predicate()
        self.assertIsNone(BaseWWTask.wait_book_target_state(task))

    def test_checkpoint_scope_changes_with_mode_and_targets(self):
        task = Mock(spec=DailyTask)
        values = {}
        task._profile_get.side_effect = lambda key, default: values.get(key, default)
        full = DailyTask._nightmare_checkpoint_key(task, True)
        self.assertNotEqual(full, DailyTask._nightmare_checkpoint_key(task, False))
        values['Tacet Discord Nests to Farm'] = ['另一个聚落']
        self.assertNotEqual(full, DailyTask._nightmare_checkpoint_key(task, True))

    def test_checkpoint_refresh_boundary_missing_and_future(self):
        task = Mock(spec=DailyTask)
        now = datetime(2026, 9, 14, 4, 1)
        for stamp, expected in [(None, False), ('invalid', False),
                                ('2026-09-14 03:59:00', False),
                                ('2026-09-14 04:00:00', True),
                                ('2026-09-15 04:00:00', False)]:
            task.get_last_completed.return_value = stamp
            self.assertEqual(expected, DailyTask._daily_step_completed(task, 'scoped', now))


if __name__ == '__main__':
    unittest.main()
