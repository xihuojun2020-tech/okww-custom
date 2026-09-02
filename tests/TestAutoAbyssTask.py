# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace

from src.task.AutoAbyssTask import (
    AVAILABLE,
    COMPLETED,
    LOCKED,
    aggregate_floor_states,
    match_travel_button,
    tower_click_point,
)


class TestAutoAbyssTask(unittest.TestCase):
    def test_match_travel_button_uses_the_same_card_row(self):
        title = SimpleNamespace(x=100, y=400, width=180, height=40)
        same_card = SimpleNamespace(x=1200, y=405, width=80, height=30)
        other_card = SimpleNamespace(x=1200, y=700, width=80, height=30)
        self.assertIs(match_travel_button(title, [other_card, same_card]), same_card)

    def test_match_travel_button_rejects_buttons_left_of_target_card(self):
        title = SimpleNamespace(x=500, y=400, width=180, height=40)
        wrong = SimpleNamespace(x=100, y=400, width=80, height=30)
        self.assertIsNone(match_travel_button(title, [wrong]))

    def test_aggregate_floor_states_prefers_completed_then_locked_then_available(self):
        self.assertEqual(
            aggregate_floor_states([True, False, False, False], [False, True, False, False]),
            (COMPLETED, LOCKED, AVAILABLE, AVAILABLE),
        )

    def test_tower_click_uses_title_x_and_diamond_height(self):
        title = SimpleNamespace(x=1000, y=100, width=200, height=40)
        self.assertEqual(tower_click_point(title, 2560), (1100 / 2560, 0.47))


if __name__ == "__main__":
    unittest.main()
