import tempfile
from pathlib import Path

import cv2
from unittest.mock import Mock, patch
from ok.test.TaskTestCase import TaskTestCase
from config import config
from src.task.AutoCombatTask import AutoCombatTask


class TestSoloTeam(TaskTestCase):
    task_class = AutoCombatTask
    config = config

    def check_frame(self, frame, expected):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'frame.png')
            cv2.imwrite(path, frame)
            self.set_image(path)
            self.assertEqual(self.task.in_team(), expected)
            self.assertEqual(self.task.in_team_and_world(), expected[0])

    def test_real_solo_hud_at_both_resolutions(self):
        source = cv2.imread('tests/images/solo_hud_1440.png')
        for width, height in ((2560, 1440), (1920, 1080)):
            with self.subTest(size=(width, height)):
                self.check_frame(cv2.resize(source, (width, height)), (True, 0, 1))

    def test_low_health_still_detected(self):
        source = cv2.imread('tests/images/solo_hud_1440.png')
        source[383:388,2350:2442] = 45
        for size in ((2560,1440),(1920,1080)):
            self.check_frame(cv2.resize(source,size), (True,0,1))

    def test_actual_team_gate_enters_auto_combat_loop(self):
        self.set_image('tests/images/solo_hud_1440.png')
        self.task.scene.reset()
        char = Mock()
        with patch.object(self.task, 'warm_up_char_features'), \
             patch.object(self.task, 'in_combat', side_effect=[True, False]), \
             patch.object(self.task, 'get_current_char', return_value=char), \
             patch.object(self.task, 'switch_healer'), \
             patch.object(self.task, 'combat_end'):
            self.assertTrue(self.task._run_combat())
        char.perform.assert_called_once()

    def test_solo_switch_keeps_attacking_without_team_switch(self):
        char = Mock()
        self.task.chars = [char]
        with patch.object(self.task, 'send_key') as send, \
             patch.object(self.task, 'update_lib_portrait_icon') as portrait:
            self.task.switch_next_char(char)
        char.continues_normal_attack.assert_called_once_with(0.2)
        char.get_current_con.assert_not_called()
        send.assert_not_called()
        portrait.assert_not_called()

    def test_missing_or_extra_health_bars_do_not_imply_solo(self):
        source = cv2.imread('tests/images/solo_hud_1440.png')
        for width, height in ((2560, 1440), (1920, 1080)):
            for scenario in ('blank', 'no_player', 'no_party', 'second_party', 'third_party'):
                with self.subTest(size=(width, height), scenario=scenario):
                    frame = source.copy()
                    if scenario == 'blank':
                        frame[:] = 0
                    elif scenario == 'no_player':
                        frame[1300:] = 0
                    elif scenario == 'no_party':
                        frame[:500] = 0
                    else:
                        y = 554 if scenario == 'second_party' else 732
                        frame[y:y+20,2334:2450] = source[375:395,2334:2450]
                    self.check_frame(cv2.resize(frame, (width,height)), (False,-1,1))

    def test_existing_multi_member_combat_frames(self):
        for name, current in (('a4_domain_unfinished_1.png',2),('a4_domain_unfinished_2.png',0)):
            self.set_image('tests/images/'+name)
            self.assertEqual(self.task.in_team(), (True,current,3))

    def test_multi_team_with_unreadable_digits_is_not_solo(self):
        for name in ('a4_domain_unfinished_1.png', 'a4_domain_unfinished_2.png'):
            self.set_image('tests/images/' + name)
            find_one = self.task.find_one
            def missing_digits(name, *args, **kwargs):
                if name in ('char_1_text', 'char_2_text', 'char_3_text'):
                    return None
                return find_one(name, *args, **kwargs)
            with patch.object(self.task, 'find_one', side_effect=missing_digits):
                self.assertEqual(self.task.in_team(), (False,-1,1))

    def test_map_is_not_a_solo_team(self):
        self.set_image('tests/images/big_map.png')
        self.assertFalse(self.task.in_team()[0])


if __name__ == '__main__':
    import unittest
    unittest.main()
