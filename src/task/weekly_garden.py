"""Shared weekly garden scheduling and completion rules."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

BEIJING = timezone(timedelta(hours=8))
GARDEN_DAILY = 'daily'
GARDEN_INDEPENDENT = 'multi_account_weekly'
GARDEN_CLOSED = 'closed'
GARDEN_MODES = (GARDEN_DAILY, GARDEN_INDEPENDENT, GARDEN_CLOSED)


def garden_weekly_page(texts):
    text = ''.join(str(getattr(box, 'name', box)) for box in (texts or []))
    return '活跃行迹' in text and '周度游历' in text


def garden_current_points(texts):
    """Only for the isolated current-value region, never a whole page."""
    values = []
    for box in texts or []:
        text = str(getattr(box, 'name', box)).strip().replace(',', '')
        if re.fullmatch(r'\d{1,5}', text) and 0 <= int(text) <= 6000:
            values.append(int(text))
    return values[0] if len(values) == 1 else None


def _beijing_now(now=None):
    if now is None:
        now = datetime.now(BEIJING)
    elif not isinstance(now, datetime):
        raise TypeError('now must be a datetime')
    elif now.tzinfo is None:
        now = now.replace(tzinfo=BEIJING)
    else:
        now = now.astimezone(BEIJING)
    return now


def garden_week_key(now=None):
    """Return the Beijing game-week start (Monday 04:00) as an ISO timestamp."""
    current = _beijing_now(now)
    start = (current - timedelta(days=current.weekday())).replace(
        hour=4, minute=0, second=0, microsecond=0)
    if current < start:
        start -= timedelta(days=7)
    return start.isoformat(timespec='seconds')


def garden_completed_this_week(completed_at, now=None):
    if not completed_at:
        return False
    try:
        value = datetime.fromisoformat(str(completed_at).strip())
        if value.tzinfo is None:
            value = value.replace(tzinfo=BEIJING)
        else:
            value = value.astimezone(BEIJING)
        current = _beijing_now(now)
        return value <= current and garden_week_key(value) == garden_week_key(current)
    except (TypeError, ValueError, OverflowError):
        return False


def normalize_garden_mode(mode, legacy_check_day='无'):
    if mode in GARDEN_MODES:
        return mode
    try:
        from src.account_field_metadata import WEEKDAYS, normalize_weekday
        day = normalize_weekday(legacy_check_day)
    except (ImportError, ValueError):
        return GARDEN_CLOSED
    return GARDEN_INDEPENDENT if day in WEEKDAYS else GARDEN_CLOSED


@dataclass(frozen=True)
class GardenRunResult:
    status: str
    week_key: str
    points: int | None = None
    verified: bool = False
    evidence_ref: str | None = None
    error: str | None = None

    @property
    def done(self):
        return self.status in ('completed', 'already_completed') and self.verified


__all__ = ['BEIJING', 'GARDEN_DAILY', 'GARDEN_INDEPENDENT', 'GARDEN_CLOSED',
           'GARDEN_MODES', 'GardenRunResult', 'garden_week_key',
           'garden_completed_this_week', 'normalize_garden_mode']
