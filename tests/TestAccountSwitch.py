import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import test_account_switch as account_switch
from config import config
from src.task.TestAccountSwitchTask import (
    CONTINUOUS_MODE,
    DEFAULT_CONTINUOUS_ORDER,
    SINGLE_MODE,
    TestAccountSwitchTask,
)


class TestAccountSwitchCompatibilityEntryPoint(unittest.TestCase):
    """旧脚本只验证兼容转发，不重复测试一套已废弃的切换实现。"""

    def test_compatibility_entry_points_to_formal_task(self):
        self.assertIs(account_switch.get_task_class(), TestAccountSwitchTask)
        self.assertIs(account_switch.TestAccountSwitchTask, TestAccountSwitchTask)

    def test_formal_task_is_registered_in_application_config(self):
        self.assertIn(
            ["src.task.TestAccountSwitchTask", "TestAccountSwitchTask"],
            config["onetime_tasks"],
        )

    def test_legacy_wrapper_delegates_without_own_switch_implementation(self):
        sentinel = object()
        with patch.object(account_switch, "run_task", return_value=sentinel) as run:
            result = account_switch.run_test(
                target="A3",
                rounds=2,
                diag_only=True,
                save_screenshots=False,
            )

        self.assertIs(result, sentinel)
        run.assert_called_once_with()
        for obsolete in ("_do_switch", "_go_back_to_login", "_screen_click"):
            self.assertFalse(hasattr(account_switch, obsolete))

    def test_invalid_round_count_is_rejected_before_delegation(self):
        with patch.object(account_switch, "run_task") as run, redirect_stdout(io.StringIO()):
            self.assertFalse(account_switch.run_test(rounds=0))
        run.assert_not_called()

    def test_formal_task_keeps_continuous_order_contract(self):
        self.assertEqual(DEFAULT_CONTINUOUS_ORDER, "A1,A3,A4")
        self.assertEqual(
            TestAccountSwitchTask._parse_continuous_order("a1， A3 A4"),
            ["A1", "A3", "A4"],
        )
        self.assertEqual(SINGLE_MODE, "单账号切换")
        self.assertEqual(CONTINUOUS_MODE, "连续序列切换")


if __name__ == "__main__":
    unittest.main()
