"""Replay the installed 1.97.01 client's tower failure without game input."""
import unittest
from unittest.mock import patch
from pathlib import Path

import cv2
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.Labels import Labels
from src.task.AutoAbyssTask import (
    AutoAbyssTask, AVAILABLE, LOCKED, TOWER_NAMES, selected_floor_index,
    count_occupied_tower_slots,
)
from src.task.abyss_allocation import current_season_rules


class TestAbyssSeasonImages(TaskTestCase):
    config = config
    task_class = AutoAbyssTask
    folder = Path('tests/images/abyss_season_20261004')

    def test_selected_fourth_floor_and_empty_portraits(self):
        for name in ('left_floor4', 'right_floor4'):
            original = cv2.imread(str(self.folder / (name + '.png')))
            for height in (720, 1080, 1152, 1440, 2160):
                frame = cv2.resize(original, (height * 16 // 9, height))
                self.assertEqual(selected_floor_index(frame), 3, (name, height))
                self.assertEqual([count_occupied_tower_slots(frame, i) for i in range(4)], [0] * 4)

    def test_real_four_open_floors_are_not_a_state_conflict(self):
        for tower, name in ((TOWER_NAMES[0], 'left_floor4'), (TOWER_NAMES[2], 'right_floor4')):
            self.set_image(str(self.folder / (name + '.png')))
            task = self.task
            # Each row's actual frame is preserved; row clicks are simulated only.
            with patch.object(task, '_verify_floor_state', return_value=AVAILABLE), \
                    patch.object(task, 'screenshot') as screenshot:
                self.assertEqual(task._scan_tower_floors(tower, 0), (AVAILABLE,) * 4)
                screenshot.assert_not_called()

    def test_real_presets_read_all_six_current_energies_as_ten(self):
        expected = ((Labels.char_qingxiao, Labels.char_denia, Labels.char_verina),
                    ('yangyang_sp', 'rover_aero', Labels.char_sanhua))
        original = cv2.imread(str(self.folder / 'presets.png'))
        self.set_image(str(self.folder / 'presets.png'))
        rows = self.task._preset_page_rows(self.task.frame)
        for number, top in rows[:2]:
            preset = self.task._preset_on_row(original, number, top)
            self.assertIsNotNone(preset, number)
            self.assertEqual(preset.members, expected[number - 1], number)
            self.assertEqual(preset.energies, (10, 10, 10), number)
        for height in (1440,):
            frame = cv2.resize(original, (height * 16 // 9, height))
            for number, top in rows[:2]:
                energies = tuple(self.task._preset_energy(frame, x, top) for x in (.121, .207, .294))
                self.assertEqual(energies, (10, 10, 10), (height, number))
        # Resampled glyphs can remain unreadable; they must never become zero.
        for height in (720, 1152, 2160):
            frame = cv2.resize(original, (height * 16 // 9, height))
            for number, top in rows[:2]:
                for x in (.121, .207, .294):
                    self.assertIn(self.task._preset_energy(frame, x, top), (None, 10), (height, number, x))
        number, top = rows[2]
        self.assertIsNone(self.task._preset_on_row(original, number, top))

    def test_real_preset_scan_feeds_side_tower_allocation_without_missing_member(self):
        self.set_image(str(self.folder / 'presets.png'))
        task = self.task
        frame = task.frame.copy()
        with patch.object(task, 'scroll_relative'), patch.object(task, 'sleep'), \
                patch.object(task, '_wait_stable_preset_frame', return_value=frame):
            records = task._scan_saved_presets()
            self.assertEqual(len(records), 6)
            self.assertEqual([r.energy for r in records], [10] * 6)
            self.assertEqual(tuple(task._saved_presets), (1, 2))
            task._preset_mode = True
            task._abyss_rules = current_season_rules()
            states = {TOWER_NAMES[0]: (AVAILABLE,) * 4, TOWER_NAMES[2]: (AVAILABLE,) * 4,
                      TOWER_NAMES[1]: (AVAILABLE, LOCKED, LOCKED, LOCKED)}
            task._allocation_context = (TOWER_NAMES[0], 0, states, '两侧塔优先')
            plan = task._allocate_remaining(records)
            self.assertIn(plan.preset.queue, (1, 2))
            self.assertIsNotNone(task._scheduled_teams[(TOWER_NAMES[0], 0)])
            self.assertEqual(sum(p is not None for (tower, _), p in task._scheduled_teams.items()
                                 if tower != TOWER_NAMES[1]), 8)


if __name__ == '__main__':
    unittest.main()
