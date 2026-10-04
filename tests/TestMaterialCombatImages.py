import unittest
from types import SimpleNamespace
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


if __name__ == '__main__':
    unittest.main()
