import unittest

from src.task.BaseWWTask import BaseWWTask


class TestStaminaAccounting(unittest.TestCase):

    @staticmethod
    def _stamina_task(current, backup, *, backup_prompt=False):
        class FakeTask:
            project_stamina_after_use = staticmethod(BaseWWTask.project_stamina_after_use)

            def has_claim_stamina(self):
                return True

            def _confirm_stamina_used(self, total, used, before_balance=None):
                return self.project_stamina_after_use(current, backup, used)

            def sleep(self, _seconds):
                pass

            def get_stamina(self):
                return current, backup, current + backup

            def click_dialog_right_button(self):
                self.clicked = 'double'
                return object()

            def click_dialog_left_button(self):
                self.clicked = 'single'
                return object()

            def wait_feature(self, *_args, **_kwargs):
                return backup_prompt

            def click_relative(self, *_args, **_kwargs):
                pass

            def back(self, *_args, **_kwargs):
                pass

            def click(self, *_args, **_kwargs):
                pass

            def log_info(self, *_args, **_kwargs):
                pass

        return FakeTask()

    def test_projected_stamina_uses_backup_without_negative_current(self):
        current, backup, total = BaseWWTask.project_stamina_after_use(0, 106, 60)

        self.assertEqual((0, 46, 46), (current, backup, total))

    def test_claim_confirmation_requires_balance_change_and_closed_dialog(self):
        from unittest.mock import Mock
        for open_dialog, balance, expected in (
                (False, (2, 417, 419), True),
                (False, (3, 417, 420), True),
                (True, (2, 417, 419), False),
                (False, (82, 417, 499), False),
                (False, (-1, -1, -1), False)):
            task = Mock(spec=BaseWWTask)
            task.frame = None
            task.has_claim_stamina.return_value = open_dialog
            task.get_stamina.return_value = balance
            task.wait_until.side_effect = lambda fn, **kw: fn()
            if expected:
                self.assertEqual(BaseWWTask._confirm_stamina_used(task, 499, 80), balance)
            else:
                with self.assertRaises(RuntimeError):
                    BaseWWTask._confirm_stamina_used(task, 499, 80)

    def test_unconfirmed_claim_does_not_return_spending(self):
        from unittest.mock import Mock
        task = self._stamina_task(82, 417)
        task._confirm_stamina_used = Mock(side_effect=RuntimeError('unconfirmed'))
        with self.assertRaises(RuntimeError):
            BaseWWTask.use_stamina(task, once=40, must_use=120, allow_backup=True)

    def test_nas_settlement_balances_and_invalid_observations(self):
        from unittest.mock import Mock
        cases = [(240, 308, 120, 120), (139, 308, 120, 19),
                 (240, 480, 120, 120), (64, 177, 40, 24),
                 (64, 177, 40, 25)]
        for current, backup, used, remaining in cases:
            task = Mock(spec=BaseWWTask)
            task.has_claim_stamina.return_value = False
            task.get_stamina.return_value = (-1, -1, -1)
            task.get_settlement_stamina.return_value = remaining
            task.wait_until.side_effect = lambda fn, **kw: fn()
            self.assertEqual((remaining, backup, remaining + backup),
                             BaseWWTask._confirm_stamina_used(
                                 task, current + backup, used, (current, backup, current + backup)))
        for current, remaining, dialog in [(64, 64, False), (64, -1, False),
                                            (64, 23, False), (64, 24, True), (20, 0, False)]:
            task.has_claim_stamina.return_value = dialog
            task.get_settlement_stamina.return_value = remaining
            task.frame = None
            with self.assertRaises(RuntimeError):
                BaseWWTask._confirm_stamina_used(task, current + 177, 40, (current, 177, current + 177))

    def test_settlement_ocr_requires_button_and_unambiguous_remaining_value(self):
        from unittest.mock import Mock
        from types import SimpleNamespace
        for names, expected in [(['剩余19'], 19), (['剩餘120'], 120),
                                (['Remaining 24'], 24), (['剩余', '24'], 24),
                                (['288秒后自动退出'], -1), (['241'], -1),
                                (['24', '40'], -1), ([], -1)]:
            task = Mock(spec=BaseWWTask)
            task.ocr.side_effect = [[SimpleNamespace(name='重新挑战')],
                                    [SimpleNamespace(name=n) for n in names]]
            self.assertEqual(expected, BaseWWTask.get_settlement_stamina(task))
        task.ocr.side_effect = [[]]
        self.assertEqual(-1, BaseWWTask.get_settlement_stamina(task))

    def test_reserve_conversion_requires_exact_amount_and_balance(self):
        from unittest.mock import Mock
        from types import SimpleNamespace
        for converted, accepted in [((60, 57, 117), True), ((61, 57, 118), True),
                                     ((117, 0, 117), False), ((-1,-1,-1),False)]:
            task = self._stamina_task(20, 97, backup_prompt=True)
            task.get_stamina = Mock(side_effect=[(20, 97, 117), converted])
            task._confirm_stamina_used = Mock(return_value=(0, 57, 57))
            task.next_frame=Mock(); task.screenshot=Mock(); task.click=Mock()
            task.ocr=Mock(side_effect=[[SimpleNamespace(name='备用结晶波片'),SimpleNamespace(name='转化数量：40')],[SimpleNamespace(name='确认')]])
            if accepted:
                BaseWWTask.use_stamina(task,once=60,must_use=60,allow_backup=True)
                task._confirm_stamina_used.assert_called_once_with(117,60,before_balance=converted)
            else:
                with self.assertRaisesRegex(RuntimeError,'余额不符合'):
                    BaseWWTask.use_stamina(task,once=60,must_use=60,allow_backup=True)
                task._confirm_stamina_used.assert_not_called()
            task.click.assert_called_once()

    def test_large_or_unknown_conversion_never_confirms(self):
        from unittest.mock import Mock
        from types import SimpleNamespace
        for names in (['转化数量：97'], ['97'], []):
            task=self._stamina_task(20,97,backup_prompt=True)
            task.next_frame=Mock();task.screenshot=Mock();task.click=Mock()
            task.ocr=Mock(return_value=[SimpleNamespace(name=n) for n in names])
            self.assertEqual((False,0),BaseWWTask.use_stamina(task,once=60,must_use=60,allow_backup=True))
            task.click.assert_not_called()

    def test_backup_policy_is_preserved_at_two_current_stamina(self):
        for allowed in (True, False):
            task = self._stamina_task(82, 417)
            self.assertEqual(BaseWWTask.use_stamina(task, once=40, must_use=120, allow_backup=allowed),
                             (allowed, 80))

    def test_projected_stamina_spends_current_before_backup(self):
        current, backup, total = BaseWWTask.project_stamina_after_use(30, 100, 60)

        self.assertEqual((0, 70, 70), (current, backup, total))

    def test_daily_budget_depends_on_activity_and_stage_cost(self):
        self.assertEqual(0, BaseWWTask.daily_stamina_budget(True, 60))
        self.assertEqual(180, BaseWWTask.daily_stamina_budget(False, 60))
        self.assertEqual(200, BaseWWTask.daily_stamina_budget(False, 40))

    def test_backup_is_only_allowed_when_incomplete_activity_can_reach_budget(self):
        allowed = BaseWWTask.should_use_backup_stamina
        self.assertFalse(allowed(True, 20, 500, 180))
        self.assertFalse(allowed(False, 120, 50, 180))
        self.assertTrue(allowed(False, 120, 60, 180))
        self.assertFalse(allowed(False, 200, 500, 200))

    def test_final_budget_claim_does_not_overshoot_with_double_claim(self):
        task = self._stamina_task(240, 0)

        can_continue, used = BaseWWTask.use_stamina(
            task, once=60, must_use=60, allow_backup=False)

        self.assertEqual('single', task.clicked)
        self.assertEqual(60, used)
        self.assertFalse(can_continue)

    def test_full_activity_zero_budget_keeps_clearing_current_stamina(self):
        task = self._stamina_task(240, 0)

        can_continue, used = BaseWWTask.use_stamina(
            task, once=60, must_use=0, allow_backup=False)

        self.assertEqual('double', task.clicked)
        self.assertEqual(120, used)
        self.assertTrue(can_continue)


if __name__ == '__main__':
    unittest.main()
