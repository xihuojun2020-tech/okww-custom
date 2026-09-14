import unittest
from unittest.mock import Mock
from tests import TestNavigationAdapter as nav_tests
from src.task.ui_transition import TransitionTimeout

class TestTravelTransitions(unittest.TestCase):
    def task(self):
        harness=nav_tests.TestNavigationAdapter();self.addCleanup(harness.doCleanups)
        task=harness.task();self.button=harness.button
        task.click=Mock();task.find_one=Mock(return_value=None)
        task._travel_identity=Mock(return_value=('destination',))
        task._travel_confirmation=Mock(return_value=None)
        return task
    def test_lost_first_click_retries_only_map_source(self):
        task=self.task()
        task._travel_button=lambda frame:self.button if task.click.call_count<2 else None
        task.in_team_and_world=lambda **kw:task.click.call_count>=2
        self.assertTrue(task._navigate_travel())
        self.assertEqual(task.click.call_count,2)
    def test_unrelated_world_does_not_prove_travel(self):
        task=self.task();task._travel_button=Mock(return_value=None)
        task.in_team_and_world=Mock(return_value=True)
        with self.assertRaises(TransitionTimeout):task._navigate_travel()
        task.click.assert_not_called()
    def test_remove_marker_never_clicked(self):
        task=self.task();task._travel_button=Mock(return_value=None)
        task.find_one=Mock(return_value=self.button)
        with self.assertRaisesRegex(RuntimeError,'移除'):task.click_traval_button()
        task.click.assert_not_called()
    def test_confirm_is_a_separate_step_without_checkbox_toggle(self):
        task=self.task()
        task._travel_button=lambda frame:None if task.click.called else self.button
        task._travel_confirmation=lambda frame:self.button if task.click.called and not task.click_relative.called else None
        task.in_team_and_world=lambda **kw:task.click_relative.called
        self.assertTrue(task._navigate_travel())
        task.click.assert_called_once_with(self.button)
        task.click_relative.assert_called_once()
    def test_missing_frame_after_click_never_replays_travel(self):
        task=self.task()
        task._travel_button=lambda frame:None if task.click.called else self.button
        task.in_team_and_world=Mock(return_value=False)
        with self.assertRaises(TransitionTimeout):task._navigate_travel()
        task.click.assert_called_once()

if __name__=='__main__':unittest.main()
