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

    def test_reported_qingxiao_combat_frame(self):
        source = cv2.imread('tests/images/solo_qingxiao_combat_1440.png')
        for size in ((2560,1440), (1920,1080)):
            with self.subTest(size=size):
                self.check_frame(cv2.resize(source,size), (True,0,1))
                self.assertTrue(self.task.check_health_bar())
                self.assertTrue(self.task.has_target())
                self.task.do_reset_to_false()
                self.task.chars = [None, None, None]
                with patch.object(self.task, 'load_hotkey'), \
                     patch.object(self.task, 'ensure_levitator', return_value=True):
                    self.assertTrue(self.task.do_check_in_combat(target=False))
                self.assertEqual(len(self.task.chars), 1)
                self.assertEqual(type(self.task.get_current_char()).__name__, 'Qingxiao')

    def test_portrait_fallback_rejects_missing_player_or_extra_member(self):
        source = cv2.imread('tests/images/solo_qingxiao_combat_1440.png')
        for scenario in ('no_player', 'no_portrait', 'second_member', 'third_member'):
            frame = source.copy()
            if scenario == 'no_player':
                frame[1360:1399,1048:1093] = 0
            elif scenario == 'no_portrait':
                frame[275:397,2330:2455] = 0
            else:
                offset = 178 if scenario == 'second_member' else 356
                frame[275+offset:372+offset,2330:2455] = source[275:372,2330:2455]
            for size in ((2560,1440), (1920,1080)):
                with self.subTest(scenario=scenario,size=size):
                    self.check_frame(cv2.resize(frame,size), (False,-1,1))


if __name__ == '__main__':
    import unittest
    unittest.main()
