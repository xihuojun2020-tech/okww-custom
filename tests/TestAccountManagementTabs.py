import unittest

import inspect
from custom_ok.ok.gui.MainWindow import MainWindow
from src.gui.AccountSettingsTab import AccountSettingsTab
from src.gui.AccountConfigTab import AccountConfigTab, ClickOnlyComboBox
from src.gui.SequenceManagementTab import SequenceManagementTab
from src.gui.AccountChangeEvent import AccountChangeEvent


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

    def test_account_page_exposes_sequence_membership(self):
        source = inspect.getsource(AccountConfigTab)
        self.assertIn("所属序列", source)
        self.assertIn("sequence_ids", source)

    def test_primary_farm_dropdown_ignores_mouse_wheel(self):
        class Event:
            ignored = False

            def ignore(self):
                self.ignored = True

        event = Event()
        ClickOnlyComboBox.wheelEvent(None, event)
        self.assertTrue(event.ignored)

    def test_account_pages_enter_safe_state_when_master_is_missing(self):
        account_source = inspect.getsource(AccountConfigTab.refresh)
        sequence_source = inspect.getsource(SequenceManagementTab.refresh)
        self.assertIn("AccountRepositoryError", account_source)
        self.assertIn("账号仓库暂不可用", account_source)
        self.assertIn("AccountRepositoryError", sequence_source)
        self.assertIn("序列仓库暂不可用", sequence_source)

    def test_account_change_event_carries_stable_ids(self):
        event = AccountChangeEvent("profile_saved", "rev-2", ("profile-a1",), ("序列2",))
        self.assertEqual(event.profile_ids, ("profile-a1",))
        self.assertEqual(event.sequence_ids, ("序列2",))

    def test_account_settings_wires_child_changes_and_refreshes_siblings(self):
        source = inspect.getsource(AccountSettingsTab)
        self.assertIn("account_tab.changed.connect", source)
        self.assertIn("sequence_tab.changed.connect", source)
        self.assertIn("refresh_sequences", source)
        self.assertIn("account_changed.emit", source)

    def test_embedded_pages_use_full_available_width(self):
        section_source = inspect.getsource(__import__(
            "src.gui.SectionPanel", fromlist=["SectionPanel"]).SectionPanel)
        account_source = inspect.getsource(AccountSettingsTab)
        self.assertIn("setHorizontalPolicy(QSizePolicy.Policy.Expanding)", section_source)
        self.assertIn("takeWidget", account_source)
        self.assertIn("content_policy.setHorizontalPolicy", account_source)


if __name__ == "__main__":
    unittest.main()
