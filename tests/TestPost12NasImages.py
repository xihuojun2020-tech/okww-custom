"""Identity-redacted images from the reviewed October 6 NAS incidents."""
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.NightmareNestTask import NightmareNestTask
from src.char.CharFactory import get_char_by_pos, char_names, char_dict
from src.char.BaseChar import BaseChar
from src.Labels import Labels
from src.char.Youhu import Youhu
from unittest.mock import patch


class TestPost12NasImages(TaskTestCase):
    task_class = NightmareNestTask
    config = config

    def load(self, name):
        self.set_image('tests/images/post12_nas/' + name + '.png')

    def test_actual_mengmo_row_retains_legacy_name(self):
        self.load('nightmare_top')
        row = self.task._nightmare_rows(self.task.frame)['三王峰梦魇聚落']
        self.assertEqual((0, 36, '直接挑战'), (row[0], row[1], row[2].name))

    def test_actual_danjin_portrait_can_replace_zhezhi_cache(self):
        char = BaseChar(self.task, 2, char_name=Labels.char_zhezhi, confidence=.95)
        for _ in range(3):
            self.load('changed_roster')
            box = self.task.get_box_by_name('box_char_3')
            best = self.task.find_best_match_in_box(box, char_names, threshold=.6)
            self.assertEqual(char_dict[Labels.char_danjin]['canonical_name'],
                             char_dict[best.name]['canonical_name'])
            char = get_char_by_pos(self.task, box, 2, char, force_full_scan=True)
        self.assertFalse(char._identity_unconfirmed)
        self.assertEqual(Labels.char_danjin, char.char_name)

    def test_actual_victory_is_confirmed(self):
        self.load('liberation_victory')
        self.assertTrue(self.task.has_challenge_success())

    def test_youhu_selection_and_returned_combat_are_distinct(self):
        char = Youhu(self.task, 0, char_name=Labels.char_youhu)
        self.load('liberation_active_pre7')
        self.assertTrue(char._liberation_choice_visible())
        with patch.object(self.task, 'send_key') as send, \
                patch.object(self.task, 'wait_until', return_value=True), \
                patch.object(BaseChar, 'recheck_liberation_timeout') as recheck:
            char.recheck_liberation_timeout()
        send.assert_called_once_with('w', after_sleep=.1)
        recheck.assert_called_once()
        for name in ('liberation_active_pre8',):
            self.load(name)
            self.assertFalse(char._liberation_choice_visible())
            self.task._in_combat = True
            team = self.task.in_team()
            solo = self.task.find_one('solo_player_health', threshold=.75, use_gray_scale=True,
                                      horizontal_variance=.002, vertical_variance=.002)
            target, health = self.task.has_target(), self.task.check_health_bar()
            self.assertTrue(team[0] or solo)
            self.assertTrue(target or health)
