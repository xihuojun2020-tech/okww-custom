import inspect
import unittest
from pathlib import Path


class TestCodexLightUI(unittest.TestCase):
    def test_program_preferences_do_not_override_collapsed_default(self):
        from ok.gui.settings.SettingTab import SettingTab
        self.assertNotIn('setExpand(True)', inspect.getsource(SettingTab.add_global_config))

    def test_theme_tokens_are_fixed_light(self):
        from src.gui.CodexTheme import COLORS, codex_style_sheet

        self.assertEqual(COLORS["window"], "#FAFAFA")
        self.assertEqual(COLORS["panel"], "#FFFFFF")
        self.assertEqual(COLORS["border"], "#E5E7EB")
        self.assertEqual(COLORS["accent"], "#0969DA")
        self.assertNotIn("dark", codex_style_sheet().lower())

    def test_hubs_do_not_create_nested_tab_widgets(self):
        from src.gui.AccountSettingsTab import AccountSettingsTab
        from src.gui.ActivityHubTab import ActivityHubTab

        self.assertNotIn("QTabWidget", inspect.getsource(AccountSettingsTab))
        self.assertNotIn("QTabWidget", inspect.getsource(ActivityHubTab))

    def test_six_page_order_and_flat_section_markers(self):
        from src.gui.navigation_sections import build_navigation_manifest
        from src.gui.GeneralSettingsTab import GeneralSettingsTab

        self.assertEqual(
            [item["title"] for item in build_navigation_manifest()],
            ["任务", "账号", "完成检查", "自动辅助", "工具", "设置"],
        )
        self.assertIn("self.section_panels", inspect.getsource(GeneralSettingsTab))

    def test_release_version_is_synchronized(self):
        from config import version

        from scripts.validate_release import validate_release
        self.assertEqual(version, validate_release(Path.cwd()))
        self.assertIn(version, Path("更新日志.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
