"""Project-wide fixed deadlines, independent of account completion and game weeks."""
import re
from datetime import datetime, timedelta, timezone

ZONE = timezone(timedelta(hours=8))
# User explicitly authorized counting from this time, rather than message timestamps.
ANCHOR = '2026-10-08T20:22:11+08:00'
REMAINING = {
    'adversity_tower': (3, 7), 'sea_ruins': (17, 7), 'matrix': (34, 7),
    'character_trial': (13, 13), 'tiangong_treasure': (17, 7),
    'dango_brawl': (33, 15), 'dream_box': (33, 7),
}
CYCLE_PROJECTS = frozenset(REMAINING)


def seed_cycles():
    start = datetime.fromisoformat(ANCHOR)
    return {key: dict(start_at=ANCHOR, end_at=(start + timedelta(days=days, hours=hours)).isoformat(),
                      source='user_countdown') for key, (days, hours) in REMAINING.items()}


def stamp(value=None):
    value = value or datetime.now(ZONE)
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        raise ValueError('证据时间必须包含时区')
    return value.astimezone(ZONE)


def cycle_for(project, when=None, cycles=None):
    cycle = (seed_cycles() if cycles is None else cycles).get(project)
    if cycle and stamp(cycle['start_at']) <= stamp(when) < stamp(cycle['end_at']):
        return cycle
    return None


def cycle_label(project, when=None, cycles=None):
    now = stamp(when)
    cycle = (seed_cycles() if cycles is None else cycles).get(project)
    if not cycle:
        return '本期有效期待确认'
    end = stamp(cycle['end_at'])
    if now >= end:
        return '上一期已结束 · 新期有效期待确认'
    seconds = max(0, int((end - now).total_seconds()))
    hours = seconds // 3600
    return f'本期结束：{end:%Y-%m-%d %H:%M}（北京时间）\n剩余：{hours // 24}天{hours % 24}小时'


def observed_end(title, text, when):
    """Only a named project with one explicit countdown can establish a new cycle."""
    compact = re.sub(r'\s+', '', text)
    if title not in compact or not re.search(r'剩[余餘]|结束|結束|Remaining|Ends', text, re.I):
        return None
    matches = re.findall(r'(\d+)\s*(?:天|[Dd]ays?)\s*(\d+)\s*(?:小时|小時|[Hh]ours?)', text)
    if len(matches) != 1:
        return None
    days, hours = map(int, matches[0])
    if hours > 23 or (days == 0 and hours == 0):
        return None
    return stamp(when) + timedelta(days=days, hours=hours)
