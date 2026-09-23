import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from src.task.BaseWWTask import BaseWWTask
from src.task.BaseCombatTask import CombatStateUnknown
from src.task.DomainTask import DomainTask
from src.task.MultiAccountDailyTask import MultiAccountDailyTask
from src.runtime.game_runtime_errors import GameProcessLost


class TestChallengeFailureRecovery(unittest.TestCase):
    def test_failure_screen_exits_only_with_button_and_world_confirmation(self):
        task = Mock(spec=BaseWWTask)
        button = SimpleNamespace(name='退出副本')
        task.ocr.side_effect = [[SimpleNamespace(name='挑战失败')], [button]]
        task.wait_until.return_value = True
        self.assertTrue(BaseWWTask.recover_failed_challenge(task))
        task.click.assert_called_once_with(button, after_sleep=1)

    def test_failure_without_exit_button_never_clicks(self):
        task = Mock(spec=BaseWWTask)
        task.ocr.side_effect = [[SimpleNamespace(name='挑战失败')], []]
        self.assertFalse(BaseWWTask.recover_failed_challenge(task))
        task.click.assert_not_called()

    def test_other_page_does_not_click(self):
        task = Mock(spec=BaseWWTask)
        task.ocr.return_value = []
        self.assertIsNone(BaseWWTask.recover_failed_challenge(task))
        task.click.assert_not_called()

    def test_domain_stops_after_failure_recovery_without_claiming(self):
        task = Mock(spec=DomainTask)
        task.recover_failed_challenge.return_value = True
        with self.assertRaisesRegex(CombatStateUnknown, '保留补跑'):
            DomainTask._finish_domain_combat(task)
        task._domain_reward_state.assert_not_called()

    def test_multi_account_does_not_restart_on_unresolved_failure_page(self):
        task = Mock(spec=MultiAccountDailyTask)
        task._game_window_available.return_value = True
        task.do_find_account_drop_down.return_value = None
        task.recover_failed_challenge.return_value = False
        with self.assertRaises(GameProcessLost):
            MultiAccountDailyTask._prepare_login_after_account_failure(task, 'A1', RuntimeError('combat'))
        task.ensure_main.assert_not_called()
        task._restart_game_once.assert_not_called()


if __name__ == '__main__':
    unittest.main()
