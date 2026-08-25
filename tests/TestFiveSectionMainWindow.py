import inspect
import unittest

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


if __name__ == "__main__":
    unittest.main()
