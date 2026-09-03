# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace

from src.Labels import Labels
from src.task.abyss_team_planner import (
    ROVER_AERO,
    ROVER_SPECTRO,
    ROVER_UNKNOWN,
    effective_character_id,
    plan_team,
)


def record(character_id, energy=10, level=90, confidence=0.9, rover_form=None):
    return SimpleNamespace(
        character_id=character_id,
        energy=energy,
        level=level,
        confidence=confidence,
        rover_form=rover_form,
    )


class TestAbyssTeamPlanner(unittest.TestCase):
    def test_second_queue_complete_beats_first_queue_two_member_core(self):
        plan = plan_team([
            record(Labels.char_qingxiao), record(Labels.char_denia),
            record(Labels.char_galbrena), record(Labels.char_chouyuan),
            record(Labels.char_shorekeeper), record(Labels.char_verina),
        ])
        self.assertEqual(
            plan.members,
            (Labels.char_galbrena, Labels.char_chouyuan, Labels.char_shorekeeper),
        )
        self.assertTrue(plan.complete)
        self.assertEqual(plan.preset.queue, 2)

    def test_first_queue_complete_beats_second_queue_complete(self):
        plan = plan_team([
            record(Labels.char_qingxiao), record(Labels.char_denia), record(Labels.char_chisa),
            record(Labels.char_galbrena), record(Labels.char_chouyuan), record(Labels.char_shorekeeper),
        ])
        self.assertEqual(plan.members, (Labels.char_qingxiao, Labels.char_denia, Labels.char_chisa))
        self.assertEqual(plan.preset.queue, 1)

    def test_qingxiao_core_uses_verina_for_missing_healer(self):
        plan = plan_team([
            record(Labels.char_qingxiao),
            record(Labels.char_denia),
            record(Labels.char_verina, energy=8, level=90),
        ])
        self.assertEqual(plan.members, (Labels.char_qingxiao, Labels.char_denia, Labels.char_verina))
        self.assertEqual(plan.substitutions, ((Labels.char_chisa, Labels.char_verina),))
        self.assertFalse(plan.complete)
        self.assertTrue(plan.executable)

    def test_regular_candidate_does_not_break_another_two_member_core(self):
        plan = plan_team([
            record(Labels.char_qingxiao), record(Labels.char_denia),
            record(Labels.char_zani, energy=10), record(Labels.char_phoebe, energy=10),
            record(Labels.char_verina, energy=5),
        ])
        self.assertEqual(plan.members[-1], Labels.char_verina)
        self.assertNotIn(Labels.char_zani, plan.members)
        self.assertNotIn(Labels.char_phoebe, plan.members)

    def test_two_member_core_can_be_used_only_when_no_regular_candidate_exists(self):
        plan = plan_team([
            record(Labels.char_qingxiao), record(Labels.char_denia),
            record(Labels.char_zani, energy=8), record(Labels.char_phoebe, energy=10),
        ])
        self.assertTrue(plan.executable)
        self.assertIn(plan.members[-1], (Labels.char_zani, Labels.char_phoebe))
        self.assertTrue(plan.broke_two_member_core)

    def test_rover_forms_are_strict_and_unknown_never_completes_a_rover_preset(self):
        base = [record(Labels.char_zani), record(Labels.char_phoebe)]
        spectro = plan_team(base + [record(Labels.char_rover, rover_form=ROVER_SPECTRO)])
        aero = plan_team(base + [record(Labels.char_rover, rover_form=ROVER_AERO)])
        unknown = plan_team(base + [record(Labels.char_rover, rover_form=ROVER_UNKNOWN)])
        self.assertTrue(spectro.complete)
        self.assertEqual(spectro.members[-1], ROVER_SPECTRO)
        self.assertFalse(aero.complete)
        self.assertFalse(unknown.complete)
        self.assertEqual(effective_character_id(base[0]), Labels.char_zani)

    def test_fewer_than_three_usable_characters_returns_non_executable_plan(self):
        plan = plan_team([
            record(Labels.char_qingxiao),
            record(Labels.char_denia),
            record(Labels.char_verina, energy=0),
        ])
        self.assertFalse(plan.executable)
        self.assertEqual(len(plan.members), 2)


if __name__ == "__main__":
    unittest.main()
