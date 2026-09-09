import unittest
from types import SimpleNamespace

from src.gui.navigation_sections import ACTIVITIES, TASKS, TESTS, TOOLS, build_navigation_manifest, classify_task


class TestNavigationSections(unittest.TestCase):
    def test_manifest_has_exactly_five_scroll_entries(self):
        manifest = build_navigation_manifest()
        self.assertEqual([item["title"] for item in manifest],
                         ["任务", "账号", "自动辅助", "工具", "设置"])
        self.assertEqual({item["route"] for item in manifest},
                         {"settings", "accounts", "tasks", "assistant", "tools"})
        self.assertEqual([item['position'] for item in manifest], ['scroll'] * 3 + ['bottom'] * 2)

    def test_task_classification_uses_explicit_then_legacy_groups(self):
        self.assertEqual(classify_task(SimpleNamespace(navigation_section=TESTS)), TOOLS)
        self.assertEqual(classify_task(SimpleNamespace(group_name="常驻活动")), TASKS)
        self.assertEqual(classify_task(SimpleNamespace(group_name="")), TASKS)


if __name__ == "__main__":
    unittest.main()
