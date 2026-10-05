"""Shared Beijing game-day boundaries for execution, evidence and UI."""
from datetime import datetime, timedelta, timezone

GAME_ZONE = timezone(timedelta(hours=8))


def beijing_now(now=None):
    value = now or datetime.now(GAME_ZONE)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        value = value.replace(tzinfo=GAME_ZONE)
    return value.astimezone(GAME_ZONE)


def parse_legacy_time(value):
    try:
        return beijing_now(value) if value else None
    except (ValueError, TypeError, AttributeError):
        return None


def game_day_key(now=None):
    return (beijing_now(now) - timedelta(hours=4)).date().isoformat()


def game_week_key(now=None):
    day = (beijing_now(now) - timedelta(hours=4)).date()
    return (day - timedelta(days=day.weekday())).isoformat()


def next_daily_reset(now=None):
    current = beijing_now(now)
    boundary = current.replace(hour=4, minute=0, second=0, microsecond=0)
    return boundary + timedelta(days=1) if boundary <= current else boundary


def next_weekly_reset(now=None):
    start = datetime.fromisoformat(game_week_key(now)).replace(tzinfo=GAME_ZONE, hour=4)
    return start + timedelta(days=7)


def completed_in_period(value, key=None, *, weekly=False, now=None):
    stamp = parse_legacy_time(value)
    current = beijing_now(now)
    period = game_week_key if weekly else game_day_key
    return bool(stamp and stamp <= current and period(stamp) == (key or period(current)))


def nightmare_checkpoint(tasks, auto_farm=True):
    import hashlib
    import json
    from src.nightmare_nests import DEFAULT_NEST_NAMES
    intent = [bool(auto_farm), sorted(tasks.get('Tacet Discord Nests to Farm', DEFAULT_NEST_NAMES)),
              sorted(tasks.get('Nightmare Settlements to Farm', []))]
    digest = hashlib.sha256(json.dumps(intent, ensure_ascii=False).encode()).hexdigest()[:20]
    return f'daily_step_v{4 if auto_farm else 2}:nightmare:{digest}'
