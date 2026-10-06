"""Named targets in the guidebook's Boss Challenge section, never weekly bosses."""
from dataclasses import dataclass
import re
from src.task.weekly_boss import compact


@dataclass(frozen=True)
class WorldBossTarget:
    key: str
    name: str
    aliases: tuple[str, ...] = ()
    farm_profile: str = 'Other'
    ordinal_hint: int = 0
    cost: int = 60  # Verified again against the claim dialog before consumption.
    health_titles: tuple[str, ...] = ()


WORLD_BOSS_TARGETS = (
    WorldBossTarget('world_puppet_calamity', '天傀劫煞'),
    WorldBossTarget('world_prison_husk', '万囚牢·朽躯'),
    WorldBossTarget('world_adam_smasher', '梦魔亚当·重锤'),
    WorldBossTarget('world_explorer', '无铭探索者', farm_profile='Nameless Explorer'),
    WorldBossTarget('world_hyvatia', '海维夏', farm_profile='Hyvatia'),
    WorldBossTarget('world_furnace', '炉芯机骸'),
    WorldBossTarget('world_lady_of_the_sea', '海之女', farm_profile='Lady of the Sea',
                    health_titles=('海之女·荣光的灰烬',)),
    WorldBossTarget('world_false_sovereign', '伪作的神王'),
    WorldBossTarget('world_fenrico', '芬莱克', farm_profile='Fenrico',
                    health_titles=('芬莱克·异海归途',)),
    WorldBossTarget('world_lioness', '荣耀狮像', ('亚狮诺索',), 'Lioness of Glory'),
    WorldBossTarget('world_dragon', '叹息古龙'),
    WorldBossTarget('world_lorelei', '罗蕾莱', ('夜之女皇',), 'Lorelei'),
    WorldBossTarget('world_sentry', '异构武装', ('加尔古耶',), 'Sentry Construct'),
    WorldBossTarget('world_fallacy', '无归的谬误', farm_profile='Fallacy of No Return'),
    WorldBossTarget('world_crownless', '无冠者'),
    WorldBossTarget('world_thundering', '朔雷之鳞'),
    WorldBossTarget('world_tempest', '云闪之鳞'),
    WorldBossTarget('world_inferno', '燎照之骑'),
    WorldBossTarget('world_feilian', '飞廉之猩'),
    WorldBossTarget('world_mourning', '哀声鸷'),
    WorldBossTarget('world_heron', '无常凶鹭'),
    WorldBossTarget('world_lampylumen', '辉萤军势'),
    WorldBossTarget('world_mech', '聚械机偶'),
)
TARGETS_BY_ID = {target.key: target for target in WORLD_BOSS_TARGETS}


def matches_target(text, target):
    value = compact(text)
    names = (target.name, *target.aliases)
    titles = {compact(name) for name in names}
    titles.update(compact(target.name + separator + alias)
                  for alias in target.aliases for separator in ('·', '・', '-'))
    return value in titles


def matches_health_title(text, target):
    value = re.sub(r'(?:[lL][vV][.．]?|等级)\s*\d{1,3}', '', compact(text))
    return matches_target(value, target) or value.replace('・', '·') in target.health_titles


def matches_health_title_boxes(boxes, target, height):
    """OCR may separate Lv., the level, and the title. Join only adjacent same-row boxes."""
    for first in boxes:
        neighbors = sorted((b for b in boxes if b.x >= first.x and
                            abs((b.y + b.height / 2) - (first.y + first.height / 2))
                            <= min(b.height, first.height) / 2), key=lambda b: b.x)
        text, right = '', first.x
        for part in neighbors:
            if part.x - right > height * .025:
                break
            text += part.name
            right = part.x + part.width
            if matches_health_title(text, target):
                return True
    return False


def material_target_button(boxes, target, height):
    """A named title and its own action on the same row; no ordinal guesses."""
    titles = [b for b in boxes if matches_target(b.name, target)]
    if not titles:
        # Some OCR engines split a Chinese title into adjacent boxes on one line.
        for first in boxes:
            neighbors = sorted((b for b in boxes if b.x >= first.x and
                                abs(b.y - first.y) <= height * .012), key=lambda b: b.x)
            text, right = '', first.x
            for part in neighbors:
                if part.x - right > height * .025:
                    break
                text += part.name
                right = part.x + part.width
                if matches_target(text, target):
                    titles.append(first)
                    break
    if len(titles) != 1:
        return None
    title = titles[0]
    buttons = [b for b in boxes if compact(b.name) in ('前往', '直接挑战', '传送')
               and b.x > title.x + title.width
               and -.01 * height <= b.y - title.y <= .065 * height]
    return buttons[0] if len(buttons) == 1 else None
