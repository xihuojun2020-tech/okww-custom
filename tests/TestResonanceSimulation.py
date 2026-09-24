import unittest
import queue
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np
from ok import PostMessageInteraction, TaskDisabledException

from src.task.ResonanceSimulationTask import ResonanceSimulationTask
from src.task.resonance_simulation import liberation_ready, skill_bar_visible


class TestResonanceSimulation(unittest.TestCase):
    def task(self):
        task = ResonanceSimulationTask.__new__(ResonanceSimulationTask)
        task._held_keys = set()
        task._held_mouse = set()
        task._manual_paused = False
        task._toggle_key = '/?'
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

    def test_skill_bar_does_not_require_hp_bar(self):
        frame = cv2.imread('tests/fixtures/resonance_simulation/combat.png')
        frame[681:699, 525:742] = 0
        self.assertTrue(skill_bar_visible(frame))

    def test_menus_and_blank_images_are_not_skill_bars(self):
        for name in ('initial', 'event', 'formation'):
            frame = cv2.imread(f'tests/fixtures/echoes_remain/{name}.png')
            self.assertFalse(skill_bar_visible(frame))
        self.assertFalse(skill_bar_visible(np.zeros((720, 1280, 3), np.uint8)))
        self.assertFalse(skill_bar_visible(np.full((720, 1280, 3), 255, np.uint8)))

    def test_q_only_ready_with_complete_yellow_ring(self):
        root = Path('tests/fixtures/resonance_simulation')
        for name in ('factor', 'currency'):
            self.assertTrue(liberation_ready(cv2.imread(str(root / f'{name}.png'))), name)
        for name in ('combat', 'marker', 'portal', 'reward_far', 'treasure'):
            self.assertFalse(liberation_ready(cv2.imread(str(root / f'{name}.png'))), name)

    def test_short_taps_are_queued_once_per_press(self):
        task = self.task()
        task._toggle_key = '鼠标侧键1'
        task._hotkey_pressed = Mock(side_effect=[False, True, True, False, True])
        task._hotkey_context = Mock(side_effect=[True, True])
        stop = Mock()
        stop.wait.side_effect = [False, False, False, False, True]
        events = queue.SimpleQueue()
        task._watch_hotkey(stop, events)
        self.assertEqual([events.get_nowait(), events.get_nowait()], [True, True])
        self.assertTrue(events.empty())
        task._release = Mock()
        task.log_info = Mock()
        events.put(True)
        task._apply_hotkeys(events)
        self.assertTrue(task._manual_paused)
        events.put(True)
        task._apply_hotkeys(events)
        self.assertFalse(task._manual_paused)
        self.assertEqual(task._release.call_count, 2)

    def test_only_three_toggle_bindings_are_supported(self):
        choices = ResonanceSimulationTask.TOGGLE_KEYS
        self.assertEqual(choices, {'/?': 0xBF, '鼠标侧键1': 0x05, '鼠标侧键2': 0x06})
        for name, code in choices.items():
            task = SimpleNamespace(config={'Skill Interval': 2.0, 'Combat Toggle Key': name},
                                   TOGGLE_KEY='Combat Toggle Key', TOGGLE_KEYS=choices)
            ResonanceSimulationTask._settings(task)
            self.assertEqual(task._toggle_vk, code)
        task.config['Combat Toggle Key'] = 'F9'
        with self.assertRaisesRegex(ValueError, '只支持'):
            ResonanceSimulationTask._settings(task)

    def test_side_button_poll_uses_selected_virtual_key(self):
        task = self.task()
        task._toggle_vk = ResonanceSimulationTask.TOGGLE_KEYS['鼠标侧键2']
        with patch('src.task.ResonanceSimulationTask.ctypes.windll.user32.GetAsyncKeyState',
                   return_value=0x8000) as state:
            self.assertTrue(task._hotkey_pressed())
        state.assert_called_once_with(0x06)

    def test_hotkey_accepts_own_window_and_rejects_other_apps(self):
        task = self.task()
        task._foreground = Mock(return_value=False)
        with patch('src.task.ResonanceSimulationTask.win32gui.GetForegroundWindow', return_value=123), \
                patch('src.task.ResonanceSimulationTask.win32process.GetWindowThreadProcessId',
                      return_value=(1, os.getpid())):
            self.assertTrue(task._hotkey_context())
        with patch('src.task.ResonanceSimulationTask.win32gui.GetForegroundWindow', return_value=123), \
                patch('src.task.ResonanceSimulationTask.win32process.GetWindowThreadProcessId',
                      return_value=(1, os.getpid() + 1)):
            self.assertFalse(task._hotkey_context())

    def test_background_combat_requires_targeted_post_message_input(self):
        task = self.task()
        task._foreground = Mock(return_value=False)
        self.assertFalse(task._input_context_allowed())
        task._executor.interaction = PostMessageInteraction.__new__(PostMessageInteraction)
        self.assertTrue(task._input_context_allowed())

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
        task = ResonanceSimulationTask(executor=Mock(scene=None), app=None)
        defaults = task.default_config
        self.assertEqual(defaults, {'Skill Interval': 2.0, 'Combat Toggle Key': '/?'})
        self.assertEqual(task.config_type['Combat Toggle Key']['options'],
                         ['/?', '鼠标侧键1', '鼠标侧键2'])

    def test_registered_without_normal_combat_dependency(self):
        from config import config
        from src.gui.activity_catalog import PLACEHOLDERS
        from src.task.BaseCombatTask import BaseCombatTask
        self.assertIn(['src.task.ResonanceSimulationTask', 'ResonanceSimulationTask'], config['onetime_tasks'])
        self.assertFalse(any(project == 'resonance_simulation' for project, _ in PLACEHOLDERS))
        self.assertFalse(issubclass(ResonanceSimulationTask, BaseCombatTask))


if __name__ == '__main__':
    unittest.main()
