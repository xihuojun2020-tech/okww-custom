"""Sanitized portrait-only samples from the September 28 diagnostic package."""
from config import config
from ok.test.TaskTestCase import TaskTestCase

from src.Labels import Labels
from src.char.CharFactory import char_names, char_dict
from src.task.WeeklyBossTask import WeeklyBossTask
from src.char.BaseChar import BaseChar
from src.task.BaseCombatTask import CharDeadException
from unittest.mock import Mock, patch
from src.combat.roster_context import roster_context


config['debug'] = True


class TestRosterConfirmationImages(TaskTestCase):
    task_class = WeeklyBossTask
    config = config

    def test_abyss_death_and_switch_cooldown_preserve_roster(self):
        task = self.task
        task.chars = [BaseChar(task, i) for i in range(3)]
        task._battle_roster_confirmed = True
        task._char_context = roster_context(task)
        task.load_hotkey = Mock()
        task.in_team = Mock(return_value=(True, 0, 3))
        originals = tuple(task.chars)
        with patch('src.task.BaseCombatTask.get_char_by_pos') as identify:
            for image, current, dead in (('alive', 0, False), ('dead', 0, True),
                                         ('cooldown', 2, True), ('alive', 0, False)):
                self.set_image(f'tests/images/roster_confirmation/abyss_{image}.png')
                task.in_team.return_value = True, current, 3
                self.assertTrue(task.load_chars(force_full_scan=True))
                self.assertEqual(tuple(task.chars), originals)
                self.assertEqual([c.__dict__.get('_switch_unrevivable', False) for c in task.chars],
                                 [False, dead, False])
                self.assertIs(task.get_current_char(), task.chars[current])
                task.send_key = Mock()
                for c in task.chars:
                    c.do_perform = Mock(side_effect=lambda: task.send_key('e'))
                task.get_current_char().perform()
                task.send_key.assert_called_once_with('e')
                if image == 'cooldown':
                    task.send_key.reset_mock()
                    task.chars[0].perform()  # Old script must yield after the game's auto-switch.
                    task.send_key.assert_not_called()
            identify.assert_not_called()

    def test_gray_portrait_alone_does_not_mark_dead_and_all_dead_hands_off(self):
        task = self.task
        task.chars = [BaseChar(task, i) for i in range(3)]
        self.set_image('tests/images/roster_confirmation/abyss_alive.png')
        with patch.object(task, '_switch_portrait_gray', return_value=True):
            task._refresh_battle_roster(0, task.frame)
        self.assertFalse(any(c.__dict__.get('_switch_unrevivable', False) for c in task.chars))
        self.set_image('tests/images/roster_confirmation/abyss_dead.png')
        task.chars = [task.chars[1]]
        task._battle_roster_confirmed = True
        with self.assertRaises(CharDeadException):
            task._refresh_battle_roster(1, task.frame)
        self.assertFalse(task._battle_roster_confirmed)

    def test_incident_portraits_have_clear_identity(self):
        samples = (
            ('25b63ab2-1', (Labels.char_hiyuki, Labels.char_linnai, Labels.char_moning)),
            ('e69a866b-1', (Labels.yangyang_sp, Labels.char_aemeath, Labels.char_shorekeeper)),
        )
        for filename, identities in samples:
            self.set_image(f'tests/images/roster_confirmation/{filename}.png')
            for slot, expected in enumerate(identities, 1):
                with self.subTest(filename=filename, slot=slot):
                    box = self.task.get_box_by_name(f'box_char_{slot}')
                    best = self.task.find_best_match_in_box(box, char_names, threshold=.6)
                    self.assertIsNotNone(best)
                    self.assertEqual(char_dict[best.name]['canonical_name'],
                                     char_dict[expected]['canonical_name'])
                    self.assertGreaterEqual(best.confidence, .82)
                    competitors = [name for name in char_names if
                                   char_dict[name]['canonical_name'] != char_dict[best.name]['canonical_name']]
                    runner = self.task.find_best_match_in_box(box, competitors, threshold=.6)
                    if runner:
                        self.assertGreaterEqual(best.confidence - runner.confidence, .08)
