import unittest

import inspect
from custom_ok.ok.gui.MainWindow import MainWindow
from src.gui.AccountSettingsTab import AccountSettingsTab
from src.gui.AccountConfigTab import AccountConfigTab, ClickOnlyComboBox
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

    def test_delete_labels_identify_the_object_being_changed(self):
        account_source = inspect.getsource(AccountConfigTab.__init__)
        sequence_source = inspect.getsource(SequenceManagementTab.__init__)
        self.assertIn("删除当前账号", account_source)
        self.assertIn("删除当前序列", sequence_source)
        self.assertIn("当前序列包含的账号", sequence_source)
        self.assertIn("上移账号", sequence_source)
        self.assertIn("下移账号", sequence_source)

    def test_primary_farm_dropdown_ignores_mouse_wheel(self):
        class Event:
            ignored = False

            def ignore(self):
                self.ignored = True

        event = Event()
        ClickOnlyComboBox.wheelEvent(None, event)
        self.assertTrue(event.ignored)


if __name__ == "__main__":
    unittest.main()
