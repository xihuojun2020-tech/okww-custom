import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.task.weekly_boss import (
    WEEKLY_BOSSES, parse_remaining, parse_cost, parse_stamina, match_target_button,
)
from src.task.WeeklyBossTask import WeeklyBossTask


def box(name, x=0, y=0, width=100, height=30):
    return SimpleNamespace(name=name, x=x, y=y, width=width, height=height)


class TestWeeklyBossParsing(unittest.TestCase):
    def test_remaining_requires_label_and_valid_unique_fraction(self):
        for n in range(4):
            self.assertEqual(parse_remaining(f'本周剩余可收取次数：{n}/3'), n)
        for text in ('3/3', '本周剩余可收取次数：4/3',
                     '本周剩余可收取次数：1/8', '本周剩余可收取次数：',
                     '本周剩余可收取次数：1/3 2/3'):
            with self.subTest(text=text):
                self.assertIsNone(parse_remaining(text))
        self.assertEqual(parse_remaining('本周剩余可收取次数: ２／３'), 2)

    def test_cost_and_stamina_do_not_read_reward_quantities(self):
        self.assertEqual(parse_cost('x60'), 60)
        self.assertIsNone(parse_cost('450 60'))
        self.assertEqual(parse_stamina('228/240'), 228)
        self.assertIsNone(parse_stamina('3/3'))
        self.assertIsNone(parse_stamina('228/240 5/240'))

    def test_targets_are_ten_distinct_ids_in_user_order(self):
        self.assertEqual(len(WEEKLY_BOSSES), 10)
        self.assertEqual(len({b.key for b in WEEKLY_BOSSES}), 10)
        self.assertEqual(WEEKLY_BOSSES[1].name, '虚妄诞生之种')
        self.assertEqual(WEEKLY_BOSSES[-1].name, '昔日咏叹之钟')

    def test_button_must_belong_to_same_row(self):
        name = '虚妄诞生之种'
        title = box(name + '·战歌重奏', 900, 600, 350, 32)
        right = box('直接挑战', 1750, 640, 150, 36)
        wrong = box('直接挑战', 1750, 800, 150, 36)
        self.assertIs(match_target_button([title, wrong, right], name, 1152), right)
        self.assertIsNone(match_target_button([title, wrong], name, 1152))
        self.assertIsNone(match_target_button([title, right, box('直接挑战', 1750, 645)], name, 1152))


class TestWeeklyBossFlow(unittest.TestCase):
    def task(self, count, stamina=240, final=0):
        task = object.__new__(WeeklyBossTask)
        task.info = {}
        task.logger = Mock()
        task.config = {'Weekly Boss': WEEKLY_BOSSES[1].key, 'Use Liberation': True}
        for method in ('_stage', '_open_weekly_book', 'ensure_main', '_select_target',
                       '_enter_challenge', '_fight_and_claim', '_leave_settlement',
                       '_wait_for', '_release_movement', 'reset_to_false'):
            setattr(task, method, Mock())
        task._read_remaining = Mock(side_effect=[count, count, final] if count else [0])
        task._read_entry_resources = Mock(return_value=(60, stamina))
        task._fight_and_claim.side_effect = [stamina - 60 * (i + 1) for i in range(count)]
        return task

    def test_remaining_controls_claims_and_retries(self):
        for n in range(4):
            with self.subTest(n=n):
                task = self.task(n)
                result = task.run_weekly()
                self.assertTrue(result.complete)
                self.assertEqual(result.claimed, n)
                self.assertEqual(task._fight_and_claim.call_count, n)
                actions = [c.args[0] for c in task._leave_settlement.call_args_list]
                self.assertEqual(actions, [True] * max(n - 1, 0) + ([False] if n else []))

    def test_nonzero_recheck_is_not_success(self):
        task = self.task(2, final=1)
        with self.assertRaisesRegex(RuntimeError, '剩余'):
            task.run_weekly()

    def test_mismatch_on_detail_prevents_entry(self):
        task = self.task(3)
        task._read_remaining.side_effect = [3, 2]
        with self.assertRaisesRegex(RuntimeError, '次数'):
            task.run_weekly()
        task._enter_challenge.assert_not_called()

    def test_insufficient_stamina_never_enters(self):
        task = self.task(3, stamina=5)
        task._read_remaining.side_effect = [3, 3, 3]
        with self.assertRaisesRegex(RuntimeError, '体力不足'):
            task.run_weekly()
        task._enter_challenge.assert_not_called()

    def test_partial_claim_exits_before_next_fight(self):
        task = self.task(3, stamina=65, final=2)
        with self.assertRaisesRegex(RuntimeError, '体力不足'):
            task.run_weekly()
        self.assertEqual(task._fight_and_claim.call_count, 1)
        task._leave_settlement.assert_called_once_with(False)

    def test_claim_failure_or_stop_never_retries(self):
        from ok import TaskDisabledException
        for error in (RuntimeError('领奖未知'), TaskDisabledException('stop')):
            task = self.task(3)
            task._fight_and_claim.side_effect = error
            with self.assertRaises(type(error)):
                task.run_weekly()
            task._leave_settlement.assert_not_called()
            self.assertEqual(task.info.get('已确认领奖', 0), 0)

    def test_failed_retry_does_not_count_another_reward(self):
        task = self.task(3)
        task._leave_settlement.side_effect = RuntimeError('加载超时')
        with self.assertRaises(RuntimeError):
            task.run_weekly()
        self.assertEqual(task._fight_and_claim.call_count, 1)
        self.assertEqual(task.info['已确认领奖'], 1)

    def test_unknown_balance_exits_and_rechecks(self):
        task = self.task(2, final=1)
        task._fight_and_claim.side_effect = [None]
        with self.assertRaisesRegex(RuntimeError, '体力未知'):
            task.run_weekly()
        task._leave_settlement.assert_called_once_with(False)
        self.assertEqual(task.last_result.remaining, 1)


class TestWeeklyBossBoundaries(unittest.TestCase):
    def task(self):
        task = object.__new__(WeeklyBossTask)
        task.logger = Mock()
        task.info = {}
        task._executor = SimpleNamespace(frame=None, next_frame=Mock())
        task.next_frame = Mock()
        task.sleep = Mock()
        task._stage = Mock()
        return task

    def test_stable_zero_and_flicker_use_new_frames(self):
        task = self.task()
        probe = Mock(side_effect=[3, None, 2, 0, 0])
        self.assertEqual(task._stable_value(probe, 'unknown'), 0)
        self.assertEqual(task.next_frame.call_count, 5)

    def test_timeout_is_bounded_and_does_not_click(self):
        from src.task.WeeklyBossTask import WeeklyPageTimeout
        task = self.task()
        task.click = Mock()
        with patch('src.task.WeeklyBossTask.time.monotonic', side_effect=[0, 1, 16]):
            with self.assertRaises(WeeklyPageTimeout):
                task._wait_for(lambda: None, 'unknown')
        task.click.assert_not_called()

    def test_stop_and_capture_loss_propagate_from_ocr_wait(self):
        from ok import TaskDisabledException
        from src.runtime.game_runtime_errors import FrameUnavailable, GameProcessLost
        for error in (TaskDisabledException(), FrameUnavailable('frame'), GameProcessLost('game')):
            task = self.task()
            with self.assertRaises(type(error)):
                task._stable_value(Mock(side_effect=error), 'unknown')

    def test_claim_once_then_stable_balance_no_cancel_handler(self):
        task = self.task()
        task._fight = Mock()
        task._reward_available = Mock(return_value=True)
        task._settlement = Mock(return_value=(object(), object()))
        task.send_key = Mock()
        task.get_settlement_stamina = Mock(side_effect=[169, 169])
        task.handle_claim_button = Mock()
        self.assertEqual(task._fight_and_claim(60), 169)
        task.send_key.assert_called_once_with('f')
        task.handle_claim_button.assert_not_called()

    def test_unknown_claim_screen_never_counts_as_reward(self):
        from src.task.WeeklyBossTask import WeeklyPageTimeout
        task = self.task()
        task._fight = Mock()
        task._reward_available = Mock(return_value=True)
        task._wait_for = Mock(side_effect=[True, WeeklyPageTimeout('unknown')])
        task.send_key = Mock()
        task.get_settlement_stamina = Mock()
        with self.assertRaises(WeeklyPageTimeout):
            task._fight_and_claim(60)
        task.get_settlement_stamina.assert_not_called()

    def test_capture_loss_after_reward_is_not_swallowed_as_low_stamina(self):
        from src.runtime.game_runtime_errors import FrameUnavailable
        task = self.task()
        task._fight = Mock()
        task._reward_available = Mock(return_value=True)
        task._wait_for = Mock(return_value=True)
        task.send_key = Mock()
        task._stable_value = Mock(side_effect=FrameUnavailable('lost'))
        with self.assertRaises(FrameUnavailable):
            task._fight_and_claim(60)

    def test_retry_button_is_clicked_once_if_loading_times_out(self):
        from src.task.WeeklyBossTask import WeeklyPageTimeout
        task = self.task()
        exit_button, retry_button = object(), object()
        task._wait_for = Mock(side_effect=[(exit_button, retry_button), True, WeeklyPageTimeout('loading')])
        task.click_box = Mock()
        with self.assertRaises(WeeklyPageTimeout):
            task._leave_settlement(True)
        task.click_box.assert_called_once_with(retry_button)

    def test_no_weekly_target_does_not_fall_back_to_first(self):
        task = self.task()
        task.config = {'Weekly Boss': 'deleted_target'}
        task._open_weekly_book = Mock()
        with self.assertRaises(ValueError):
            task.run_weekly()
        task._open_weekly_book.assert_not_called()

    def test_guidebook_no_target_and_no_scroll_progress_stops(self):
        task = self.task()
        task.scroll_relative = Mock()
        task._ocr = Mock(return_value=[box('other title')])
        task._executor.method = SimpleNamespace(height=1440)
        task.click_box = Mock()
        with self.assertRaisesRegex(RuntimeError, '未找到'):
            task._select_target(WEEKLY_BOSSES[0])
        task.click_box.assert_not_called()
        self.assertLessEqual(task.scroll_relative.call_count, 4)

    def test_navigation_and_registration(self):
        from config import config
        from src.gui.navigation_sections import classify_task
        self.assertIn(['src.task.WeeklyBossTask', 'WeeklyBossTask'], config['onetime_tasks'])
        self.assertEqual(classify_task(self.task()), 'tests')


if __name__ == '__main__':
    unittest.main()
