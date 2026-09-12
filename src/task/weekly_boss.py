"""Weekly challenge names and conservative, UI-independent parsing rules."""
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from types import SimpleNamespace

WEEKLY_TARGET = 'Weekly Boss Target'
WEEKLY_AUTO = '自动（列表首项）'
WEEKLY_DISABLED = '无'
WEEKLY_MONDAY = 'Weekly Boss Monday Check'
WEEKLY_SUNDAY = 'Weekly Boss Sunday Check'


def weekly_check_window(now=None):
    # Simplified-Chinese servers reset at 04:00 UTC+8.
    now = now or datetime.now(timezone(timedelta(hours=8)))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone(timedelta(hours=8)))
    day = (now.astimezone(timezone(timedelta(hours=8))) - timedelta(hours=4)).date()
    return (day - timedelta(days=day.weekday()),
            WEEKLY_SUNDAY if day.weekday() == 6 else WEEKLY_MONDAY)


def weekly_check_due(target, completed, now=None):
    if target == WEEKLY_DISABLED:
        return False
    if target != WEEKLY_AUTO and target not in {boss.key for boss in WEEKLY_BOSSES}:
        raise ValueError('请选择有效的账号周本目标')
    if not completed:
        return True
    try:
        stamp = datetime.fromisoformat(str(completed).replace('Z', '+00:00'))
        current = now or datetime.now(timezone(timedelta(hours=8)))
        zone = timezone(timedelta(hours=8))
        stamp = stamp.replace(tzinfo=zone) if stamp.tzinfo is None else stamp
        current = current.replace(tzinfo=zone) if current.tzinfo is None else current
        if stamp > current:
            return True
        return weekly_check_window(stamp) != weekly_check_window(now)
    except (TypeError, ValueError):
        return True


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


def weekly_title_rows(boxes, height):
    """Join nearby title fragments only; never merge rewards or challenge buttons."""
    parts = sorted((b for b in boxes if b.x < height * 1.11), key=lambda b: (b.y, b.x))
    rows = []
    for part in parts:
        row = next((r for r in rows if abs(r[0].y - part.y) <= height * .012), None)
        if row is None:
            rows.append([part])
        else:
            row.append(part)
    result = []
    for row in rows:
        row.sort(key=lambda b: b.x)
        groups = [[]]
        for part in row:
            group = groups[-1]
            if group and part.x - (group[-1].x + group[-1].width) > height * .035:
                groups.append([])
            groups[-1].append(part)
        for group in groups:
            name = ''.join(b.name for b in group)
            if '战歌重奏' not in compact(name) and boss_title(name) not in {b.name for b in WEEKLY_BOSSES}:
                continue
            result.append(SimpleNamespace(name=name, x=group[0].x,
                          y=min(b.y for b in group),
                          width=max(b.x + b.width for b in group) - group[0].x,
                          height=max(b.height for b in group)))
    return sorted(result, key=lambda b: b.y)


def match_target_button(boxes, target_name, height):
    titles = [b for b in weekly_title_rows(boxes, height) if boss_title(b.name) == target_name]
    if len(titles) != 1:
        return None
    title = titles[0]
    candidates = [b for b in boxes if compact(b.name) == '直接挑战'
                  and b.x > title.x + title.width
                  and -0.01 * height <= b.y - title.y <= 0.065 * height]
    return candidates[0] if len(candidates) == 1 else None
