import unittest
from types import SimpleNamespace
from unittest.mock import patch
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.WorldBossMaterialTask import WorldBossMaterialTask
from src.task.world_boss_materials import TARGETS_BY_ID, matches_health_title_boxes


class TestMaterialCombatImages(TaskTestCase):
    config = config
    task_class = WorldBossMaterialTask

    def load(self, name):
        self.set_image('tests/images/material_boss_entry/' + name + '.png')

    def test_actual_title_including_fragmented_level_is_verified(self):
        target = TARGETS_BY_ID['world_lady_of_the_sea']
        for name in ('combat_alive', 'combat_healer_dead', 'combat_two_dead'):
            self.load(name)
            boxes = self.task.ocr(.15, .0, .85, .10)
            self.assertTrue(matches_health_title_boxes(boxes, target, self.task.height))
            self.assertFalse(matches_health_title_boxes(boxes, TARGETS_BY_ID['world_crownless'], self.task.height))
            self.task._material_target = target
            self.task._material_name_verified = False
            self.task._verify_material_boss_title()
            self.assertTrue(self.task._material_name_verified)

    def test_actual_no_revival_banner_only_blocks_gray_dead_teammates(self):
        cases = [('combat_alive', [False, False, False]),
                 ('combat_healer_dead', [False, False, True]),
                 ('combat_two_dead', [False, True, True])]
        for name, expected in cases:
            self.load(name)
            for index, dead in enumerate(expected):
                char = SimpleNamespace(index=index, has_intro=False, has_sub_dps_intro=False)
                self.assertEqual(dead, self.task._switch_rejected_by_death(char), (name, index))
                self.assertEqual(dead, char.__dict__.get('_switch_unrevivable', False))

    def test_colored_revived_portrait_restores_switch_eligibility(self):
        char = SimpleNamespace(index=2, has_intro=False, has_sub_dps_intro=False)
        self.load('combat_healer_dead')
        self.assertTrue(self.task._switch_rejected_by_death(char))
        self.assertTrue(self.task._unrevivable_switch_target(char))
        self.load('combat_alive')
        self.assertFalse(self.task._unrevivable_switch_target(char))
        self.assertFalse(char._switch_unrevivable)

    def test_actual_absorb_and_reward_rows_are_distinguished_for_materials(self):
        self.task._in_realm = False
        self.task._material_phase = 'combat'
        for name in ('nas_b7_absorb', 'nas_b8_absorb'):
            self.set_image('tests/images/weekly_boss/' + name + '.png')
            self.assertTrue(self.task._selected_reward_interaction('吸收'))
            self.assertFalse(self.task._reward_available())
            self.assertTrue(self.task._material_combat_finished())
        self.set_image('tests/images/weekly_boss/claim.png')
        self.task._material_phase = 'echo'
        self.assertTrue(self.task._reward_available())
        with patch.object(self.task, 'send_key') as send, patch.object(self.task, 'find_f_with_text', return_value=None):
            self.assertFalse(self.task.pick_f())
        send.assert_not_called()

    def test_actual_absorption_disappears_after_f_without_opening_reward(self):
        self.task._material_phase = 'echo'
        self.set_image('tests/images/weekly_boss/nas_b7_absorb.png')
        with patch.object(self.task, '_release_movement'), patch.object(self.task, 'send_key') as send:
            send.side_effect = lambda *args, **kw: self.set_image('tests/images/weekly_boss/nas_b10_no_interaction.png')
            self.assertTrue(self.task.pick_echo())
        send.assert_called_once_with('f', after_sleep=.6)

    def test_material_fee_confirmation_reuses_weekly_parser(self):
        self.set_image('tests/images/weekly_boss/confirmation.png')
        shape, (cost, stamina, button) = self.task._claim_dialog()
        self.assertEqual(('confirm', 60, 123, '确认'), (shape, cost, stamina, button.name))

    def test_actual_material_settlement_uses_weekly_exit_not_retry(self):
        self.load('reward_settlement')
        buttons = self.task._settlement()
        self.assertEqual(('退出副本', '重新挑战'), tuple(button.name for button in buttons))
        self.assertEqual(73, self.task.get_settlement_stamina())
        def navigate(step, source, target, **kwargs):
            self.assertEqual('退出副本', source(self.task.frame).name)
            self.assertFalse(target(self.task.frame))
        with patch.object(self.task, 'navigate_ui', side_effect=navigate) as navigation:
            self.task._leave_settlement(False)
        navigation.assert_called_once()


if __name__ == '__main__':
    unittest.main()
