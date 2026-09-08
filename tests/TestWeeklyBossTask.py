import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.task.weekly_boss import (
    WEEKLY_BOSSES, combat_phase, parse_remaining, parse_cost, parse_stamina,
    match_target_button,
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

    def test_combat_phase_uses_objective_meaning_not_text_change(self):
        for text in ('击败敌人', '击败伤痕', '与岁主「角」对战'):
            self.assertEqual(combat_phase(text), 'combat')
        for text in ('领取奖励', '离开某地'):
            self.assertEqual(combat_phase(text), 'post')
        for text in ('', '剧情过场', '无法识别'):
            self.assertIsNone(combat_phase(text))


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
    def confirmation_task(self, cost=60, stamina=123):
        task = self.task()
        task._settlement = Mock(return_value=None)
        task.confirm_button = box('确认')
        task._claim_confirmation = Mock(return_value=(cost, stamina, task.confirm_button))
        task.click_box = Mock()
        return task

    def test_reward_confirmation_clicks_once_after_stable_resources(self):
        task = self.confirmation_task()
        task._confirm_claim_if_needed(60)
        self.assertEqual(task._claim_confirmation.call_count, 2)
        task.click_box.assert_called_once_with(task.confirm_button)
        self.assertNotIn('已确认领奖', task.info)

    def test_reward_confirmation_rejects_cost_mismatch_and_low_stamina(self):
        for cost, stamina in ((120, 123), (60, 59)):
            task = self.confirmation_task(cost, stamina)
            with self.assertRaises(RuntimeError):
                task._confirm_claim_if_needed(60)
            task.click_box.assert_not_called()

    def test_direct_settlement_needs_no_confirmation_click(self):
        task = self.confirmation_task()
        task._settlement.return_value = (object(), object())
        task._confirm_claim_if_needed(60)
        task.click_box.assert_not_called()
        task._claim_confirmation.assert_not_called()

    def test_unrecognized_confirmation_does_not_click(self):
        from src.task.WeeklyBossTask import WeeklyPageTimeout
        task = self.confirmation_task()
        task._claim_confirmation.return_value = None
        with patch('src.task.WeeklyBossTask.time.monotonic', side_effect=[0, 1, 21]):
            with self.assertRaises(WeeklyPageTimeout):
                task._confirm_claim_if_needed(60)
        task.click_box.assert_not_called()

    def test_confirmation_is_not_repeated_when_settlement_times_out(self):
        from src.task.WeeklyBossTask import WeeklyPageTimeout
        task = self.confirmation_task()
        task._fight = Mock()
        task._reward_available = Mock(return_value=True)
        task.send_key = Mock()
        task._settlement.side_effect = [None, None, WeeklyPageTimeout('no settlement')]
        with self.assertRaises(WeeklyPageTimeout):
            task._fight_and_claim(60)
        task.click_box.assert_called_once_with(task.confirm_button)
        task.send_key.assert_called_once_with('f')

    def test_confirmation_then_settlement_returns_balance(self):
        task = self.confirmation_task()
        task._fight = Mock()
        task._reward_available = Mock(return_value=True)
        task.send_key = Mock()
        task.get_settlement_stamina = Mock(return_value=63)
        task._settlement.side_effect = lambda: (object(), object()) if task.click_box.called else None
        self.assertEqual(task._fight_and_claim(60), 63)
        task.click_box.assert_called_once_with(task.confirm_button)
        self.assertNotIn('已确认领奖', task.info)

    def test_confirmation_capture_loss_and_stop_never_click(self):
        from ok import TaskDisabledException
        from src.runtime.game_runtime_errors import FrameUnavailable
        for error in (TaskDisabledException(), FrameUnavailable('lost')):
            task = self.confirmation_task()
            task._claim_confirmation.side_effect = error
            with self.assertRaises(type(error)):
                task._confirm_claim_if_needed(60)
            task.click_box.assert_not_called()

    def test_confirmation_parser_rejects_other_spending_dialogs(self):
        task = self.task()
        valid = '领取奖励需消耗60点结晶波片，请确认是否领取？'
        for message, stamina, missing in (
                (valid, '123/240', None), (valid, '0/240', None),
                ('领取奖励需消耗60点星声，请确认是否领取？', '123/240', None),
                (valid + '补充体力', '123/240', None), (valid, '123', None),
                (valid.replace('60', '0'), '123/240', None),
                (valid, '123/240', '确认'), (valid, '123/240', '取消')):
            task._text = Mock(side_effect=lambda region, frame: {
                task.CLAIM_TITLE: '领取奖励', task.CLAIM_MESSAGE: message,
                task.CLAIM_STAMINA: stamina}[region])
            task._button = Mock(side_effect=lambda region, text, frame: None if text == missing else box(text))
            result = task._claim_confirmation()
            if message == valid and stamina in ('123/240', '0/240') and missing is None:
                self.assertEqual(result[:2], (60, int(stamina.split('/')[0])))
            else:
                self.assertIsNone(result)

    def combat_task(self, error):
        task = self.task()
        task.wait_until = Mock(return_value=True)
        task.combat_once = Mock(side_effect=error)
        task._release_movement = Mock()
        task.reset_to_false = Mock()
        task.combat_end = Mock()
        task._wait_combat_phase = Mock(return_value='post')
        return task

    def test_unknown_combat_recovers_only_after_victory_evidence(self):
        from src.task.BaseCombatTask import CombatStateUnknown
        task = self.combat_task(CombatStateUnknown('liberation timeout'))
        task._fight()
        task._wait_combat_phase.assert_called_once_with()
        task.combat_end.assert_called_once()
        self.assertTrue(task.skip_combat_check)
        self.assertNotIn('已确认领奖', task.info)

    def test_unknown_combat_without_evidence_remains_failure(self):
        from src.task.BaseCombatTask import CombatStateUnknown
        from src.task.WeeklyBossTask import WeeklyPageTimeout
        error = CombatStateUnknown('liberation timeout')
        task = self.combat_task(error)
        task._wait_combat_phase.side_effect = WeeklyPageTimeout('no victory')
        with self.assertRaises(CombatStateUnknown) as caught:
            task._fight()
        self.assertIs(caught.exception, error)
        task.combat_end.assert_not_called()

    def test_death_stop_and_capture_loss_are_not_victory(self):
        from ok import TaskDisabledException
        from src.task.BaseCombatTask import CharDeadException
        from src.runtime.game_runtime_errors import FrameUnavailable
        for error in (CharDeadException(), TaskDisabledException(), FrameUnavailable('lost')):
            task = self.combat_task(error)
            with self.assertRaises(type(error)):
                task._fight()
            task._wait_combat_phase.assert_not_called()

    def test_stop_during_victory_verification_propagates(self):
        from ok import TaskDisabledException
        from src.task.BaseCombatTask import CombatStateUnknown
        task = self.combat_task(CombatStateUnknown('timeout'))
        task._wait_combat_phase.side_effect = TaskDisabledException()
        with self.assertRaises(TaskDisabledException):
            task._fight()
        task.combat_end.assert_not_called()

    def test_normal_combat_return_with_next_phase_continues_without_claim(self):
        task = self.combat_task(None)
        task._wait_combat_phase.side_effect = ['combat', 'post']
        task._wait_for = Mock(return_value=True)
        task.in_combat = Mock(return_value=True)
        task._fight()
        self.assertEqual(task.combat_once.call_count, 2)
        task._wait_for.assert_called_once()
        task.combat_end.assert_not_called()
        self.assertNotIn('已确认领奖', task.info)

    def test_battle_hint_overrides_victory_and_reward_auxiliary_signals(self):
        task = self.task()
        task._text = Mock(return_value='击败伤痕')
        task._reward_available = Mock(return_value=object())
        task._button = Mock(return_value=object())
        self.assertFalse(task._battle_finished())

    def test_unknown_phase_after_normal_return_stops(self):
        from src.task.WeeklyBossTask import WeeklyPageTimeout
        task = self.combat_task(None)
        task._wait_combat_phase.side_effect = WeeklyPageTimeout('unknown')
        with self.assertRaises(WeeklyPageTimeout):
            task._fight()
        self.assertEqual(task.combat_once.call_count, 1)

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
        task._confirm_claim_if_needed = Mock()
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
        task.click_relative = Mock()
        with self.assertRaisesRegex(RuntimeError, '未确认列表翻页'):
            task._select_target(WEEKLY_BOSSES[0])
        task.click_box.assert_not_called()
        self.assertLessEqual(task.scroll_relative.call_count, 4)
        self.assertEqual(task.click_relative.call_count, 14)
        self.assertAlmostEqual(task.click_relative.call_args.args[1], 0.88)

    def test_stuck_wheel_uses_scrollbar_until_target_appears(self):
        task = self.task()
        task._executor.method = SimpleNamespace(height=1440)
        task.scroll_relative = Mock()
        task.click_relative = Mock()
        task.click_box = Mock()
        task._wait_for = Mock()
        boss = WEEKLY_BOSSES[8]
        title = box(boss.name + '·战歌重奏', 900, 600, 350)
        button = box('直接挑战', 1750, 640)
        # The first several track clicks can hit the same scrollbar thumb.
        task._ocr = Mock(side_effect=lambda *_: [title, button]
                         if task.click_relative.call_count >= 10 else [box('other title')])
        task._select_target(boss)
        self.assertEqual(task.click_relative.call_count, 10)
        task.click_box.assert_called_once_with(button)
        task._wait_for.assert_called_once()

    def test_wheel_can_find_target_without_scrollbar(self):
        task = self.task()
        task._executor.method = SimpleNamespace(height=1440)
        task.scroll_relative = Mock()
        task.click_relative = Mock()
        task.click_box = Mock()
        task._wait_for = Mock()
        boss = WEEKLY_BOSSES[8]
        button = box('直接挑战', 1750, 640)
        task._ocr = Mock(side_effect=[[box('other title')],
                        [box(boss.name, 900, 600, 350), button]])
        task._select_target(boss)
        task.click_box.assert_called_once_with(button)
        task.click_relative.assert_not_called()

    def test_scrollbar_scan_with_progress_but_no_target_is_bounded(self):
        task = self.task()
        task._executor.method = SimpleNamespace(height=1440)
        task.scroll_relative = Mock()
        task.click_relative = Mock()
        task.click_box = Mock()
        task._ocr = Mock(side_effect=lambda *_: [box(f'other {task.click_relative.call_count}')])
        with self.assertRaisesRegex(RuntimeError, '分段搜索.*未找到'):
            task._select_target(WEEKLY_BOSSES[8])
        self.assertEqual(task.click_relative.call_count, 14)
        task.click_box.assert_not_called()

    def test_stop_during_scrollbar_scan_propagates(self):
        from ok import TaskDisabledException
        task = self.task()
        task._executor.method = SimpleNamespace(height=1440)
        task.scroll_relative = Mock()
        task.click_relative = Mock(side_effect=TaskDisabledException())
        task.click_box = Mock()
        task._ocr = Mock(return_value=[box('other title')])
        with self.assertRaises(TaskDisabledException):
            task._select_target(WEEKLY_BOSSES[8])
        task.click_box.assert_not_called()

    def test_navigation_and_registration(self):
        from config import config
        from src.gui.navigation_sections import classify_task
        self.assertIn(['src.task.WeeklyBossTask', 'WeeklyBossTask'], config['onetime_tasks'])
        self.assertEqual(classify_task(self.task()), 'tests')


if __name__ == '__main__':
    unittest.main()
