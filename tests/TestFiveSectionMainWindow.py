import inspect
import unittest
from unittest.mock import Mock

from custom_ok.ok.gui.MainWindow import MainWindow
from src.gui.GeneralSettingsTab import GeneralSettingsTab
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


if __name__ == "__main__":
    unittest.main()
