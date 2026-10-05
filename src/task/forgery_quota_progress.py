"""Atomic forgery claim journal in the portable per-account runtime store."""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4, UUID

LEDGER_PREFIX = 'forgery_quota_claims:'


def validate_ledger(value):
    if not isinstance(value, dict) or not isinstance(value.get('events'), dict):
        raise ValueError('凝素领奖记录无效，停止消费')
    for key, event in value['events'].items():
        if not isinstance(key, str) or not key or not isinstance(event, dict):
            raise ValueError('凝素领奖事件无效')
        try:
            UUID(event['goal_id'])
            datetime.fromisoformat(event['time'])
        except (KeyError, ValueError, TypeError, AttributeError):
            raise ValueError('凝素领奖身份或时间无效') from None
        if (type(event.get('domain')) is not int or not 1 <= event['domain'] <= 20
                or event.get('state') not in ('pending', 'confirmed', 'cancelled')
                or type(event.get('planned_cost')) is not int or event['planned_cost'] not in (40, 80)
                or not isinstance(event.get('revision'), str) or not event['revision']):
            raise ValueError('凝素领奖参数无效')
        cost = event.get('cost')
        if ((event['state'] == 'confirmed' and (type(cost) is not int or cost not in (40, 80)))
                or (event['state'] == 'cancelled' and (type(cost) is not int or cost != 0))):
            raise ValueError('凝素领奖消耗无效')
    return value


class ForgeryQuotaProgress:
    def __init__(self, service, profile_id):
        if service is None or not profile_id:
            raise ValueError('凝素目标需要已核验账号和运行状态服务')
        self.service = service
        self.key = LEDGER_PREFIX + str(profile_id)

    def read(self):
        return validate_ledger(self.service.get_progress(self.key, {'events': {}}))

    def earned(self):
        result = {}
        for event in self.read()['events'].values():
            if event['state'] == 'confirmed':
                result[event['goal_id']] = result.get(event['goal_id'], 0) + event['cost'] // 40 * 25
        return result

    def pending(self):
        return {key: event for key, event in self.read()['events'].items() if event['state'] == 'pending'}

    def _update(self, callback):
        def change(value):
            value = validate_ledger(value if value is not None else {'events': {}})
            callback(value)
            return validate_ledger(value)
        return self.service.update_progress(self.key, change)

    def begin(self, goal_id, domain, planned_cost, revision):
        event_id = str(uuid4())
        def change(value):
            if any(e['state'] == 'pending' for e in value['events'].values()):
                raise RuntimeError('凝素领奖待核验，请先在账号设置核对')
            value['events'][event_id] = dict(goal_id=goal_id, domain=domain, planned_cost=planned_cost,
                revision=revision, state='pending', time=datetime.now(timezone.utc).isoformat())
        self._update(change)
        return event_id

    def resolve(self, event_id, cost):
        if type(cost) is not int or cost not in (0, 40, 80):
            raise ValueError('请明确核对本次消耗：未领取、40或80体力')
        def change(value):
            event = value['events'][event_id]
            if event['state'] != 'pending':
                if event.get('cost') != cost:
                    raise ValueError('该领奖已核验，不能重复修改结果')
                return
            event.update(state='confirmed' if cost else 'cancelled', cost=cost,
                         resolved_at=datetime.now(timezone.utc).isoformat())
        self._update(change)


def preserve_forgery_progress(incoming, current):
    merged = incoming.setdefault('progress', {})
    for key, existing in (current.get('progress') or {}).items():
        if not key.startswith(LEDGER_PREFIX):
            continue
        validate_ledger(existing)
        if key not in merged:
            merged[key] = deepcopy(existing)
            continue
        other = validate_ledger(merged[key])
        for event_id, event in existing['events'].items():
            saved = other['events'].get(event_id)
            if saved is not None and any(saved[field] != event[field] for field in
                    ('goal_id', 'domain', 'planned_cost', 'revision', 'time')):
                raise ValueError('凝素领奖事件身份冲突，未覆盖记录')
            if saved is None or (saved['state'] == 'pending' and event['state'] != 'pending'):
                other['events'][event_id] = deepcopy(event)
            elif (event['state'] != 'pending' and saved['state'] != 'pending'
                  and (saved['state'], saved.get('cost')) != (event['state'], event.get('cost'))):
                raise ValueError('凝素领奖记录冲突，未覆盖已核验结果')
    return incoming
