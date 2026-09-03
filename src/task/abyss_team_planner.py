# -*- coding: utf-8 -*-
"""Pure preset-team planning for the automatic abyss test task."""
from dataclasses import dataclass
from typing import Iterable

from src.Labels import Labels
from src.char.BaseChar import CharType
from src.char.CharFactory import char_dict


ROVER_SPECTRO = "rover_spectro"
ROVER_AERO = "rover_aero"
ROVER_HAVOC = "rover_havoc"
ROVER_UNKNOWN = "rover_unknown"
ROVER_IDENTITIES = frozenset((ROVER_SPECTRO, ROVER_AERO, ROVER_HAVOC, ROVER_UNKNOWN))
ROVER_CHARACTER_IDS = frozenset((Labels.char_rover, Labels.char_rover_male))


@dataclass(frozen=True)
class TeamPreset:
    queue: int
    members: tuple[str, str, str]
    display_names: tuple[str, str, str]


@dataclass(frozen=True)
class TeamPlan:
    preset: TeamPreset
    members: tuple[str, ...]
    matched: tuple[str, ...]
    substitutions: tuple[tuple[str, str], ...]
    complete: bool
    executable: bool
    broke_two_member_core: bool
    reason: str


def _preset(queue, members, names):
    return TeamPreset(queue=queue, members=members, display_names=names)


TEAM_PRESETS = (
    _preset(1, (Labels.char_qingxiao, Labels.char_denia, Labels.char_chisa),
            ("清宵", "达妮娅", "千咲")),
    _preset(1, (Labels.yangyang_sp, Labels.char_chisa, Labels.char_suisui),
            ("秧秧·玄翎", "千咲", "穗穗")),
    _preset(1, (Labels.char_hiyuki, Labels.char_lucilla, Labels.char_chisa),
            ("绯雪", "洛瑟拉", "千咲")),
    _preset(1, (Labels.char_hiyuki, Labels.char_lucilla, Labels.char_suisui),
            ("绯雪", "洛瑟拉", "穗穗")),
    _preset(1, (Labels.char_lucy, Labels.char_rebecca, Labels.char_moning),
            ("露西", "丽贝卡", "莫宁")),
    _preset(1, (Labels.char_aemeath, Labels.char_linnai, Labels.char_moning),
            ("爱弥斯", "琳奈", "莫宁")),
    _preset(1, (Labels.char_luhesi, Labels.char_linnai, Labels.char_moning),
            ("陆赫斯", "琳奈", "莫宁")),
    _preset(1, (Labels.char_luhesi, Labels.char_denia, Labels.char_moning),
            ("陆赫斯", "达妮娅", "莫宁")),
    _preset(1, (Labels.char_aemeath, Labels.char_denia, Labels.char_chisa),
            ("爱弥斯", "达妮娅", "千咲")),
    _preset(1, (Labels.char_xigelika, Labels.char_chouyuan, Labels.char_shorekeeper),
            ("西格莉卡", "仇远", "守岸人")),
    _preset(1, (Labels.char_xigelika, Labels.char_linnai, Labels.char_moning),
            ("西格莉卡", "琳奈", "莫宁")),
    _preset(2, (Labels.char_galbrena, Labels.char_chouyuan, Labels.char_shorekeeper),
            ("嘉贝莉娜", "仇远", "守岸人")),
    _preset(2, (Labels.char_galbrena, Labels.char_lupa, Labels.char_shorekeeper),
            ("嘉贝莉娜", "露帕", "守岸人")),
    _preset(2, (Labels.char_galbrena, Labels.char_iuno, Labels.char_shorekeeper),
            ("嘉贝莉娜", "尤诺", "守岸人")),
    _preset(2, (Labels.Augusta, Labels.char_iuno, Labels.char_shorekeeper),
            ("奥古斯塔", "尤诺", "守岸人")),
    _preset(2, (Labels.char_cartethyia, Labels.char_ciaccona, Labels.char_shorekeeper),
            ("卡提希娅", "夏空", "守岸人")),
    _preset(2, (Labels.char_cartethyia, Labels.char_ciaccona, ROVER_AERO),
            ("卡提希娅", "夏空", "风主")),
    _preset(2, (Labels.char_cartethyia, Labels.char_ciaccona, Labels.char_chisa),
            ("卡提希娅", "夏空", "千咲")),
    _preset(2, (Labels.char_phrolova, Labels.char_cantarella, Labels.char_shorekeeper),
            ("弗洛洛", "坎特蕾拉", "守岸人")),
    _preset(2, (Labels.char_phrolova, Labels.char_cantarella, Labels.char_roccia),
            ("弗洛洛", "坎特蕾拉", "洛可可")),
    _preset(2, (Labels.char_zani, Labels.char_phoebe, ROVER_SPECTRO),
            ("赞妮", "菲比", "光主")),
    _preset(2, (Labels.char_zani, Labels.char_phoebe, Labels.char_chisa),
            ("赞妮", "菲比", "千咲")),
    _preset(2, (Labels.char_zani, Labels.char_phoebe, Labels.char_shorekeeper),
            ("赞妮", "菲比", "守岸人")),
    _preset(2, (Labels.char_carlotta, Labels.char_zhezhi, Labels.char_shorekeeper),
            ("柯莱塔", "折枝", "守岸人")),
)


def effective_character_id(record):
    character_id = record.character_id
    if character_id in ROVER_CHARACTER_IDS:
        return getattr(record, "rover_form", None) or ROVER_UNKNOWN
    return character_id


def role_for_character(character_id):
    if character_id == ROVER_SPECTRO:
        return CharType.SUB_DPS
    if character_id == ROVER_AERO:
        return CharType.HEALER
    if character_id in (ROVER_HAVOC, ROVER_UNKNOWN):
        return CharType.MAIN_DPS
    return char_dict.get(character_id, {}).get("char_type", CharType.MAIN_DPS)


def _record_quality(record):
    return (
        record.energy is not None,
        record.level is not None,
        float(record.confidence),
    )


def _members_quality(member_ids, available):
    records = [available[member_id] for member_id in member_ids if member_id in available]
    if not records:
        return 0, 0, 0.0
    return (
        min(record.energy for record in records),
        sum(record.level for record in records),
        sum(float(record.confidence) for record in records),
    )


def _substitute_key(record):
    return (
        -record.energy,
        -record.level,
        -float(record.confidence),
        effective_character_id(record),
    )


def _best_substitute(pool, missing_id):
    same_role = [record for record in pool if role_for_character(effective_character_id(record)) == role_for_character(missing_id)]
    candidates = same_role or list(pool)
    return min(candidates, key=_substitute_key, default=None)


def plan_team(records: Iterable[object]) -> TeamPlan:
    available = {}
    for record in records:
        if record.energy is None or record.level is None or record.energy <= 0 or record.level <= 60:
            continue
        identity = effective_character_id(record)
        old = available.get(identity)
        if old is None or _record_quality(record) > _record_quality(old):
            available[identity] = record

    complete = [preset for preset in TEAM_PRESETS if all(member in available for member in preset.members)]
    if complete:
        def full_key(preset):
            energy, level, confidence = _members_quality(preset.members, available)
            return preset.queue, -energy, -level, -confidence, preset.members

        preset = min(complete, key=full_key)
        return TeamPlan(
            preset=preset,
            members=preset.members,
            matched=preset.members,
            substitutions=(),
            complete=True,
            executable=True,
            broke_two_member_core=False,
            reason=f"第{preset.queue}队列完整预设",
        )

    def partial_key(preset):
        matched = tuple(member for member in preset.members if member in available)
        energy, level, confidence = _members_quality(matched, available)
        return -len(matched), preset.queue, -energy, -level, -confidence, preset.members

    preset = min(TEAM_PRESETS, key=partial_key)
    matched = tuple(member for member in preset.members if member in available)
    protected_two_member_ids = set()
    for other in TEAM_PRESETS:
        if other == preset:
            continue
        other_matches = tuple(member for member in other.members if member in available)
        if len(other_matches) >= 2:
            protected_two_member_ids.update(other_matches)
    protected_two_member_ids.difference_update(matched)

    members = []
    substitutions = []
    used = set()
    broke_two_member_core = False
    for missing_id in preset.members:
        if missing_id in available:
            members.append(missing_id)
            used.add(missing_id)
            continue
        ordinary = [
            record for identity, record in available.items()
            if identity not in used and identity not in preset.members and identity not in protected_two_member_ids
        ]
        protected = [
            record for identity, record in available.items()
            if identity not in used and identity not in preset.members and identity in protected_two_member_ids
        ]
        substitute = _best_substitute(ordinary, missing_id)
        if substitute is None:
            substitute = _best_substitute(protected, missing_id)
            broke_two_member_core = broke_two_member_core or substitute is not None
        if substitute is None:
            continue
        substitute_id = effective_character_id(substitute)
        members.append(substitute_id)
        used.add(substitute_id)
        substitutions.append((missing_id, substitute_id))

    executable = len(members) == 3
    reason = f"第{preset.queue}队列命中{len(matched)}/3"
    if broke_two_member_core:
        reason += "，为补齐队伍拆用另一两人核心"
    if not executable:
        reason += f"，仅能组成{len(members)}人"
    return TeamPlan(
        preset=preset,
        members=tuple(members),
        matched=matched,
        substitutions=tuple(substitutions),
        complete=False,
        executable=executable,
        broke_two_member_core=broke_two_member_core,
        reason=reason,
    )
