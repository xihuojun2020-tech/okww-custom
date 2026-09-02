import unittest
import inspect

from src.gui.navigation_sections import ACTIVITIES, TESTS, classify_task
from src.task.EventTask import EventTask
from src.task.TestAccountSwitchTask import TestAccountSwitchTask
from src.task.AutoAbyssTask import AutoAbyssTask


class TestTaskNavigationClassification(unittest.TestCase):
    def test_event_is_permanent_and_switch_test_has_clear_owner(self):
        self.assertEqual(EventTask.activity_category, "常驻活动")
        self.assertEqual(classify_task(object.__new__(EventTask)), ACTIVITIES)
        self.assertEqual(classify_task(object.__new__(TestAccountSwitchTask)), TESTS)
        self.assertEqual(classify_task(object.__new__(AutoAbyssTask)), TESTS)
        self.assertIn("多账号每日任务", inspect.getsource(TestAccountSwitchTask.__init__))
        self.assertIn("不会进入战斗", inspect.getsource(AutoAbyssTask.__init__))
        self.assertNotIn("AutoCombatTask", inspect.getsource(AutoAbyssTask))


if __name__ == "__main__":
    unittest.main()
