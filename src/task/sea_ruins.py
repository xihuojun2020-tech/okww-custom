"""Version-owned sea-ruins rules and deterministic whole-preset selection.

Scores are conservative preferences, not simulated damage. Unknown modes never
grant a reaction-specific bonus. No roster substitution is performed here.
"""
from dataclasses import dataclass
from datetime import date
from itertools import permutations, product
import re

SEASON_START = date(2026, 8, 31)
SEASON_END = date(2026, 9, 28)  # exclusive; AI must review a new cycle
FLOORS = {7: '险滩', 8: '涡流'}  # names verified in supplied screenshots
# User-confirmed current-cycle enemy resistances, 2026-09-22.
SEASON_RULES = {
    (7, 0): ((), ()), (7, 1): ((), ()),
    (8, 0): ((), ('热熔',)), (8, 1): ((), ('衍射',)),
    (9, 0): ((), ('气动',)), (9, 1): ((), ('气动',)),
    (10, 0): ((), ('导电',)), (10, 1): ((), ('导电',)),
    (11, 0): ((), ('衍射',)), (11, 1): ((), ('衍射',)),
}


def compact(text):
    return re.sub(r'\s+', '', str(text or '')).replace('—', '-').replace('–', '-')


@dataclass(frozen=True)
class Profile:
    element: str
    weight: float
    tags: frozenset = frozenset()
    triggers: frozenset = frozenset()


def profile(element, weight=1., tags='', triggers=''):
    return Profile(element, weight, frozenset(tags.split()), frozenset(triggers.split()))


PROFILES = {
    'char_qingxiao': profile('气动', tags='重击 共鸣解放 集谐', triggers='集谐'),
    'char_jingran': profile('热熔', tags='重击', triggers='护盾'),
    'char_hiyuki': profile('冷凝', tags='共鸣解放', triggers='霜渐 异常'),
    'yangyang_sp': profile('湮灭', tags='共鸣技能 共鸣解放', triggers='虚湮 异常'),
    'char_aemeath': profile('热熔', tags='共鸣解放'),  # mode is not visible in preset
    'char_luhesi': profile('衍射', tags='普攻'),
    'char_xigelika': profile('气动', tags='声骸技能'),
    'char_phrolova': profile('湮灭', tags='声骸技能 共鸣技能'),
    'Augusta': profile('导电', tags='重击', triggers='护盾'),
    'char_augusta': profile('导电', tags='重击', triggers='护盾'),
    'char_cartethyia': profile('气动', tags='普攻', triggers='风蚀 异常'),
    'char_carlotta': profile('冷凝', tags='共鸣技能'),
    'char_jinhsi': profile('衍射', tags='共鸣技能'),
    'char_camellya': profile('湮灭', tags='普攻'),
    'char_xiangliyao': profile('导电', tags='共鸣解放'),
    'char_jiyan': profile('气动', tags='重击'),
    'chang_changli': profile('热熔', tags='共鸣技能'),
    'char_galbrena': profile('热熔', tags='重击'),
    'char_zani': profile('衍射', tags='重击', triggers='光噪 异常'),
    'char_lucy': profile('衍射'),
    'char_encore': profile('热熔', tags='普攻'),
    'char_calcharo': profile('导电', tags='共鸣解放'),
    'char_lingyang': profile('冷凝', tags='普攻'),
    'char_danjin': profile('湮灭', .65, '重击'),
    'char_iuno': profile('气动', .55, '重击', '护盾'),
    'char_denia': profile('热熔', .4, '共鸣解放'),  # no assumed selected mode
    'char_linnai': profile('衍射', .4),
    'char_lucilla': profile('冷凝', .4),
    'char_chouyuan': profile('气动', .4, '声骸技能'),
    'char_ciaccona': profile('气动', .4, triggers='风蚀 异常'),
    'char_phoebe': profile('衍射', .5, '重击', '光噪 异常'),
    'char_roccia': profile('湮灭', .4, '重击'),
    'char_yinlin': profile('导电', .4, '共鸣技能'),
    'char_zhezhi': profile('冷凝', .4, '普攻'),
    'char_sanhua': profile('冷凝', .35, '共鸣技能'),
    'char_mortefi': profile('热熔', .35, '共鸣解放'),
    'char_lupa': profile('热熔', .4),
    'char_rebecca': profile('导电', .4),
    'char_chisa': profile('湮灭', .15, triggers='虚湮 异常'),
    'char_suisui': profile('冷凝', .1, triggers='霜渐 异常'),
    'char_moning': profile('热熔', .1),
    'char_shorekeeper': profile('衍射', .1),
    'char_verina': profile('衍射', .1),
    'char_baizhi': profile('冷凝', .1),
    'char_brant': profile('热熔', .45, triggers='护盾'),
    'char_cantarella': profile('湮灭', .2),
    'char_jianxin': profile('气动', .2, triggers='护盾'),
    'char_taoqi': profile('湮灭', .1, triggers='护盾'),
    'char_yuanwu': profile('导电', .25),
    'char_youhu': profile('冷凝', .1),
    'char_chixia': profile('热熔', .65, '共鸣技能'),
    'char_yangyang': profile('气动', .25),
    'char_aalto': profile('气动', .25),
    'char_lumi': profile('导电', .5),
    # Same portrait across Rover attributes: no element/trigger assumption.
    'char_rover': profile('未知', .65),
}


def character_profile(identity):
    """Missing specialization is not an unknown portrait or an unusable teammate."""
    if identity in PROFILES:
        return PROFILES[identity]
    from src.char.CharFactory import char_dict
    from src.char.BaseChar import CharType
    from src.task.abyss_allocation import element_for_character
    data = char_dict.get(identity)
    if data is None:
        return None
    canonical = data['canonical_name']
    if canonical in PROFILES:
        return PROFILES[canonical]
    weight = {CharType.MAIN_DPS: 1., CharType.SUB_DPS: .35, CharType.HEALER: .1}
    return profile(element_for_character(canonical) or '未知', weight.get(data.get('char_type'), .35))


@dataclass(frozen=True)
class Preset:
    number: int
    members: tuple[str, ...]

    @property
    def valid(self):
        return (len(self.members) == 3 and len(set(self.members)) == 3
                and all(character_profile(m) is not None for m in self.members))


@dataclass(frozen=True)
class Token:
    name: str
    description: str
    remaining: int | None
    locked: bool = False

    @property
    def available(self):
        return not self.locked and self.remaining is not None and (self.remaining == -1 or self.remaining > 0)


@dataclass(frozen=True)
class Loadout:
    upper: Preset
    lower: Preset
    tokens: tuple[Token, Token]
    score: float
    reasons: tuple[str, ...]


def season_rule(floor, half, today=None):
    today = today or date.today()
    if not SEASON_START <= today < SEASON_END:
        raise ValueError(f'海墟周期规则已失效：适用{SEASON_START}至{SEASON_END}之前，请更新代码规则')
    return SEASON_RULES[(floor, half)]


def team_score(team, rule, half):
    favored, resisted = rule
    profiles = [character_profile(m) for m in team.members]
    if max(p.weight for p in profiles) < .5:
        return -100.
    score = sum(p.weight * (25 * (p.element in favored) - 55 * (p.element in resisted)) for p in profiles)
    # Small opening-resource tie breaker, never stronger than resistance.
    if half == 1:
        score += 4 * sum(p.weight for p in profiles if '共鸣解放' in p.tags or '重击' in p.tags)
    else:
        score += 3 * sum(p.weight for p in profiles if '集谐' in p.tags or '普攻' in p.tags)
    return score


def token_score(team, token, floor):
    if not token.available:
        return -10000.
    ps = [character_profile(m) for m in team.members]
    total = sum(p.weight for p in ps)
    share = lambda label: sum(p.weight for p in ps if label in p.tags or label == p.element) / total
    triggers = frozenset().union(*(p.triggers for p in ps))
    name, desc = compact(token.name), compact(token.description)
    score = 0.
    if '丈量心' in name:
        score = (40 * share('集谐') + 20 * share('气动')) if '集谐' in triggers else 0
    elif '映照虚' in name or '照彻虚' in name:
        # Self shielding is relevant to the carrier; teammate shield is not assumed transferable.
        score = sum(p.weight * (30 * (p.element == '热熔') + 25 * ('重击' in p.tags))
                    for p in ps if '护盾' in p.triggers) / total
    elif '凝望深' in name or '凝视深' in name:
        score = 50 * share('冷凝') if '霜渐' in triggers else 0
    elif '镌刻者' in name:
        score = 15  # universal part only; preset portraits cannot prove rupture mode
    elif '希冀者' in name:
        score = 15 + (15 if '集谐' in triggers else 0)
    elif '编造者' in name:
        score = 15 + 25 * share('声骸技能')
    elif '慰藉者' in name:
        score = 15 + (15 if '异常' in triggers else 0)
    elif '狂欢者' in name:
        score = 25
    elif '眷属' in name:
        score = 5  # independent summon: conservative fallback, not a damage simulation
    elif '布道' in name:
        score = 20 * share('普攻')
    elif '游猎' in name:
        score = 20 * share('重击')
    elif '审判' in name and '暴击伤害' in desc:
        score = 12
    else:
        # Only simple, understood effects; do not guess unknown trigger conditions.
        simple = not any(s in desc for s in ('后', '每', '叠加', '生命低于', '状态', '层'))
        if simple:
            for tag in ('气动', '热熔', '冷凝', '衍射', '湮灭', '导电', '普攻', '重击', '共鸣技能', '共鸣解放', '声骸技能'):
                if tag in desc and '提升' in desc:
                    score = max(score, 10 * share(tag))
    if score and token.remaining != -1:
        reserve = {7: 24, 8: 20, 9: 8, 10: 0, 11: 0}[floor]
        # Protect the last use more strongly than a two-use stock; late floors
        # may spend it. Availability and the joint two-team limit still apply.
        score = max(1., score - reserve * 2 / token.remaining)
    return max(0., score)


def choose_loadout(presets, tokens, floor, today=None):
    rules = [season_rule(floor, half, today) for half in (0, 1)]
    presets = sorted((p for p in presets if p.valid), key=lambda p: p.number)
    tokens = sorted((t for t in tokens if t.available), key=lambda t: t.name)
    best = None
    for a, b in permutations(presets, 2):
        if set(a.members) & set(b.members):
            continue
        for ta, tb in product(tokens, repeat=2):
            if ta.name == tb.name and ta.remaining != -1 and ta.remaining < 2:
                continue
            sa, sb = token_score(a, ta, floor), token_score(b, tb, floor)
            # Unrecognized/unsuitable effects must not be carried simply because all scores tie.
            if sa <= 0 or sb <= 0:
                continue
            score = team_score(a, rules[0], 0) + team_score(b, rules[1], 1) + sa + sb
            candidate = Loadout(a, b, (ta, tb), score, (
                f'上半预设{a.number} 顺{rules[0][0]} 逆{rules[0][1]}；{ta.name}库存{ta.remaining}适配分{sa:.1f}',
                f'下半预设{b.number} 顺{rules[1][0]} 逆{rules[1][1]}；{tb.name}库存{tb.remaining}适配分{sb:.1f}',
            ))
            if best is None or score > best.score:
                best = candidate
    if best is None:
        raise ValueError('没有可用的两支不重人预设及信物组合；请补充预设、解锁信物或更新角色规则')
    return best


def parse_count(text):
    text = compact(text)
    if text == '∞':
        return -1
    return int(text) if re.fullmatch(r'\d{1,2}', text) else None


def scores_valid(upper, lower, total):
    return all(isinstance(x, int) and 0 <= x <= 99999 for x in (upper, lower, total)) and upper + lower == total
