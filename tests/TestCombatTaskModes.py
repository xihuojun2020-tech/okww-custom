import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from src.task.AutoCombatTask import AutoCombatTask
from src.task.SoloCombatTask import SoloCombatTask
from src.runtime.game_runtime_errors import GameProcessLost, FrameUnavailable


def combat_task(cls, count):
    executor = SimpleNamespace(scene=SimpleNamespace(in_team=Mock(return_value=True)),
                               text_fix={}, remove_onetime_task=Mock(), _wake_executor=Mock(),
                               global_config=SimpleNamespace(get_config=lambda _: {}))
    task = cls(executor=executor, app=None)
    task.scene = executor.scene
    task.config = dict(task.default_config)
    task.warm_up_char_features = Mock()
    task.in_team = Mock(return_value=(True, 0, count))
    task.in_world = Mock(return_value=True)
    task.combat_is_active = Mock(side_effect=[True, False])
    task.switch_healer = Mock()
    task.perform_combat_rotation = Mock()
    task.combat_end = Mock()
    return task


class TestCombatTaskModes(unittest.TestCase):
    def test_separate_defaults_and_character_routing(self):
        multi = combat_task(AutoCombatTask, 3)
        solo = combat_task(SoloCombatTask, 1)
        self.assertTrue(multi.default_config['_enabled'])
        self.assertFalse(solo.default_config['_enabled'])
        self.assertFalse(multi.solo_rotation_enabled)
        self.assertTrue(solo.solo_rotation_enabled)
        self.assertTrue(multi.use_original_multi_rotation)

    def test_exact_team_count_routes_to_one_task(self):
        for count in (1, 2, 3):
            for cls in (AutoCombatTask, SoloCombatTask):
                with self.subTest(count=count, task=cls.__name__):
                    task = combat_task(cls, count)
                    allowed = count == 1 if cls is SoloCombatTask else count in (2, 3)
                    self.assertEqual(task._run_combat(), allowed)
                    self.assertEqual(task.perform_combat_rotation.call_count, int(allowed))
                    self.assertIsNone(getattr(task.executor, '_background_combat_mode', None))

    def test_other_mode_cannot_take_over_active_battle(self):
        task = combat_task(SoloCombatTask, 1)
        task.executor._background_combat_mode = 'multi'
        self.assertFalse(task._run_combat())
        task.perform_combat_rotation.assert_not_called()
        self.assertEqual(task.executor._background_combat_mode, 'multi')

    def test_changed_team_releases_mode_only_after_combat(self):
        task = combat_task(AutoCombatTask, 1)
        task.executor._background_combat_mode = 'multi'
        task.in_combat = Mock(return_value=True)
        self.assertFalse(task._run_combat())
        self.assertEqual(task.executor._background_combat_mode, 'multi')
        task.in_combat.return_value = False
        self.assertFalse(task._run_combat())
        self.assertIsNone(task.executor._background_combat_mode)

    def test_manual_stop_releases_only_its_mode(self):
        task = combat_task(AutoCombatTask, 3)
        task.executor._background_combat_mode = 'multi'
        task._release_combat_inputs = Mock()
        task.set_enabled_from_ui(False)
        self.assertIsNone(task.executor._background_combat_mode)
        task.executor._background_combat_mode = 'solo'
        task._release_combat_mode()
        self.assertEqual(task.executor._background_combat_mode, 'solo')

    def test_process_loss_releases_mode_but_temporary_frame_loss_keeps_it(self):
        task = combat_task(AutoCombatTask, 3)
        task._release_combat_inputs = Mock()
        task.record_combat_error = Mock()
        task.do_reset_to_false = Mock()
        task.executor._background_combat_mode = 'multi'
        task.handle_execution_error(FrameUnavailable('temporary'))
        self.assertEqual(task.executor._background_combat_mode, 'multi')
        task.handle_execution_error(GameProcessLost('closed'))
        self.assertIsNone(task.executor._background_combat_mode)


if __name__ == '__main__':
    unittest.main()
