import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
from ok import TaskDisabledException

from src.task.ResonanceSimulationTask import ResonanceSimulationTask
from src.task.resonance_simulation import liberation_ready, skill_bar_visible


class TestResonanceSimulation(unittest.TestCase):
    def task(self):
        task = ResonanceSimulationTask.__new__(ResonanceSimulationTask)
        task._held_keys = set()
        task._held_mouse = set()
        task._manual_paused = False
        task._slash_down = False
        task._executor = SimpleNamespace(interaction=Mock())
        task._input_ready = Mock(return_value=True)
        return task

    def test_all_activity_pages_keep_skill_bar_visible(self):
        root = Path('tests/fixtures/resonance_simulation')
        for path in root.glob('*.png'):
            source = cv2.imread(str(path))
            for height in (720, 1080, 1440):
                with self.subTest(path=path.name, height=height):
                    frame = cv2.resize(source, (height * 16 // 9, height))
                    self.assertTrue(skill_bar_visible(frame))

    def test_menus_and_blank_images_are_not_skill_bars(self):
        for name in ('initial', 'event', 'formation'):
            frame = cv2.imread(f'tests/fixtures/echoes_remain/{name}.png')
            self.assertFalse(skill_bar_visible(frame))
        self.assertFalse(skill_bar_visible(np.zeros((720, 1280, 3), np.uint8)))

    def test_q_only_ready_with_complete_yellow_ring(self):
        root = Path('tests/fixtures/resonance_simulation')
        for name in ('factor', 'currency'):
            self.assertTrue(liberation_ready(cv2.imread(str(root / f'{name}.png'))), name)
        for name in ('combat', 'marker', 'portal', 'reward_far', 'treasure'):
            self.assertFalse(liberation_ready(cv2.imread(str(root / f'{name}.png'))), name)

    def test_slash_question_key_toggles_once_per_press(self):
        task = self.task()
        task._foreground = Mock(return_value=True)
        self.assertTrue(task._toggle_requested(True))
        self.assertTrue(task._manual_paused)
        self.assertFalse(task._toggle_requested(True))
        self.assertFalse(task._toggle_requested(False))
        self.assertTrue(task._toggle_requested(True))
        self.assertFalse(task._manual_paused)

    def test_short_attack_and_skill_are_always_released(self):
        task = self.task()
        task._pulse(attack=True, skill='q')
        task.executor.interaction.send_key_down.assert_called_once_with('q', activate=False)
        task.executor.interaction.send_key_up.assert_called_once_with('q')
        task.executor.interaction.mouse_down.assert_called_once_with(key='left')
        task.executor.interaction.mouse_up.assert_called_once_with(key='left')
        self.assertFalse(task._held_keys)
        self.assertFalse(task._held_mouse)

    def test_stop_during_pulse_releases_input(self):
        task = self.task()
        task._input_ready.side_effect = [True, True, TaskDisabledException()]
        with self.assertRaises(TaskDisabledException):
            task._pulse(attack=True, skill='e')
        task.executor.interaction.send_key_up.assert_called_once_with('e')
        task.executor.interaction.mouse_up.assert_called_once_with(key='left')

    def test_cleanup_attempts_every_input_if_one_release_fails(self):
        task = self.task()
        task._held_keys = {'e', 'q'}
        task._held_mouse = {'left'}
        task.executor.interaction.send_key_up.side_effect = RuntimeError('release')
        with self.assertRaises(RuntimeError):
            task._release()
        self.assertEqual(task.executor.interaction.send_key_up.call_count, 2)
        task.executor.interaction.mouse_up.assert_called_once_with(key='left')

    def test_configuration_only_keeps_combat_interval(self):
        defaults = ResonanceSimulationTask(executor=Mock(scene=None), app=None).default_config
        self.assertEqual(defaults, {'Skill Interval': 2.0})

    def test_registered_without_normal_combat_dependency(self):
        from config import config
        from src.gui.activity_catalog import PLACEHOLDERS
        from src.task.BaseCombatTask import BaseCombatTask
        self.assertIn(['src.task.ResonanceSimulationTask', 'ResonanceSimulationTask'], config['onetime_tasks'])
        self.assertFalse(any(project == 'resonance_simulation' for project, _ in PLACEHOLDERS))
        self.assertFalse(issubclass(ResonanceSimulationTask, BaseCombatTask))


if __name__ == '__main__':
    unittest.main()
