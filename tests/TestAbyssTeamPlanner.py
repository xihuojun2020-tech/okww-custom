# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace
from dataclasses import replace
from src.char.BaseChar import CharType
from src.task.abyss_allocation import (
    ElementRule, FloorRequest, allocate, candidate_teams, team_preference,
    rules_from_config, CONFIG_FIELDS, element_for_character,
)
from src.task.abyss_team_planner import TEAM_PRESETS, TeamPlan, role_for_character

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

    def test_minimum_energy_filters_team_for_remaining_tower_cost(self):
        plan = plan_team([
            record(Labels.char_qingxiao, energy=9),
            record(Labels.char_denia, energy=10),
            record(Labels.char_chisa, energy=10),
            record(Labels.char_galbrena, energy=10),
            record(Labels.char_chouyuan, energy=10),
            record(Labels.char_shorekeeper, energy=10),
        ], minimum_energy=10)

        self.assertTrue(plan.complete)
        self.assertEqual(
            plan.members,
            (Labels.char_galbrena, Labels.char_chouyuan, Labels.char_shorekeeper),
        )


class TestAbyssAllocation(unittest.TestCase):
    def team(self, *members):
        return TeamPlan(TEAM_PRESETS[0], members, (), (), True, True, False, "test")

    def test_factory_roles_and_elements_are_authoritative(self):
        self.assertEqual(role_for_character(Labels.char_phrolova), CharType.MAIN_DPS)
        self.assertEqual(role_for_character(Labels.yangyang_sp), CharType.MAIN_DPS)
        self.assertEqual(element_for_character(Labels.char_linnai), "衍射")
        self.assertEqual(element_for_character(Labels.yangyang_sp), "湮灭")

    def test_hard_resistance_checks_sub_dps_but_allows_factory_healer(self):
        plan = self.team(Labels.char_qingxiao, Labels.char_denia, Labels.char_moning)
        self.assertIsNone(team_preference(plan, ElementRule(hard="热熔", center=True)))
        healer_only = self.team(Labels.char_qingxiao, Labels.char_chouyuan, Labels.char_moning)
        self.assertIsNotNone(team_preference(healer_only, ElementRule(hard="热熔", center=True)))

    def test_soft_center_allows_sub_dps_and_penalizes_main_even_if_favored(self):
        rule = ElementRule(("热熔", "气动"), soft="热熔", center=True)
        neutral_main = self.team(Labels.char_qingxiao, Labels.char_denia, Labels.char_moning)
        resisted_main = replace(neutral_main, members=(Labels.char_aemeath, Labels.char_denia, Labels.char_moning))
        self.assertEqual(team_preference(neutral_main, rule), (0, 0, -1))
        self.assertGreater(team_preference(resisted_main, rule), team_preference(neutral_main, rule))

    def test_two_main_dps_cannot_hide_resistance_behind_favored_main(self):
        plan = self.team(Labels.char_qingxiao, Labels.char_aemeath, Labels.char_moning)
        self.assertIsNone(team_preference(plan, ElementRule(("气动",), hard="热熔", center=True)))
        self.assertEqual(team_preference(plan, ElementRule(("气动",), soft="热熔", center=True))[0], 1)

    def test_side_fallback_order_and_healer_does_not_score_favored(self):
        rule = ElementRule(("衍射",), soft="热熔")
        clean = self.team(Labels.char_qingxiao, Labels.char_chouyuan, Labels.char_shorekeeper)
        sub = replace(clean, members=(Labels.char_qingxiao, Labels.char_denia, Labels.char_shorekeeper))
        main = replace(clean, members=(Labels.char_aemeath, Labels.char_chouyuan, Labels.char_shorekeeper))
        self.assertEqual(team_preference(clean, rule), (0, 0, 0))
        self.assertLess(team_preference(clean, rule), team_preference(sub, rule))
        self.assertLess(team_preference(sub, rule), team_preference(main, rule))

    def test_equal_favored_elements_and_unset_resistance(self):
        first = self.team(Labels.char_qingxiao, Labels.char_denia, Labels.char_chisa)
        second = replace(first, members=(Labels.char_aemeath, Labels.char_denia, Labels.char_chisa))
        rule = ElementRule(("气动", "热熔"), center=True)
        self.assertEqual(team_preference(first, rule), team_preference(second, rule))

    def test_config_has_twelve_independent_fields_and_snapshot(self):
        config = {"Center Lower Resisted 1": "导电", "Center Upper Resisted 2": "热熔"}
        rules = rules_from_config(config)
        config["Center Lower Resisted 1"] = "气动"
        self.assertEqual(len(CONFIG_FIELDS), 12)
        self.assertEqual(rules["Center Lower"].hard, "导电")
        self.assertEqual(rules["Center Upper"].soft, "热熔")
        self.assertIsNone(rules["Left"].soft)
        with self.assertRaises(ValueError):
            rules_from_config({"Left Favored": "invalid"})

    def test_candidates_replace_owned_forbidden_sub_and_preserve_role(self):
        records = [record(x) for x in (Labels.char_qingxiao, Labels.char_denia, Labels.char_chisa,
                                      Labels.char_chouyuan)]
        candidates = candidate_teams(records)
        self.assertTrue(any(Labels.char_denia not in p.members for p in candidates))
        for plan in candidates:
            for original, replacement in plan.substitutions:
                self.assertEqual(role_for_character(original), role_for_character(replacement))

    def test_roster_without_preset_anchor_uses_same_role_structure(self):
        records = [record(x) for x in (Labels.char_calcharo, Labels.char_yinlin, Labels.char_verina)]
        candidates = candidate_teams(records)
        self.assertTrue(candidates)
        self.assertTrue(all(Labels.char_calcharo in p.members for p in candidates))

    def test_unknown_identity_and_unknown_rover_do_not_become_neutral_dps(self):
        records = [record("unknown"), record(Labels.char_rover), record(Labels.char_denia), record(Labels.char_chisa)]
        self.assertEqual(candidate_teams(records), ())

    def test_shared_energy_is_not_duplicated_across_teams(self):
        records = [record(x, energy=5) for x in (Labels.char_qingxiao, Labels.char_denia,
                                                Labels.char_chisa, Labels.char_aemeath)]
        floors = [FloorRequest("center", i, 5, ElementRule(center=True), True) for i in range(2)]
        result = allocate(records, floors)
        self.assertEqual(sum(p is not None for _, p in result.assignments), 1)

    def test_center_both_halves_reserve_different_main_dps_before_sides(self):
        records = [record(Labels.char_qingxiao, 5), record(Labels.char_aemeath, 5),
                   record(Labels.char_denia, 10), record(Labels.char_chisa, 10)]
        floors = [FloorRequest("center", 1, 5, ElementRule(center=True), True),
                  FloorRequest("center", 2, 5, ElementRule(hard="气动", center=True), True),
                  FloorRequest("left", 0, 1, ElementRule(), False)]
        result = allocate(records, floors)
        self.assertIn(Labels.char_qingxiao, result.assignments[0][1].members)
        self.assertIn(Labels.char_aemeath, result.assignments[1][1].members)
        self.assertIsNone(result.assignments[2][1])

    def test_priority_coverage_beats_favored_and_skip_blocks_later_floors(self):
        records = [record(x, energy=5) for x in (Labels.char_qingxiao, Labels.char_denia, Labels.char_chisa)]
        floors = [FloorRequest("left", 0, 1, ElementRule(), False),
                  FloorRequest("left", 1, 2, ElementRule(), False),
                  FloorRequest("center", 0, 5, ElementRule(center=True), True)]
        result = allocate(records, floors)
        self.assertEqual([p is not None for _, p in result.assignments], [False, False, True])

    def test_search_cancellation_propagates(self):
        def cancel():
            raise InterruptedError("cancelled")
        with self.assertRaises(InterruptedError):
            allocate([], [FloorRequest("left", 0, 1, ElementRule(), False)], checkpoint=cancel)

    def test_aliases_cannot_duplicate_energy_or_a_character(self):
        records = [record(Labels.char_carlotta), record(Labels.char_carlotta2),
                   record(Labels.char_zhezhi), record(Labels.char_shorekeeper)]
        for plan in candidate_teams(records):
            self.assertEqual(plan.members.count(Labels.char_carlotta), 1)
            self.assertNotIn(Labels.char_carlotta2, plan.members)


if __name__ == "__main__":
    unittest.main()
