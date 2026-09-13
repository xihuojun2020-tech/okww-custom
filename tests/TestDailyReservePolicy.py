import unittest
from src.task.daily_reserve_policy import DailyReservePolicy,conversion_matches,conversion_amount

class TestDailyReservePolicy(unittest.TestCase):
    def test_full_latches_even_if_later_low_read(self):
        p=DailyReservePolicy('A',remaining=180);p.observe(True,now=1);p.observe(False,now=2)
        self.assertEqual(0,p.allowance(0,60,now=3))
    def test_unknown_and_old_read_block(self):
        p=DailyReservePolicy('A',remaining=180)
        p.observe(None,now=1);self.assertEqual(0,p.allowance(0,60,now=2))
        p.observe(False,now=1);self.assertEqual(0,p.allowance(0,60,now=32))
    def test_budget_and_deficit_bound(self):
        p=DailyReservePolicy('A',remaining=60);p.observe(False,now=1)
        self.assertEqual(40,p.allowance(20,120,now=2))
        p.spend(60);self.assertEqual(0,p.allowance(0,60,now=3))
    def test_total_conservation_alone_is_not_enough(self):
        self.assertFalse(conversion_matches((20,100,120),(120,0,120),40))
        self.assertTrue(conversion_matches((20,100,120),(60,60,120),40))

    def test_pending_transaction_and_wrong_currency_block(self):
        from types import SimpleNamespace
        p=DailyReservePolicy('A',remaining=180,pending_conversion=True)
        p.observe(False,now=1)
        self.assertEqual(0,p.allowance(0,60,now=2))
        for names, amount in [(['转化数量：40'],None),
                              (['备用结晶波片','转化数量：40','星声'],None),
                              (['备用结晶波片','转化数量：40'],40)]:
            self.assertEqual(amount,conversion_amount([SimpleNamespace(name=n) for n in names]))

    def test_production_claim_does_not_click_when_full_unknown_or_stale(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from src.task.BaseWWTask import BaseWWTask
        for ready, age in [(True,0),(None,0),(False,60)]:
            p=DailyReservePolicy('A');p.observe(ready);p.observed_at-=age
            task=Mock(spec=BaseWWTask)
            task.executor=SimpleNamespace(_daily_reserve_policy=p)
            task.has_claim_stamina.return_value=True
            task.get_stamina.return_value=(20,500,520)
            self.assertEqual((False,0),BaseWWTask.use_stamina(task,60,180,True))
            task.click_dialog_left_button.assert_not_called()
            task.click_dialog_right_button.assert_not_called()

    def test_exhausted_budget_is_not_reset_on_planner_reentry(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from src.task.BaseWWTask import BaseWWTask
        p=DailyReservePolicy('A',remaining=0,consumed=180,budget_initialized=True);p.observe(False)
        task=Mock(spec=BaseWWTask);task.executor=SimpleNamespace(_daily_reserve_policy=p)
        task.has_claim_stamina.return_value=True;task.get_stamina.return_value=(0,500,500)
        self.assertEqual((False,0),BaseWWTask.use_stamina(task,60,180,True))
        self.assertEqual(0,p.remaining)

    def test_uncertain_conversion_blocks_even_current_stamina(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from src.task.BaseWWTask import BaseWWTask
        p=DailyReservePolicy('A',pending_conversion=True)
        task=Mock(spec=BaseWWTask);task.executor=SimpleNamespace(_daily_reserve_policy=p)
        task.has_claim_stamina.return_value=True;task.get_stamina.return_value=(240,0,240)
        with self.assertRaisesRegex(RuntimeError,'尚未确认'):
            BaseWWTask.use_stamina(task,60,180,True)
        task.click_dialog_right_button.assert_not_called()

    def test_exit_refresh_is_once_and_preserves_full_latch(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from src.task.BaseWWTask import BaseWWTask
        p=DailyReservePolicy('A',refresh_required=True)
        p.refresh=Mock(side_effect=lambda:p.observe(True))
        task=Mock(spec=BaseWWTask);task.executor=SimpleNamespace(_daily_reserve_policy=p)
        BaseWWTask.refresh_daily_reserve_after_exit(task)
        BaseWWTask.refresh_daily_reserve_after_exit(task)
        p.refresh.assert_called_once();self.assertTrue(p.full_seen)

if __name__=='__main__':unittest.main()
