import unittest
import inspect

from src.gui.navigation_sections import TASKS, TOOLS, classify_task, task_category
from src.task.PianoTeachingTask import PianoTeachingTask
from src.task.SecondSolTask import SecondSolTask
from src.task.EventTask import EventTask
from src.task.TestAccountSwitchTask import TestAccountSwitchTask
from src.task.AutoAbyssTask import AutoAbyssTask
from src.task.BaseCombatTask import BaseCombatTask


class TestTaskNavigationClassification(unittest.TestCase):
    def test_echoes_remain_uses_executable_activity_card(self):
        from src.task.EchoesRemainTask import EchoesRemainTask
        from src.gui.activity_catalog import PLACEHOLDERS, PLACEHOLDER_REVISION, activity_revision
        from src.activity_catalog import ACTIVITIES
        task = object.__new__(EchoesRemainTask)
        self.assertEqual(classify_task(task), TASKS)
        self.assertEqual(task_category(task), '活动')
        self.assertFalse(any(key == 'echoes_remain' or title == ACTIVITIES['echoes_remain']
                             for key, title in PLACEHOLDERS))
        self.assertGreater(activity_revision(task), PLACEHOLDER_REVISION)

    def test_event_is_permanent_and_switch_test_has_clear_owner(self):
        self.assertEqual(EventTask.activity_category, "常驻活动")
        self.assertEqual(classify_task(object.__new__(EventTask)), TASKS)
        self.assertEqual(classify_task(object.__new__(TestAccountSwitchTask)), TOOLS)
        self.assertEqual(classify_task(object.__new__(AutoAbyssTask)), TASKS)
        self.assertEqual(task_category(object.__new__(AutoAbyssTask)), '每周任务')
        for cls in (PianoTeachingTask, SecondSolTask):
            self.assertEqual(classify_task(object.__new__(cls)), TASKS)
            self.assertEqual(task_category(object.__new__(cls)), '活动')
        self.assertIn("多账号每日任务", inspect.getsource(TestAccountSwitchTask.__init__))
        self.assertIn('self.visible = False', inspect.getsource(TestAccountSwitchTask.__init__))
        self.assertTrue(issubclass(AutoAbyssTask, BaseCombatTask))
        self.assertIn("逐塔重新识别角色体力", inspect.getsource(AutoAbyssTask.__init__))
        self.assertIn("combat_once", inspect.getsource(AutoAbyssTask._run_floor_combat))
        abyss = object.__new__(AutoAbyssTask)
        abyss.close_revive_popup = lambda: True
        self.assertFalse(abyss.revive_action())


if __name__ == "__main__":
    unittest.main()
