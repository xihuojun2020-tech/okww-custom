import inspect
import unittest
from unittest.mock import Mock

from custom_ok.ok.gui.MainWindow import MainWindow
from src.gui.GeneralSettingsTab import GeneralSettingsTab
from src.gui.SectionPanel import SectionPanel
from src.gui.TaskHubTab import TaskHubTab
from src.gui.ActivityHubTab import ActivityHubTab
from src.gui.TestHubTab import TestHubTab
from src.gui.navigation_sections import build_navigation_manifest


class TestFiveSectionMainWindow(unittest.TestCase):
    def test_main_window_wires_exactly_five_project_hubs(self):
        source = inspect.getsource(MainWindow.__init__)
        for class_name in ("GeneralSettingsTab", "AccountSettingsTab", "TaskHubTab",
                           "ActivityHubTab", "TestHubTab"):
            self.assertEqual(source.count(f"{class_name}()") + source.count(f"{class_name}(config"), 1)
        self.assertEqual(len(build_navigation_manifest()), 5)
        self.assertNotIn("ScheduleTaskTab", source)
        self.assertIn("程序设置", source)

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
            "activity_hub_tab": object(),
            "test_hub_tab": object(),
        }
        window.__dict__.update(pages)
        window.switchTo = Mock()

        expected = {
            "start": pages["general_settings_tab"],
            "trigger": pages["general_settings_tab"],
            "account": pages["account_settings_tab"],
            "onetime": pages["task_hub_tab"],
            "schedule": pages["task_hub_tab"],
            "activity": pages["activity_hub_tab"],
            "test": pages["test_hub_tab"],
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
        for hub in (TaskHubTab, ActivityHubTab, TestHubTab):
            self.assertIn("add_embedded_widget", inspect.getsource(hub.__init__))


if __name__ == "__main__":
    unittest.main()
