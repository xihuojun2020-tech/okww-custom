import unittest

from src.task.BaseWWTask import BaseWWTask


class TestStaminaAccounting(unittest.TestCase):

    @staticmethod
    def _stamina_task(current, backup, *, backup_prompt=False):
        class FakeTask:
            project_stamina_after_use = staticmethod(BaseWWTask.project_stamina_after_use)

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
