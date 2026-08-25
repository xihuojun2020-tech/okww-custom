import unittest

from config import config
from src.gui.AccountConfigTab import AccountConfigTab
from src.gui.SequenceManagementTab import SequenceManagementTab


class TestAccountManagementTabs(unittest.TestCase):
    def test_tabs_are_registered_after_default_tabs(self):
        self.assertIn(["src.gui.AccountConfigTab", "AccountConfigTab"], config["custom_tabs"])
        self.assertIn(["src.gui.SequenceManagementTab", "SequenceManagementTab"], config["custom_tabs"])
        self.assertTrue(AccountConfigTab.add_after_default_tabs.fget(None))
        self.assertTrue(SequenceManagementTab.add_after_default_tabs.fget(None))

    def test_user_facing_names_are_distinct(self):
        self.assertEqual(AccountConfigTab.name.fget(None), "账号配置")
        self.assertEqual(SequenceManagementTab.name.fget(None), "序列管理")


if __name__ == "__main__":
    unittest.main()
