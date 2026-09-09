"""Weekly challenge names and conservative, UI-independent parsing rules."""
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class WeeklyBoss:
    key: str
    name: str


WEEKLY_BOSSES = (
    WeeklyBoss('weekly_fallen_court', '失坠困咎之庭'),
    WeeklyBoss('weekly_false_god', '虚妄诞生之种'),
    WeeklyBoss('weekly_star_gate', '星海迷途之扉'),
    WeeklyBoss('weekly_apocalypse', '烬夜天启之章'),
    WeeklyBoss('weekly_fate_wheel', '命途断章之轮'),
    WeeklyBoss('weekly_crimson_curtain', '彼世猩红之幕'),
    WeeklyBoss('weekly_temporal', '时序命定之争'),
    WeeklyBoss('weekly_crownless', '无冠巨像之心'),
    WeeklyBoss('weekly_border_flame', '无序边境之火'),
    WeeklyBoss('weekly_bell', '昔日咏叹之钟'),
)


@dataclass(frozen=True)
class WeeklyBossResult:
    initial: int
    claimed: int
    remaining: int

    @property
    def complete(self):
        return self.remaining == 0


def compact(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))


def boss_title(text):
    # Only observed typography/character variants, not fuzzy target matching.
    return re.sub(r'[·・•.]?战歌重奏$', '', compact(text)).replace('紅', '红')


def parse_remaining(text):
    match = re.fullmatch(r'本周剩余可收取次数[:：]?(\d)/3', compact(text))
    return int(match[1]) if match and int(match[1]) <= 3 else None


def parse_cost(text):
    match = re.fullmatch(r'[xX×](\d{1,3})', compact(text))
    return int(match[1]) if match and 0 < int(match[1]) <= 240 else None


def parse_stamina(text):
    match = re.fullmatch(r'(\d{1,4})/240', compact(text))
    return int(match[1]) if match else None


def combat_phase(text):
    values = [text] if isinstance(text, str) else text
    values = [compact(value).replace('「', '').replace('」', '') for value in values]
    if any(value.startswith('领取奖励') or value.startswith('离开') for value in values):
        return 'post'
    if any(value.startswith('击败') or value.startswith('与岁主角对战') for value in values):
        return 'combat'
    return None


def match_target_button(boxes, target_name, height):
    titles = [b for b in boxes if boss_title(b.name) == target_name]
    if len(titles) != 1:
        return None
    title = titles[0]
    candidates = [b for b in boxes if compact(b.name) == '直接挑战'
                  and b.x > title.x + title.width
                  and -0.01 * height <= b.y - title.y <= 0.065 * height]
    return candidates[0] if len(candidates) == 1 else None
