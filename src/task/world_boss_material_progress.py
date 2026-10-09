"""Atomic per-account claims; reuses the portable runtime state service."""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4
from src.task.world_boss_materials import TARGETS_BY_ID

LEDGER_PREFIX = 'world_boss_material_claims:'


def validate_ledger(value):
    if not isinstance(value, dict) or not isinstance(value.get('counts'), dict) or not isinstance(value.get('events'), dict):
        raise ValueError('首领材料累计记录无效，停止领取')
    if any(boss not in TARGETS_BY_ID or type(count) is not int or count < 0
           for boss, count in value['counts'].items()):
        raise ValueError('首领材料累计次数无效')
    for event_id, event in value['events'].items():
        if (not isinstance(event, dict) or event.get('boss') not in TARGETS_BY_ID
                or not isinstance(event_id, str) or not event_id
                or event.get('state') not in ('pending', 'confirmed', 'cancelled')
                or type(event.get('cost')) is not int or not 0 < event['cost'] <= 240
                or type(event.get('count_before')) is not int or event['count_before'] < 0
                or not isinstance(event.get('revision'), str) or not event['revision']
                or not isinstance(event.get('time'), str)):
            raise ValueError('首领材料领奖事件无效')
        try:
            datetime.fromisoformat(event['time'])
        except ValueError:
            raise ValueError('首领材料领奖事件时间无效') from None
    return value


class WorldBossMaterialProgress:
    def __init__(self, service, profile_id):
        if service is None or not profile_id:
            raise ValueError('首领材料需要已核验账号及运行状态服务')
        self.service, self.profile_id = service, str(profile_id)
        self.key = LEDGER_PREFIX + self.profile_id

    def read(self):
        return validate_ledger(self.service.get_progress(self.key, {'counts': {}, 'events': {}}))

    def counts(self):
        return dict(self.read()['counts'])

    def pending(self):
        return {key: event for key, event in self.read()['events'].items() if event['state'] == 'pending'}

    def _update(self, callback):
        def change(value):
            value = validate_ledger(value if value is not None else {'counts': {}, 'events': {}})
            callback(value)
            return validate_ledger(value)
        return self.service.update_progress(self.key, change)

    def begin(self, boss, cost, revision):
        if (boss not in TARGETS_BY_ID or type(cost) is not int or not 0 < cost <= 240
                or not isinstance(revision, str) or not revision):
            raise ValueError('材料领奖目标或费用无效')
        event_id = str(uuid4())
        def change(value):
            if any(event['state'] == 'pending' for event in value['events'].values()):
                raise RuntimeError('有首领材料领奖待核验，请在账号设置中核对后继续')
            value['events'][event_id] = dict(boss=boss, cost=cost, revision=revision, state='pending',
                count_before=value['counts'].get(boss, 0), time=datetime.now(timezone.utc).isoformat())
        self._update(change)
        return event_id

    def resolve(self, event_id, received):
        if type(received) is not bool:
            raise ValueError('请明确确认是否已领取材料')
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

    def correct(self, boss, count):
        if boss not in TARGETS_BY_ID or type(count) is not int or not 0 <= count <= 999999:
            raise ValueError('请选择首领并输入非负累计次数')
        def change(value):
            if any(event['state'] == 'pending' for event in value['events'].values()):
                raise RuntimeError('请先核对待确认的材料领取')
            before = value['counts'].get(boss, 0)
            value['counts'][boss] = count
            value.setdefault('corrections', []).append(dict(boss=boss, before=before, after=count,
                time=datetime.now(timezone.utc).isoformat()))
        self._update(change)


class SessionMaterialProgress(WorldBossMaterialProgress):
    """Use the production claim operations without an account or disk writes."""
    def __init__(self):
        self._ledger = {'counts': {}, 'events': {}}

    def read(self):
        return deepcopy(self._ledger)

    def _update(self, callback):
        value = self.read()
        callback(value)
        self._ledger = validate_ledger(value)
        return deepcopy(self._ledger)


def preserve_material_progress(incoming, current):
    merged = incoming.setdefault('progress', {})
    for key, existing in (current.get('progress') or {}).items():
        if not key.startswith(LEDGER_PREFIX):
            continue
        validate_ledger(existing)
        other = merged.get(key)
        if other is None:
            merged[key] = deepcopy(existing)
            continue
        validate_ledger(other)
        for boss, count in existing['counts'].items():
            other['counts'][boss] = max(count, other['counts'].get(boss, 0))
        for event_id, event in existing['events'].items():
            saved = other['events'].get(event_id)
            if saved is None or (saved['state'] == 'pending' and event['state'] != 'pending'):
                other['events'][event_id] = deepcopy(event)
        corrections = other.setdefault('corrections', [])
        for correction in existing.get('corrections', []):
            if correction not in corrections:
                corrections.append(deepcopy(correction))
    return incoming
