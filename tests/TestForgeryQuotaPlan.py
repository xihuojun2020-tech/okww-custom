import copy
import unittest
from uuid import uuid4
from src.task.forgery_quota_plan import *


def goal(domain=1, green=50):
    return dict(goal_id=str(uuid4()), domain=domain, need=dict(gold=0, purple=0, blue=0, green=green))


class TestForgeryQuotaPlan(unittest.TestCase):
    def test_inventory_deficit_estimate_and_old_goal_semantics(self):
        row = goal()
        row.update(inventory=dict(gold=1, purple=2, blue=3, green=4),
                   need=dict(gold=5, purple=3, blue=5, green=6))
        self.assertEqual(125, goal_units(row))
        self.assertEqual((2, 1, 200), claim_estimate(125))
        self.assertEqual((0, 2, 80), claim_estimate(26))
        self.assertEqual(75, next_forgery_goal([row], {row['goal_id']: 50})[1])
        row['inventory'] = dict(row['need'])
        self.assertEqual(0, goal_units(row))
        self.assertIsNone(next_forgery_goal([row], {}))
        self.assertEqual(50, goal_units(goal()))

    def test_explicit_unlimited_keeps_dormant_goals_and_requires_valid_limited_plan(self):
        rows = [goal()]
        self.assertFalse(forgery_limited({FORGERY_GOALS: rows, FORGERY_MODE: 'unlimited'}))
        self.assertEqual(rows, forgery_plan({FORGERY_GOALS: rows, FORGERY_MODE: 'unlimited'}))
        self.assertTrue(forgery_limited({FORGERY_GOALS: rows}))
        for tasks in ({FORGERY_MODE: 'materials'}, {FORGERY_MODE: 'invalid'}):
            with self.assertRaises(ValueError):
                forgery_plan(tasks)
        snapshot = dict(goal(), inventory=dict.fromkeys(TIERS, 0))
        for second in (goal(), dict(goal(), inventory=dict.fromkeys(TIERS, 0))):
            with self.assertRaisesRegex(ValueError, '同一领域'):
                forgery_plan({FORGERY_GOALS: [snapshot, second]})
        self.assertEqual(2, len(forgery_plan({FORGERY_GOALS: [goal(), goal()]})))

    def test_equivalence_and_strict_validation(self):
        self.assertEqual(40, green_units(dict(gold=1, purple=1, blue=1, green=1)))
        for bad in (-1, True, 1.5, '1', 1000000):
            with self.assertRaises(ValueError):
                green_units(dict(gold=bad, purple=0, blue=0, green=0))

    def test_claim_boundaries_and_current_stamina(self):
        for remaining in (1, 25, 26, 49, 50, 75):
            for stamina in (0, 39, 40, 79, 80, 240):
                expected = 0 if stamina < 40 else 2 if stamina >= 80 and remaining >= 50 else 1
                self.assertEqual(expected, claim_width(remaining, stamina))
        self.assertEqual(0, claim_width(0, 240))

    def test_order_copy_and_round_identity(self):
        rows = [goal(2), goal(4, 25)]
        loaded = forgery_plan({FORGERY_GOALS: rows})
        self.assertEqual((2, 2), next_forgery_claim(loaded, {}, 80))
        self.assertEqual((4, 1), next_forgery_claim(loaded, {rows[0]['goal_id']: 50}, 80))
        self.assertIsNone(next_forgery_claim(loaded, {r['goal_id']: 50 for r in rows}, 80))
        loaded[0]['need']['gold'] = 8
        self.assertEqual(0, rows[0]['need']['gold'])
        fresh = fresh_forgery_goals(rows)
        self.assertNotEqual(rows[0]['goal_id'], fresh[0]['goal_id'])
        self.assertEqual(rows[0]['need'], fresh[0]['need'])

    def test_legacy_empty_and_invalid_goals(self):
        self.assertEqual([], forgery_plan({}))
        for rows in ([goal()] * 2, [goal(), goal(), goal()], [dict(goal(), domain=0)], [dict(goal(), goal_id='bad')]):
            with self.assertRaises(ValueError):
                forgery_plan({FORGERY_GOALS: rows})
