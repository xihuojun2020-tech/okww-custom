"""Sanitized portrait-only samples from the September 28 diagnostic package."""
from config import config
from ok.test.TaskTestCase import TaskTestCase

from src.Labels import Labels
from src.char.CharFactory import char_names, char_dict
from src.task.WeeklyBossTask import WeeklyBossTask


config['debug'] = True


class TestRosterConfirmationImages(TaskTestCase):
    task_class = WeeklyBossTask
    config = config

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
