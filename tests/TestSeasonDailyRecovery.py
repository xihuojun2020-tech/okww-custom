import unittest
from types import SimpleNamespace as Box
from unittest.mock import Mock

from ok import TaskDisabledException, WaitFailedException
from src.task.BaseWWTask import BaseWWTask
from src.task.DailyTask import DailyTask, DailyResourceInsufficient
from src.task.MultiAccountDailyTask import MultiAccountDailyTask
from src.task.NightmareNestTask import NightmareNestTask, NestTarget
from src.task.daily_reserve_policy import DailyReservePolicy, conversion_amount


def quantity_boxes(amount='39'):
    return [Box(name='备用结晶波片'),
            Box(name='转化数量', x=100, y=200, width=100, height=20),
            Box(name=amount, x=230, y=201, width=30, height=20)]


class TestSeasonDailyRecovery(unittest.TestCase):
    def test_split_quantity_and_ambiguous_or_distant_numbers(self):
        boxes = quantity_boxes()
        self.assertEqual(39, conversion_amount(boxes))
        self.assertIsNone(conversion_amount(boxes + [Box(name='40', x=280, y=200, width=30, height=20)]))
        boxes[-1].y = 400
        self.assertIsNone(conversion_amount(boxes))
        self.assertIsNone(conversion_amount(quantity_boxes() + [Box(name='星声')]))

    def test_quantity_edit_requires_readback_and_releases_ctrl(self):
        task = Mock(spec=BaseWWTask)
        task.ocr.side_effect = [quantity_boxes(), quantity_boxes('38')]
        self.assertEqual(38, BaseWWTask._reserve_conversion_amount(task, 38))
        self.assertEqual(['a', '3', '8'], [c.args[0] for c in task.send_key.call_args_list])
        task.send_key_up.assert_called_once_with('ctrl')
        task = Mock(spec=BaseWWTask)
        task.ocr.return_value = quantity_boxes()
        task.send_key.side_effect = TaskDisabledException()
        with self.assertRaises(TaskDisabledException):
            BaseWWTask._reserve_conversion_amount(task, 38)
        task.send_key_up.assert_called_once_with('ctrl')

    def test_failed_quantity_edit_returns_observed_not_requested_amount(self):
        task = Mock(spec=BaseWWTask)
        task.ocr.return_value = quantity_boxes()
        self.assertEqual(39, BaseWWTask._reserve_conversion_amount(task, 38))

    def test_mail_page_excludes_monthly_template_on_same_frame(self):
        task = Mock(spec=BaseWWTask)
        frame = object()
        task.require_game_frame.return_value = frame
        candidate = object()
        task.find_one.return_value = candidate
        task.ocr.return_value = [Box(name='邮件')]
        self.assertIsNone(BaseWWTask.find_monthly_card(task))
        self.assertIs(frame, task.find_one.call_args.kwargs['frame'])
        self.assertIs(frame, task.ocr.call_args.kwargs['frame'])
        task.ocr.return_value = []
        self.assertIs(candidate, BaseWWTask.find_monthly_card(task))

    def test_monthly_closed_after_first_click_does_not_click_world(self):
        task = Mock(spec=BaseWWTask)
        task.find_monthly_card.side_effect = [object(), None, None]
        task.wait_until.side_effect = lambda fn, **kw: (kw['post_action'](), True)[1]
        self.assertTrue(BaseWWTask.handle_monthly_card(task))
        task.click_relative.assert_called_once_with(.50, .89)
        task.set_check_monthly_card.assert_called_once_with(next_day=True)

    def test_monthly_timeout_does_not_record_claim_time(self):
        task = Mock(spec=BaseWWTask)
        task.find_monthly_card.return_value = object()
        task.wait_until.return_value = False
        self.assertFalse(BaseWWTask.handle_monthly_card(task))
        task.set_check_monthly_card.assert_not_called()

    def test_mail_claim_only_after_page_verification(self):
        task = Mock(spec=DailyTask)
        task.require_game_frame.return_value = object()
        button = Box(name='全部领取')
        def ocr(*args, **kwargs):
            if args[1] == .8:
                return [button]
            return [Box(name='邮件')] if task.send_key.call_count == 0 else []
        task.ocr.side_effect = ocr
        DailyTask.claim_mail(task)
        task.click.assert_called_once_with(button, after_sleep=.5)
        self.assertEqual(2, task.ensure_main.call_count)
        task = Mock(spec=DailyTask)
        task.ocr.return_value = []
        task.wait_until.side_effect = WaitFailedException()
        with self.assertRaises(WaitFailedException):
            DailyTask.claim_mail(task)
        self.assertEqual(1, task.click.call_count)  # menu mailbox only

    def nest_task(self, rows):
        task = Mock(spec=NightmareNestTask)
        task.require_game_frame.return_value = object()
        task._residual_rows.side_effect = rows
        task._nest_completed = set()
        return task

    def test_nest_retry_uses_fresh_button_and_stops_when_entered(self):
        first, second, feature = Box(x=10, y=10), Box(x=12, y=12), Box(name='team_entry')
        nest = NestTarget(object(), 'residual:地点', '地点')
        task = self.nest_task([{'地点': (0, 48, first)}, {'地点': (0, 48, second)}])
        task.wait_book_target_state.side_effect = [WaitFailedException(), feature]
        self.assertIs(feature, NightmareNestTask._enter_nest(task, nest))
        self.assertEqual([first, second], [c.args[0] for c in task.click.call_args_list])

    def test_nest_unknown_page_never_reclicks_and_complete_never_clicks(self):
        nest = NestTarget(object(), 'residual:地点', '地点')
        task = self.nest_task([{'地点': (0, 48, Box(x=10, y=10))}, {}])
        task.wait_book_target_state.side_effect = WaitFailedException()
        with self.assertRaisesRegex(RuntimeError, '源页'):
            NightmareNestTask._enter_nest(task, nest)
        self.assertEqual(1, task.click.call_count)
        task = self.nest_task([{'地点': (48, 48, None)}])
        self.assertIsNone(NightmareNestTask._enter_nest(task, nest))
        task.click.assert_not_called()
        self.assertIn('地点', task._nest_completed)

    def test_nest_failure_is_bounded_and_stop_propagates(self):
        nest = NestTarget(object(), 'residual:地点', '地点')
        task = self.nest_task([{'地点': (0, 48, Box(x=10, y=10))}] * 3)
        task.wait_book_target_state.side_effect = WaitFailedException()
        with self.assertRaises(WaitFailedException):
            NightmareNestTask._enter_nest(task, nest)
        self.assertEqual(3, task.click.call_count)
        task = self.nest_task([{'地点': (0, 48, Box(x=10, y=10))}])
        task.wait_book_target_state.side_effect = TaskDisabledException()
        with self.assertRaises(TaskDisabledException):
            NightmareNestTask._enter_nest(task, nest)
        self.assertEqual(1, task.click.call_count)

    def test_resource_shortfall_remains_incomplete_and_not_retryable(self):
        policy = DailyReservePolicy('A4')
        task = Mock(spec=BaseWWTask)
        task.executor = Box(_daily_reserve_policy=policy)
        BaseWWTask._note_daily_resource_shortfall(task, 41, 60)
        self.assertEqual((41, 60), policy.resource_shortfall)
        task = Mock(spec=DailyTask)
        task.executor = Box(_daily_reserve_policy=policy)
        task.claim_daily.return_value = False
        with self.assertRaises(DailyResourceInsufficient) as caught:
            DailyTask._finish_daily_rewards(task, False)
        multi = Mock(spec=MultiAccountDailyTask)
        multi.failed_accounts = {}
        multi._failure_key.return_value = 'A4'
        multi.info = {}
        MultiAccountDailyTask._mark_failed(multi, 'A4', caught.exception)
        self.assertFalse(multi.failed_accounts['A4']['retryable'])
        self.assertNotEqual('resolved', multi.failed_accounts['A4']['status'])


if __name__ == '__main__':
    unittest.main()
