"""Pure, bounded whole-run allocation of preset-based teams and shared energy."""
from dataclasses import dataclass
from itertools import product
from heapq import nsmallest

from src.char.BaseChar import CharType, Elements
from src.char.CharFactory import char_dict
from src.Labels import Labels
from src.task.abyss_team_planner import (
    TEAM_PRESETS, TeamPlan, effective_character_id, role_for_character,
    ROVER_AERO, ROVER_HAVOC, ROVER_SPECTRO,
)

ELEMENTS = {Elements.ICE: "冷凝", Elements.FIRE: "热熔", Elements.ELECTRIC: "导电",
            Elements.WIND: "气动", Elements.SPECTRO: "衍射", Elements.HAVOC: "湮灭"}
OPTIONS = ("无", *ELEMENTS.values())
RULE_GROUPS = ("Left", "Right", "Center Lower", "Center Upper")
CONFIG_FIELDS = {
    f"{group} {field}": f"{label}{description}"
    for group, label in zip(RULE_GROUPS, ("左塔", "右塔", "中塔1—2层", "中塔3—4层"))
    for field, description in (
        (("Favored", "顺属性"), ("Resisted", "逆属性（允许兜底）")) if group in ("Left", "Right") else
        (("Favored 1", "顺属性1"), ("Favored 2", "顺属性2（同优先级）"),
         ("Resisted 1", "逆属性1（禁止主C和副C）"), ("Resisted 2", "逆属性2（主C尽量避开）")))
}


def element_for_character(identity):
    overrides = {ROVER_AERO: "气动", ROVER_HAVOC: "湮灭", ROVER_SPECTRO: "衍射",
                 Labels.char_suisui: "冷凝"}
    return overrides.get(identity) or ELEMENTS.get(char_dict.get(identity, {}).get("ring_index"))


@dataclass(frozen=True)
class ElementRule:
    favored: tuple = ()
    hard: str | None = None
    soft: str | None = None
    center: bool = False


def rules_from_config(config):
    def value(key):
        result = config.get(key, "无")
        if result not in OPTIONS:
            raise ValueError(f"深塔属性设置无效：{key}={result}")
        return None if result == "无" else result
    rules = {}
    for group in RULE_GROUPS:
        center = group.startswith("Center")
        favored = (value(f"{group} Favored 1"), value(f"{group} Favored 2")) if center else (value(f"{group} Favored"),)
        rules[group] = ElementRule(tuple(x for x in favored if x),
                                   value(f"{group} Resisted 1") if center else None,
                                   value(f"{group} Resisted 2") if center else value(f"{group} Resisted"), center)
    return rules


def team_preference(plan, rule):
    """None means forbidden; otherwise lower resistance / more favored is better."""
    main = [x for x in plan.members if role_for_character(x) == CharType.MAIN_DPS]
    sub = [x for x in plan.members if role_for_character(x) == CharType.SUB_DPS]
    if not main:
        return None
    damage = [element_for_character(x) for x in main + sub]
    if (rule.hard or rule.soft or rule.favored) and None in damage:
        return None
    if rule.hard and rule.hard in damage:
        return None
    main_resisted = sum(element_for_character(x) == rule.soft for x in main) if rule.soft else 0
    sub_resisted = sum(element_for_character(x) == rule.soft for x in sub) if rule.soft and not rule.center else 0
    favored = sum(element_for_character(x) in rule.favored for x in main)
    return main_resisted, sub_resisted, -favored


def recognized_roster(records):
    roster = {}
    for record in records:
        identity = effective_character_id(record)
        if record.energy is None or record.level is None or record.energy <= 0 or record.level <= 60:
            continue
        if identity not in char_dict and identity not in (ROVER_AERO, ROVER_HAVOC, ROVER_SPECTRO):
            continue
        old = roster.get(identity)
        if old is None or record.confidence > old.confidence:
            roster[identity] = record
    return roster


def candidate_teams(records, checkpoint=lambda: None):
    """Preserve preset role structure; rank retained members above substitutions."""
    roster = recognized_roster(records)
    by_role = {role: sorted(x for x in roster if role_for_character(x) == role) for role in CharType}
    candidates = {}
    for preset in TEAM_PRESETS:
        checkpoint()
        pools = [by_role[role_for_character(x)] for x in preset.members]
        for members in product(*pools):
            if len(set(members)) != 3:
                continue
            matched = tuple(x for x, original in zip(members, preset.members) if x == original)
            if not any(role_for_character(x) == CharType.MAIN_DPS for x in members):
                continue
            substitutions = tuple((a, b) for a, b in zip(preset.members, members) if a != b)
            plan = TeamPlan(preset, members, matched, substitutions, not substitutions, True, False,
                            "完整预设" if not substitutions else "沿用预设定位结构，同定位替补")
            key = tuple(sorted(members))
            old = candidates.get(key)
            if old is None or (len(substitutions), preset.queue, members) < (len(old.substitutions), old.preset.queue, old.members):
                candidates[key] = plan
    return tuple(sorted(candidates.values(), key=lambda p: (len(p.substitutions), p.preset.queue, p.members)))


@dataclass(frozen=True)
class FloorRequest:
    tower: str
    index: int
    cost: int
    rule: ElementRule
    priority: bool


@dataclass(frozen=True)
class Allocation:
    assignments: tuple  # (FloorRequest, TeamPlan | None)
    approximate: bool


def allocate(records, floors, *, beam_width=256, checkpoint=lambda: None):
    """Beam search over shared energy. Report pruning; never claim impossibility from it.

    A skipped floor blocks the rest of that tower. The ledger is shared by every
    candidate, and both center halves participate before any battle starts.
    """
    roster = recognized_roster(records)
    identities = sorted(roster)
    positions = {x: i for i, x in enumerate(identities)}
    if beam_width < 1:
        raise ValueError("beam_width must be positive")
    candidates = candidate_teams(records, checkpoint)
    indexed = [(p, tuple(positions[x] for x in p.members)) for p in candidates]
    # score, energy ledger, blocked towers, previous members, assignments
    states = [((0,) * 7, tuple(roster[x].energy for x in identities), frozenset(), (), ())]
    approximate = False
    for floor in floors:
        checkpoint()
        legal = [(p, indices, preference) for p, indices in indexed
                 if (preference := team_preference(p, floor.rule)) is not None]
        if len(legal) > beam_width:
            # Preserve a route for each character before filling with locally
            # preferred teams. This keeps rare center DPS and alternate healers.
            legal.sort(key=lambda item: (*item[2], len(item[0].substitutions), item[0].preset.queue))
            selected = set()
            represented = set()
            for i, (_, indices, _) in enumerate(legal):
                if any(index not in represented for index in indices):
                    selected.add(i)
                    represented.update(indices)
            for i in range(len(legal)):
                if len(selected) >= beam_width:
                    break
                selected.add(i)
            legal = [legal[i] for i in sorted(selected)]
            approximate = True
        expanded = {}
        for state_index, (score, energy, blocked, previous, path) in enumerate(states):
            if state_index % 16 == 0:
                checkpoint()
            options = [(None, (), (0, 0, 0))]
            if floor.tower not in blocked:
                options += [(p, ids, preference) for p, ids, preference in legal
                            if all(energy[i] >= floor.cost for i in ids)]
            for plan, indices, preference in options:
                next_energy = list(energy)
                for i in indices:
                    next_energy[i] -= floor.cost
                next_blocked = blocked if plan else blocked | {floor.tower}
                members = plan.members if plan else previous
                delta = ((-int(floor.priority), -1, *preference, len(plan.substitutions),
                          plan.preset.queue + int(bool(previous) and previous != members)) if plan else (0,) * 7)
                next_score = tuple(a + b for a, b in zip(score, delta))
                next_state = (next_score, tuple(next_energy), next_blocked, members, path + ((floor, plan),))
                key = (tuple(next_energy), next_blocked, members)
                if key not in expanded or next_score < expanded[key][0]:
                    expanded[key] = next_state
                # Bound memory as well as survivor count for large owned rosters.
                if len(expanded) > beam_width * 4:
                    approximate = True
                    survivors = nsmallest(beam_width, expanded.items(), key=lambda item: item[1][0])
                    expanded = dict(survivors)
        ordered = sorted(expanded.values(), key=lambda s: s[0])
        approximate |= len(ordered) > beam_width
        states = ordered[:beam_width]
    best = min(states, key=lambda s: s[0])
    return Allocation(best[-1], approximate)
