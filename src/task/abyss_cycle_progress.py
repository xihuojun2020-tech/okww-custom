"""Per-account tower/floor journal with observed countdown intervals."""
import hashlib
import json
import re
from datetime import timedelta
from uuid import uuid4

from src.game_period import beijing_now, parse_legacy_time


def countdown_interval(text, now=None):
    text = str(text)
    if not re.search(r'剩[余餘]|结束|結束|Remaining|Ends', text, re.I):
        return None
    match = re.search(r'(\d+)\s*(?:天|[Dd]ays?)\s*(\d+)\s*(?:小时|小時|[Hh]ours?)', text)
    if not match:
        return None
    days, hours = map(int, match.groups())
    if days > 31 or hours > 23:
        return None
    end = beijing_now(now) + timedelta(days=days, hours=hours)
    return end, end + timedelta(hours=1)


def team_key(plan):
    return hashlib.sha256(json.dumps(sorted(plan.members), ensure_ascii=False).encode()).hexdigest()[:24]


class AbyssCycleProgress:
    def __init__(self, service, profile_id, *, guard=lambda: None, run_id=None):
        service.get_profile_completions(profile_id)
        self.service, self.profile_id, self.guard = service, profile_id, guard
        self.key = 'abyss_cycles:' + profile_id
        self.run_id = run_id or str(uuid4())
        self.cycle_id = None
        self.session = {'floors': {}}

    def read(self):
        value = self.service.get_progress(self.key, {'cycles': {}, 'current': None})
        if not isinstance(value, dict) or not isinstance(value.get('cycles'), dict):
            raise ValueError('深塔赛期记录无法读取')
        return value

    def observe_cycle(self, text, now=None):
        interval = countdown_interval(text, now)
        if interval is None:
            self.cycle_id = None
            return False
        lower, upper = interval
        self.guard()
        def update(value):
            value = value or {'cycles': {}, 'current': None}
            previous = value['cycles'].get(value.get('current'), {})
            old_lower, old_upper = parse_legacy_time(previous.get('end_lower')), parse_legacy_time(previous.get('end_at'))
            overlaps = old_lower and old_upper and max(lower, old_lower) < min(upper, old_upper)
            identity = value['current'] if overlaps else str(uuid4())
            if overlaps:
                low, high = max(lower, old_lower), min(upper, old_upper)
            else:
                low, high = lower, upper
            cycle = value['cycles'].setdefault(identity, {'floors': {}})
            cycle.update(end_lower=low.isoformat(), end_at=high.isoformat(), observed_at=beijing_now(now).isoformat())
            value['current'] = identity
            self.cycle_id = identity
            return value
        self.service.update_progress(self.key, update)
        return True

    def current(self):
        return self.read()['cycles'].get(self.cycle_id, {}) if self.cycle_id else self.session

    def floor(self, tower, index):
        return self.current().get('floors', {}).get(f'{tower}:{index}', {})

    def failed_teams(self, tower, index):
        row = self.floor(tower, index)
        return set(row.get('failed_teams', [])) if row.get('verified') or row.get('run_id') == self.run_id else set()

    def write_floor(self, tower, index, status, *, plan=None, reason='', roster_revision=None):
        self.guard()
        key = f'{tower}:{index}'
        def apply(cycle):
            previous = dict(cycle.setdefault('floors', {}).get(key, {}))
            if previous.get('status') == 'completed' and previous.get('verified') and status != 'completed':
                previous.update(conflict=True, reason=reason or '游戏扫描与既有通关记录冲突，待核验')
                cycle['floors'][key] = previous
                return
            failures = list(previous.get('failed_teams', [])) if previous.get('verified') or previous.get('run_id') == self.run_id else []
            if plan is not None and status == 'failed' and team_key(plan) not in failures:
                failures.append(team_key(plan))
            previous.update(status=status, failed_teams=failures, reason=reason,
                            updated_at=beijing_now().isoformat(), run_id=self.run_id, verified=False, conflict=False)
            if roster_revision:
                previous['roster_revision'] = roster_revision
            cycle['floors'][key] = previous
        if self.cycle_id:
            def update(value):
                apply(value['cycles'][self.cycle_id])
                return value
            self.service.update_progress(self.key, update)
        else:
            apply(self.session)
            self.service.set_progress('abyss_observation:' + self.profile_id, self.session)

    def verify_run(self, verified):
        if not self.cycle_id:
            for row in self.session['floors'].values():
                row['verified'] = bool(verified)
            self.service.set_progress('abyss_observation:' + self.profile_id, self.session)
            return
        self.guard()
        def update(value):
            for row in value['cycles'][self.cycle_id]['floors'].values():
                if row.get('run_id') == self.run_id:
                    row['verified'] = bool(verified)
            return value
        self.service.update_progress(self.key, update)


def abyss_overview(service, profile_id, now=None, towers=None):
    value = service.get_progress('abyss_cycles:' + profile_id, {})
    cycle = value.get('cycles', {}).get(value.get('current'), {})
    if not cycle:
        observation = service.get_progress('abyss_observation:' + profile_id, {})
        rows = observation.get('floors', {})
        done = sum(r.get('status') == 'completed' and r.get('verified') for r in rows.values())
        return ('attention' if rows else 'pending',
                f'赛期待核验；最近运行核验完成 {done}/{len(rows)} 关' if rows else '尚无可确认的赛期记录', '', '')
    end_lower = parse_legacy_time(cycle.get('end_lower'))
    if not end_lower or beijing_now(now) >= end_lower:
        return 'pending', '赛期可能已刷新；单独启动后核验本期', '', ''
    rows = cycle.get('floors', {})
    if towers is not None:
        rows = {key: row for key, row in rows.items() if key.split(':')[0] in towers}
    done = [row for row in rows.values() if row.get('status') == 'completed' and row.get('verified') and not row.get('conflict')]
    blocked = [f'{key.split(":")[0]}第{int(key.split(":")[1]) + 1}关：{row.get("reason") or "本期受阻"}'
               for key, row in rows.items() if row.get('status') == 'blocked' and row.get('verified')]
    uncertain = any(not row.get('verified') or row.get('status') == 'unknown' or row.get('conflict') for row in rows.values())
    detail = f'已核验完成 {len(done)}/{len(rows)} 关'
    if blocked:
        detail += '；' + '；'.join(blocked)
    if uncertain:
        detail += '；有结果待核验'
    status = 'completed' if rows and len(done) == len(rows) else 'attention' if blocked or uncertain else 'pending'
    stamp = max((row.get('updated_at', '') for row in done), default='')
    return status, detail, stamp, cycle.get('end_at', '')


def reset_abyss_failures(service, profile_id):
    """Explicit user re-evaluation; confirmed clears and old failure evidence remain."""
    service.get_profile_completions(profile_id)
    def update(value):
        if not value:
            return {'cycles': {}, 'current': None}
        cycle = value['cycles'].get(value.get('current'), {})
        for row in cycle.get('floors', {}).values():
            if row.get('status') == 'completed' and row.get('verified'):
                continue
            if row.get('failed_teams'):
                row.setdefault('failure_history', []).append({
                    'teams': row['failed_teams'], 'reason': row.get('reason'), 'reset_at': beijing_now().isoformat()})
            row.update(failed_teams=[], status='available', reason='用户要求重新评估', verified=True)
        return value
    return service.update_progress('abyss_cycles:' + profile_id, update)
