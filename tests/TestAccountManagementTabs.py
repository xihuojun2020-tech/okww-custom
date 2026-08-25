import unittest

import inspect
from custom_ok.ok.gui.MainWindow import MainWindow
from src.gui.AccountSettingsTab import AccountSettingsTab
from src.gui.AccountConfigTab import AccountConfigTab
from src.gui.SequenceManagementTab import SequenceManagementTab


class TestAccountManagementTabs(unittest.TestCase):
    def test_tabs_are_owned_by_single_account_settings_hub(self):
        source = inspect.getsource(MainWindow.__init__)
        self.assertIn("AccountSettingsTab", source)
        self.assertNotIn("ScheduleTaskTab", source)
        self.assertEqual(AccountSettingsTab.name.fget(None), "账号设置")

    def test_user_facing_names_are_distinct(self):
        self.assertEqual(AccountConfigTab.name.fget(None), "账号配置")
        self.assertEqual(SequenceManagementTab.name.fget(None), "序列管理")


if __name__ == "__main__":
    unittest.main()
