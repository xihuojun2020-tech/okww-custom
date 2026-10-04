import unittest
from unittest.mock import patch

from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.Labels import Labels
from src.char.Hsin import Hsin
from src.char.CharFactory import char_dict
from src.task.AutoCombatTask import AutoCombatTask


class TestHsinSupport(TaskTestCase):
    task_class = AutoCombatTask
    config = config

    def test_registration_and_all_templates_load(self):
        self.set_image('tests/images/solo_new_hud_1440.png')
        self.assertIs(char_dict[Labels.char_hsin]['cls'], Hsin)
        for label in (Labels.char_hsin, Labels.hsin_h1, Labels.hsin_h2,
                      Labels.hsin_lib1, Labels.hsin_lib2):
            with self.subTest(label=label):
                self.assertGreater(self.task.get_feature_by_name(label).mat.size, 0)

    def test_templates_match_their_pinned_source_frames(self):
        for label, image_id in ((Labels.char_hsin, 291), (Labels.hsin_lib1, 292),
                                (Labels.hsin_h1, 293), (Labels.hsin_h2, 294),
                                (Labels.hsin_lib2, 295)):
            with self.subTest(label=label):
                self.set_image(f'assets/images/hsin_{image_id}.png')
                self.assertIsNotNone(self.task.find_one(label, threshold=0.7))

    def test_second_liberation_marks_turn_complete(self):
        self.set_image('tests/images/solo_new_hud_1440.png')
        char = Hsin(self.task, 0)
        with patch.object(self.task, 'find_one', side_effect=lambda name, **kw:
                          object() if name == Labels.hsin_lib2 else None), \
             patch.object(char, 'liberation_available', return_value=True), \
             patch.object(char, 'click_liberation', return_value=True):
            self.assertTrue(char.lib())
        self.assertTrue(char.lib2_cast_this_turn)


if __name__ == '__main__':
    unittest.main()
