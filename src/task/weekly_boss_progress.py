"""Atomic claim journal in the existing portable account runtime state."""
from datetime import datetime, timezone
from uuid import uuid4

from src.task.weekly_boss import WEEKLY_BOSSES

LEDGER_PREFIX = 'weekly_boss_claims:'


def validate_ledger(value):
    if not isinstance(value, dict) or not isinstance(value.get('counts'), dict) or not isinstance(value.get('events'), dict):
        raise ValueError('周本累计记录无效，停止领取以免重复消耗')
    valid = {b.key for b in WEEKLY_BOSSES}
    if any(boss not in valid or type(count) is not int or count < 0 for boss, count in value['counts'].items()):
        raise ValueError('周本累计次数无效')
    for event in value['events'].values():
        if not isinstance(event, dict) or event.get('boss') not in valid or event.get('state') not in ('pending', 'confirmed', 'cancelled'):
            raise ValueError('周本领取事件无效')
    return value


def confirmed_weekly_claims(service, profile_id, week):
    """Count real claims across this account's legacy and task journals."""
    progress = WeeklyBossProgress(service, profile_id)
    confirmed = set()
    for value in service.get_progress_entries(progress.key).values():
        for event_id, event in validate_ledger(value)['events'].items():
            if event['state'] == 'pending':
                raise RuntimeError('存在未核验的周本领取，请在账号周本记录中核对后继续')
            if event['state'] == 'confirmed' and event['week'] == str(week):
                confirmed.add(event_id)
    return len(confirmed)


class WeeklyBossProgress:
    def __init__(self, service, profile_id):
        if service is None or not profile_id:
            raise ValueError('周本累计领取需要已核验账号及运行状态服务')
        self.service = service
        self.profile_id = str(profile_id)
        self.key = LEDGER_PREFIX + self.profile_id

    def read(self):
        return validate_ledger(self.service.get_progress(self.key, {'counts': {}, 'events': {}}))

    def counts(self):
        return dict(self.read()['counts'])

    def pending(self):
        return {key: event for key, event in self.read()['events'].items() if event['state'] == 'pending'}

    def _update(self, update):
        def change(value):
            value = validate_ledger(value if value is not None else {'counts': {}, 'events': {}})
            update(value)
            return validate_ledger(value)
        return self.service.update_progress(self.key, change)

    def begin(self, boss, week, remaining, revision):
        event_id = str(uuid4())
        def change(value):
            if any(e['state'] == 'pending' for e in value['events'].values()):
                raise RuntimeError('存在未核验的周本领取，请在账号周本记录中核对后继续')
            value['events'][event_id] = {'boss': boss, 'state': 'pending', 'week': str(week),
                                       'remaining_before': remaining, 'revision': revision,
                                       'time': datetime.now(timezone.utc).isoformat()}
        self._update(change)
        return event_id

    def resolve(self, event_id, received):
        def change(value):
            event = value['events'][event_id]
            if event['state'] != 'pending':
                return
            event['state'] = 'confirmed' if received else 'cancelled'
            if received:
                boss = event['boss']
                value['counts'][boss] = value['counts'].get(boss, 0) + 1
            event['resolved_at'] = datetime.now(timezone.utc).isoformat()
        self._update(change)

    def set_phase(self, event_id, phase):
        phases = ('interaction_sent', 'dialog_seen', 'confirm_sent')
        if phase not in phases:
            raise ValueError('周本领取阶段无效')
        def change(value):
            event = value['events'][event_id]
            if event['state'] != 'pending':
                return
            previous = event.get('phase')
            if previous in phases and phases.index(phase) < phases.index(previous):
                raise ValueError('周本领取阶段不能回退')
            event['phase'] = phase
        self._update(change)

    def correct(self, boss, count):
        if type(count) is not int or not 0 <= count <= 999999:
            raise ValueError('累计次数需为非负整数')
        def change(value):
            if any(e['state'] == 'pending' for e in value['events'].values()):
                raise RuntimeError('请先核对待确认领取，再校正累计次数')
            before = value['counts'].get(boss, 0)
            value['counts'][boss] = count
            value.setdefault('corrections', []).append({'boss': boss, 'before': before, 'after': count,
                                                       'time': datetime.now(timezone.utc).isoformat()})
        self._update(change)


def preserve_weekly_progress(incoming, current):
    """Restore cannot silently reduce current counters or lose pending claims."""
    merged = incoming.setdefault('progress', {})
    for key, existing in (current.get('progress') or {}).items():
        if not key.startswith(LEDGER_PREFIX):
            continue
        validate_ledger(existing)
        other = merged.get(key)
        if other is None:
            merged[key] = existing
            continue
        validate_ledger(other)
        for boss, count in existing['counts'].items():
            other['counts'][boss] = max(count, other['counts'].get(boss, 0))
        for event_id, event in existing['events'].items():
            saved = other['events'].get(event_id)
            if saved is None or (saved['state'] == 'pending' and event['state'] != 'pending'):
                other['events'][event_id] = event
    return incoming
