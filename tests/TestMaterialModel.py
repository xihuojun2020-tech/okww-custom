import unittest
from datetime import datetime
from src.materials.model import *


class TestMaterialModel(unittest.TestCase):
    def test_only_upward(self):
        self.assertEqual(calculate_gap(Counts(gold=1), Counts(green=3)).missing, Counts(green=3))
        result = calculate_gap(Counts(15, 6), Counts(6, 3, 2))
        self.assertTrue(is_satisfied(result))
        self.assertEqual(result.synthesis, Counts(0, 3, 2))
        self.assertEqual(calculate_gap(Counts(2), Counts(0, 1)).missing, Counts(0, 1))
        self.assertTrue(is_satisfied(calculate_gap(Counts(27), Counts(gold=1))))

    def test_validation(self):
        for value in (-1, True, 1.2, '1'):
            with self.assertRaises(ValueError):
                Counts(green=value)

    def test_week_boundary(self):
        self.assertEqual(week_id(datetime.fromisoformat('2026-09-14T03:59:00+08:00')), '2026-09-07')
        self.assertEqual(week_id(datetime.fromisoformat('2026-09-14T04:00:00+08:00')), '2026-09-14')

    def sample(self, claim='a', stamina=80):
        drops = (Drop((0, 0), 'g', 'rectifier_b', 'green', 7),
                 Drop((1, 0), 'g', 'rectifier_b', 'green', 6),
                 Drop((1, 1), 'b', 'rectifier_b', 'blue', 16),
                 Drop((1, 2), 'p', 'rectifier_b', 'purple', 3),
                 Drop((1, 3), 'monster', None, 'green', 100))
        return Settlement(claim, 'p', 't', 'rectifier_b', stamina, True, drops, 2)

    def test_units_and_rates(self):
        record = self.sample()
        self.assertEqual(summarize_target(record.drops, record.target_group), Counts(13, 16, 3))
        result = aggregate_settlements([record])
        self.assertEqual(result['reward_units'], 2)
        self.assertEqual(result['equivalent'], 88)
        self.assertEqual(result['per_unit'], 44)
        self.assertEqual(result['per_stamina'], 1.1)
        result = aggregate_settlements([record, self.sample('b', None)])
        self.assertEqual(result['per_stamina'], 1.1)
        self.assertEqual(result['reward_units'], 4)

    def test_identical_slots_are_real_drops(self):
        drops = (Drop((0, 0), 'g', 'a', 'green', 6), Drop((1, 0), 'g', 'a', 'green', 6))
        self.assertEqual(count_reward_units(drops, 'a'), 2)
        with self.assertRaises(ValueError):
            Settlement('a', 'p', 't', 'a', 40, True, drops + drops, 4)

    def test_partial_does_not_become_zero(self):
        partial = Settlement('b', 'p', 't', 'rectifier_b', 40, False, (), None, ('missing_page',))
        result = aggregate_settlements([self.sample(), partial])
        self.assertEqual(result['per_unit'], 44)
        self.assertEqual(result['incomplete_claims'], 1)
