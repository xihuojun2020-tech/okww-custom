import unittest
import inspect

from src.gui.navigation_sections import ACTIVITIES, TESTS, classify_task
from src.task.EventTask import EventTask
from src.task.TestAccountSwitchTask import TestAccountSwitchTask
from src.task.AutoAbyssTask import AutoAbyssTask
from src.task.BaseCombatTask import BaseCombatTask


class TestTaskNavigationClassification(unittest.TestCase):
    def test_event_is_permanent_and_switch_test_has_clear_owner(self):
        self.assertEqual(EventTask.activity_category, "常驻活动")
        self.assertEqual(classify_task(object.__new__(EventTask)), ACTIVITIES)
        self.assertEqual(classify_task(object.__new__(TestAccountSwitchTask)), TESTS)
        self.assertEqual(classify_task(object.__new__(AutoAbyssTask)), TESTS)
        self.assertIn("多账号每日任务", inspect.getsource(TestAccountSwitchTask.__init__))
        self.assertTrue(issubclass(AutoAbyssTask, BaseCombatTask))
        self.assertIn("逐塔重新识别角色体力", inspect.getsource(AutoAbyssTask.__init__))
        self.assertIn("combat_once", inspect.getsource(AutoAbyssTask._run_floor_combat))
        abyss = object.__new__(AutoAbyssTask)
        abyss.close_revive_popup = lambda: True
        self.assertFalse(abyss.revive_action())


if __name__ == "__main__":
    unittest.main()
