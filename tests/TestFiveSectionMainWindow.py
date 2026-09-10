import inspect
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from custom_ok.ok.gui.MainWindow import MainWindow
from src.gui.GeneralSettingsTab import GeneralSettingsTab
from src.gui.SectionPanel import SectionPanel
from src.gui.TaskHubTab import TaskHubTab
from src.gui.AssistantHubTab import AssistantHubTab
from src.gui.ToolsHubTab import ToolsHubTab
from src.gui.navigation_sections import build_navigation_manifest


class TestFiveSectionMainWindow(unittest.TestCase):
    def test_about_removed_and_upgrade_notice_keeps_current_page(self):
        self.assertNotIn('AboutTab', inspect.getsource(MainWindow.__init__))
        window = MainWindow.__new__(MainWindow)
        window.switchTo = Mock()
        window.navigate_tab('about')
        window.switchTo.assert_not_called()
        with patch('custom_ok.ok.gui.MainWindow.get_startup_version_change',
                   return_value=SimpleNamespace(title='1.43.01')), \
                patch('custom_ok.ok.gui.MainWindow.InfoBar.info') as notice:
            window.show_startup_version_change_notice()
            notice.assert_called_once()
        window.switchTo.assert_not_called()

    def test_main_window_wires_exactly_five_project_hubs(self):
        source = inspect.getsource(MainWindow.__init__)
        for class_name in ("GeneralSettingsTab", "AccountSettingsTab", "TaskHubTab",
                           "AssistantHubTab", "ToolsHubTab", "CompletionCheckTab"):
            self.assertEqual(source.count(f"= {class_name}("), 1)
        self.assertEqual(len(build_navigation_manifest()), 6)
        self.assertNotIn("ScheduleTaskTab", source)
        self.assertNotIn("self.setting_tab = SettingTab()", source)
        self.assertIn("item['position'] == 'bottom'", source)

    def test_general_settings_is_one_continuous_page_without_inner_tabs(self):
        source = inspect.getsource(GeneralSettingsTab.__init__)
        self.assertNotIn("QTabWidget", source)
        self.assertIn("self.add_card(title, panel)", source)
        self.assertIn("start_stop_combo", source)
        self.assertIn(
            "程序启停快捷键",
            inspect.getsource(GeneralSettingsTab._update_start_stop_hotkey),
        )

    def test_account_graph_event_refreshes_all_task_consumers(self):
        window = MainWindow.__new__(MainWindow)
        consumers = {}

        class Executor:
            def get_task_by_class(self, task_class):
                return consumers.get(task_class.__name__)

        for name in ("DailyTask", "MultiAccountDailyTask", "TestAccountSwitchTask"):
            consumers[name] = Mock()
        window.executor = Executor()
        from src.gui.AccountChangeEvent import AccountChangeEvent
        window.refresh_account_consumers(AccountChangeEvent('profile_saved', choices_changed=False))
        for consumer in consumers.values():
            self.assertEqual(consumer.mock_calls, [])
        window.refresh_account_consumers()
        consumers["DailyTask"].refresh_account_options.assert_called_once_with()
        consumers["MultiAccountDailyTask"].refresh_account_options.assert_called_once_with()
        consumers["TestAccountSwitchTask"].refresh_profile_options.assert_called_once_with()

    def test_project_routes_only_switch_to_five_top_level_pages(self):
        window = MainWindow.__new__(MainWindow)
        pages = {
            "general_settings_tab": object(),
            "account_settings_tab": object(),
            "task_hub_tab": object(),
            "assistant_hub_tab": object(),
            "tools_hub_tab": object(),
            "completion_check_tab": object(),
        }
        window.__dict__.update(pages)
        window.switchTo = Mock()

        expected = {
            "completion": pages["completion_check_tab"],
            "start": pages["general_settings_tab"],
            "trigger": pages["assistant_hub_tab"],
            "assistant": pages["assistant_hub_tab"],
            "settings": pages["general_settings_tab"],
            "account": pages["account_settings_tab"],
            "onetime": pages["task_hub_tab"],
            "schedule": pages["task_hub_tab"],
            "activity": pages["task_hub_tab"],
            "test": pages["tools_hub_tab"],
            "tools": pages["tools_hub_tab"],
        }
        for route, page in expected.items():
            window.navigate_tab(route)
            window.switchTo.assert_called_with(page)

    def test_resume_switches_to_top_level_task_page(self):
        window = MainWindow.__new__(MainWindow)
        window.task_hub_tab = object()
        window.stackedWidget = Mock()
        window.stackedWidget.currentIndex.return_value = 0
        window.switchTo = Mock()
        window.show_notification = Mock()

        window.executor_paused(False)

        window.switchTo.assert_called_once_with(window.task_hub_tab)

    def test_all_hubs_detach_embedded_scroll_area_contents(self):
        section_source = inspect.getsource(SectionPanel.add_embedded_widget)
        self.assertIn("takeWidget", section_source)
        self.assertIn("self.add_widget(content, stretch)", section_source)
        self.assertIn("add_embedded_widget", inspect.getsource(GeneralSettingsTab.add_card))
        for hub in (TaskHubTab, AssistantHubTab, ToolsHubTab):
            self.assertIn("add_embedded_widget", inspect.getsource(hub.__init__))


if __name__ == "__main__":
    unittest.main()
