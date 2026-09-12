"""Offline regressions for default weekly selection; no game interaction."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests import TestWeeklyBossTask as weekly_tests
from tests.TestWeeklyBossTask import box
from src.task.WeeklyBossTask import WeeklyBossTask, WeeklyPageTimeout
from src.task.weekly_boss import WEEKLY_AUTO, WEEKLY_BOSSES, match_target_button, weekly_title_rows


class TestWeeklyNavigation(unittest.TestCase):
    def task(self, remaining=3):
        task = weekly_tests.TestWeeklyBossFlow().task(remaining)
        task._executor = SimpleNamespace(method=SimpleNamespace(height=1440))
        for name in ('next_frame', 'sleep', 'scroll_relative', 'click_relative',
                     'click_box', 'screenshot', '_select_first_target'):
            setattr(task, name, Mock())
        return task

    def rows(self, boss=None):
        boss = boss or WEEKLY_BOSSES[0]
        return [box(boss.name, 1180, 500, 210),
                box('·战歌重奏', 1395, 503, 160),
                box('直接挑战', 2100, 550, 200)]

    def test_completed_auto_never_reads_titles(self):
        task = self.task(0)
        with patch('src.evidence.service.record_task_evidence'):
            self.assertTrue(task.run_weekly(WEEKLY_AUTO).complete)
        task._select_first_target.assert_not_called()
        task._select_target.assert_not_called()

    def test_split_title_matches_only_same_row(self):
        rows = self.rows()
        self.assertIs(match_target_button(rows, WEEKLY_BOSSES[0].name, 1440), rows[-1])
        rows[1].y += 100
        self.assertNotIn('失坠困咎之庭·战歌重奏', [b.name for b in weekly_title_rows(rows, 1440)])
        rows[-1].y += 300
        self.assertIsNone(match_target_button(rows, WEEKLY_BOSSES[0].name, 1440))

    def test_partial_name_cannot_match_another_row(self):
        rows = [box('失坠困', 1180, 500, 100), box('咎之庭·战歌重奏', 1285, 700, 220),
                box('直接挑战', 2100, 550)]
        self.assertIsNone(match_target_button(rows, WEEKLY_BOSSES[0].name, 1440))

    def test_auto_waits_for_two_matching_fresh_frames(self):
        task = self.task()
        task._confirm_list_top = Mock()
        rows = self.rows(WEEKLY_BOSSES[2])
        task._ocr = Mock(side_effect=[[], rows, [], rows, rows])
        result = WeeklyBossTask._select_first_target(task)
        self.assertEqual(result, WEEKLY_BOSSES[2])
        self.assertEqual(task.next_frame.call_count, 5)
        task.click_box.assert_called_once_with(rows[-1])

    def test_unknown_first_title_never_selects_second(self):
        task = self.task()
        task._confirm_list_top = Mock()
        rows = [box('未知名称·战歌重奏', 1180, 300, 350)] + self.rows()
        task._ocr = Mock(return_value=rows)
        with self.assertRaises(WeeklyPageTimeout):
            WeeklyBossTask._select_first_target(task)
        task.click_box.assert_not_called()
        self.assertEqual(task._ocr.call_count, 6)

    def test_top_requires_observed_movement_then_stability(self):
        task = self.task()
        task._list_signature = Mock(side_effect=[(('middle', .4),), (('first', .35),),
                                                (('first', .35),), (('first', .35),)])
        task._confirm_list_top()
        self.assertEqual(task.click_relative.call_count, 3)

    def test_unreadable_first_row_does_not_promote_second(self):
        task = self.task()
        task._confirm_list_top = Mock()
        task._ocr = Mock(return_value=[box('直接挑战', 2100, 350)] + self.rows())
        with self.assertRaises(WeeklyPageTimeout):
            WeeklyBossTask._select_first_target(task)
        task.click_box.assert_not_called()

    def test_detail_mismatch_never_enters_battle(self):
        task = self.task()
        task._confirm_list_top = Mock()
        task._ocr = Mock(return_value=self.rows())
        task._wait_for.side_effect = WeeklyPageTimeout('详情页不一致')
        task._select_first_target = lambda: WeeklyBossTask._select_first_target(task)
        with self.assertRaisesRegex(WeeklyPageTimeout, '详情页不一致'):
            task.run_weekly(WEEKLY_AUTO)
        task._enter_challenge.assert_not_called()
        self.assertEqual(task._open_weekly_book.call_count, 2)

    def test_stuck_scroll_is_not_top(self):
        task = self.task()
        task._list_signature = Mock(return_value=(('middle', .4),))
        with self.assertRaisesRegex(WeeklyPageTimeout, '回到顶部'):
            task._confirm_list_top()
        self.assertEqual(task.click_relative.call_count, 6)
        task.click_box.assert_not_called()

    def test_navigation_retries_once_and_rereads_count(self):
        task = self.task()
        task._read_remaining.side_effect = [3, 0]
        task._select_first_target.side_effect = WeeklyPageTimeout('title')
        with patch('src.evidence.service.record_task_evidence'):
            self.assertTrue(task.run_weekly(WEEKLY_AUTO).complete)
        self.assertEqual(task._open_weekly_book.call_count, 2)
        task._fight_and_claim.assert_not_called()

    def test_unknown_remaining_never_selects_or_completes(self):
        task = self.task()
        task._read_remaining.side_effect = WeeklyPageTimeout('count')
        with self.assertRaisesRegex(WeeklyPageTimeout, 'count'):
            task.run_weekly(WEEKLY_AUTO)
        self.assertEqual(task._open_weekly_book.call_count, 2)
        task._select_first_target.assert_not_called()
        self.assertIsNone(task.last_result)

    def test_stop_and_capture_loss_are_not_navigation_retries(self):
        from ok import TaskDisabledException
        from src.runtime.game_runtime_errors import FrameUnavailable
        for error in (TaskDisabledException(), FrameUnavailable('lost')):
            task = self.task()
            task._open_weekly_book.side_effect = error
            with self.assertRaises(type(error)):
                task.run_weekly(WEEKLY_AUTO)
            self.assertEqual(task._open_weekly_book.call_count, 1)

    def test_reward_failure_never_reopens_navigation(self):
        task = self.task()
        task._fight_and_claim.side_effect = WeeklyPageTimeout('reward unknown')
        with self.assertRaisesRegex(WeeklyPageTimeout, 'reward unknown'):
            task.run_weekly(WEEKLY_AUTO)
        self.assertEqual(task._open_weekly_book.call_count, 1)
        self.assertEqual(task._fight_and_claim.call_count, 1)


if __name__ == '__main__':
    unittest.main()
