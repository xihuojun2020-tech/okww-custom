import unittest
from types import SimpleNamespace

from src.gui.navigation_sections import ACTIVITIES, TASKS, TESTS, build_navigation_manifest, classify_task


class TestNavigationSections(unittest.TestCase):
    def test_manifest_has_exactly_five_scroll_entries(self):
        manifest = build_navigation_manifest()
        self.assertEqual([item["title"] for item in manifest],
                         ["通用设置", "账号设置", "任务", "活动", "测试功能"])
        self.assertEqual({item["route"] for item in manifest},
                         {"general", "accounts", "tasks", "activities", "tests"})

    def test_task_classification_uses_explicit_then_legacy_groups(self):
        self.assertEqual(classify_task(SimpleNamespace(navigation_section=TESTS)), TESTS)
        self.assertEqual(classify_task(SimpleNamespace(group_name="常驻活动")), ACTIVITIES)
        self.assertEqual(classify_task(SimpleNamespace(group_name="")), TASKS)


if __name__ == "__main__":
    unittest.main()
