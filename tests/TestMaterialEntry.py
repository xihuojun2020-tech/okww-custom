import unittest
from unittest.mock import Mock
from tests import TestNavigationAdapter as nav_tests
from src.task.MaterialPlannerTask import MaterialPlannerTask

class TestMaterialEntry(unittest.TestCase):
    def task(self):
        harness=nav_tests.TestNavigationAdapter();self.addCleanup(harness.doCleanups)
        task=harness.task();task.key_config={'Bag Key':'v'};task.send_key=Mock()
        return task
    def test_bag_and_resource_are_separate_verified_steps(self):
        task=self.task()
        task.in_team_and_world=lambda **kwargs:not task.send_key.called
        task._inventory_page=lambda frame:('资源' if task.click_relative.call_count>=2 else '武器') if task.send_key.called else None
        MaterialPlannerTask._open_resource_inventory(task)
        task.send_key.assert_called_once_with('v')
        self.assertEqual(task.click_relative.call_count,2)
        self.assertEqual(task.click_relative.call_args.args,(.04,.55))
    def test_unknown_bag_does_not_click_resource_tab(self):
        task=self.task();task.in_team_and_world=lambda **kwargs:False
        task._inventory_page=lambda frame:None
        with self.assertRaises(RuntimeError):MaterialPlannerTask._open_resource_inventory(task)
        task.send_key.assert_not_called();task.click_relative.assert_not_called()
    def test_already_resource_has_no_inputs(self):
        task=self.task();task.in_team_and_world=lambda **kwargs:False
        task._inventory_page=lambda frame:'资源'
        MaterialPlannerTask._open_resource_inventory(task)
        task.send_key.assert_not_called();task.click_relative.assert_not_called()

if __name__=='__main__':unittest.main()
