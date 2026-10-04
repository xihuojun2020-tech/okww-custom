"""Exercise the material entry through the shared production weekly navigator."""
import unittest
from unittest.mock import Mock

from ok import TaskDisabledException
from src.task.WorldBossMaterialTask import WorldBossMaterialTask
from src.task.WeeklyBossTask import WeeklyBossTask, WeeklyPageTimeout
from src.task.world_boss_materials import TARGETS_BY_ID, matches_target
from src.task.ui_transition import TransitionTimeout
from tests import TestNavigationAdapter as navigation_tests
from tests.TestWorldBossMaterialTask import box


class TestWorldBossMaterialNavigation(unittest.TestCase):
    def task(self):
        harness = navigation_tests.TestNavigationAdapter()
        self.addCleanup(harness.doCleanups)
        base = harness.task()
        task = object.__new__(WorldBossMaterialTask)
        task.__dict__.update(base.__dict__)
        task.executor.current_task = task
        task._material_target = TARGETS_BY_ID['world_crownless']
        task._stage = Mock()
        task.scroll_relative = Mock()
        task.ensure_main = Mock()
        task.openF2Book = Mock()
        task.open_boss_book = Mock()
        task.wait_click_travel = Mock()
        task.wait_in_team_and_world = Mock()
        task.click = lambda button: task.click_relative(.7, .9)
        self.title = box(task._material_target.name, 800, 600, 300)
        self.button = box('直接挑战', 1700, 640)
        self.button.center = lambda: (1344, 972)
        return task

    def direct(self, task, *, story=False, wrong=False):
        task._ocr = Mock(side_effect=lambda *args: [self.title, self.button]
                         if not task.click_relative.called else [])
        def text(region, frame):
            if region == (.25, .43, .75, .53):
                return ('提前到达目标位置可能影响剧情体验，是否确认前往？'
                        if story and task.click_relative.call_count == 1 else '')
            return '云闪之鳞' if wrong and task.click_relative.called else task._material_target.name
        task._text = text
        detail = 2 if story else 1
        task._button = lambda region, text, frame: self.button if (
            region == (.55, .59, .76, .67) and story and task.click_relative.call_count == 1 or
            region == task.SINGLE and task.click_relative.call_count == detail or
            region == task.START and task.click_relative.call_count == detail + 1) else None
        task.in_team_and_world = lambda **kwargs: task.click_relative.call_count >= detail + 2

    def test_full_material_entry_uses_qiangdi_then_detail_single_start_world(self):
        task = self.task()
        self.direct(task)
        self.assertTrue(task.teleport_to_configured_boss())
        task.openF2Book.assert_called_once_with('gray_book_boss')
        task.open_boss_book.assert_called_once_with('qiangdi')
        self.assertEqual(3, task.click_relative.call_count)
        task.wait_click_travel.assert_not_called()
        task.scroll_relative.assert_called_once_with(.92, .5, 30)

    def test_story_confirmation_is_shared_and_original_boss_checked(self):
        task = self.task()
        self.direct(task, story=True)
        self.assertTrue(task.teleport_to_configured_boss())
        self.assertEqual(4, task.click_relative.call_count)

    def formation(self, task, *, quick=True, entry=True):
        task._ocr = Mock(side_effect=lambda *args: [self.title, self.button]
                         if entry and not task.click_relative.called else [])
        task._text = lambda region, frame: '' if region == (.25, .43, .75, .53) else '队伍1'
        task._button = lambda region, text, frame: self.button if (
            (task.click_relative.call_count == 1 or not entry) and (
                region == task.START and text == '开启挑战' or
                quick and region == (.62, .864, .76, .95) and text == '快速编队')) else None
        task.in_team_and_world = lambda **kwargs: task.click_relative.call_count >= 2

    def test_direct_formation_skips_absent_detail_and_single_then_starts_once(self):
        task = self.task()
        self.formation(task)
        self.assertTrue(task.teleport_to_configured_boss())
        self.assertEqual(2, task.click_relative.call_count)
        task.wait_click_travel.assert_not_called()

    def test_start_label_without_quick_formation_does_not_prove_destination(self):
        task = self.task()
        self.formation(task, quick=False)
        with self.assertRaises(TransitionTimeout):
            task.teleport_to_configured_boss()
        self.assertEqual(1, task.click_relative.call_count)

    def test_unsubmitted_formation_cannot_bypass_named_target_selection(self):
        task = self.task()
        self.formation(task, entry=False)
        with self.assertRaises(TransitionTimeout):
            task._open_material_target(task._material_target, self.button)
        task.click_relative.assert_not_called()

    def test_wrong_boss_detail_stops_before_single_or_start(self):
        task = self.task()
        self.direct(task, wrong=True)
        with self.assertRaisesRegex(RuntimeError, '不一致'):
            task.teleport_to_configured_boss()
        self.assertEqual(1, task.click_relative.call_count)

    def test_stalled_wheel_finds_material_through_shared_scrollbar(self):
        task = self.task()
        task._ocr = Mock(side_effect=lambda *args: [self.title, self.button]
                         if task.click_relative.call_count >= 10 else [box('其他首领')])
        task._open_material_target = Mock(return_value=True)
        self.assertTrue(task.select_configured_boss(None, None))
        self.assertEqual(10, task.click_relative.call_count)
        task._open_material_target.assert_called_once_with(task._material_target, self.button)

    def test_missing_target_search_is_bounded_and_stop_propagates(self):
        task = self.task()
        task._ocr = Mock(return_value=[box('其他首领')])
        task._open_material_target = Mock()
        with self.assertRaises(WeeklyPageTimeout):
            task.select_configured_boss(None, None)
        self.assertEqual(14, task.click_relative.call_count)
        task._open_material_target.assert_not_called()
        task.click_relative.side_effect = TaskDisabledException('manual stop')
        with self.assertRaises(TaskDisabledException):
            task.select_configured_boss(None, None)

    def test_loading_never_repeats_start_submission(self):
        task = self.task()
        task._text = lambda *args: task._material_target.name
        task._button = lambda region, text, frame: self.button if (
            region == task.SINGLE and not task.click_relative.called or
            region == task.START and task.click_relative.called) else None
        task.in_team_and_world = Mock(return_value=False)
        with self.assertRaises(TransitionTimeout):
            WeeklyBossTask._enter_challenge(task, task._material_target,
                title_match=lambda text: matches_target(text, task._material_target), label='首领材料')
        self.assertEqual(2, task.click_relative.call_count)

    def test_travel_entry_retains_existing_map_travel_and_world_wait(self):
        task = self.task()
        self.button.name = '前往'
        task._ocr = Mock(side_effect=lambda *args: [self.title, self.button]
                         if not task.click_relative.called else [])
        task._travel_button = Mock(side_effect=lambda frame: self.button if task.click_relative.called else None)
        self.assertFalse(task.teleport_to_configured_boss())
        self.assertEqual(1, task.click_relative.call_count)
        task.wait_click_travel.assert_called_once()
        task.wait_in_team_and_world.assert_called_once_with(time_out=120)


if __name__ == '__main__':
    unittest.main()
