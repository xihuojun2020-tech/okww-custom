"""Display-only account reminders and notes."""
import copy

REMINDERS = {
    'daily_activity': '活跃度',
    'weekly_boss': '周本',
    'weekly_garden': '每周乐园',
    'abyss': '深渊',
    'activities': '活动',
    'other': '其他',
}
LEGACY_REMINDER_MAP = {
    'adversity_tower': 'abyss', 'sea_ruins': 'abyss', 'matrix': 'abyss',
    'echoes_remain': 'activities', 'resonance_simulation': 'activities',
    'piano_activity': 'activities', 'second_sol': 'activities',
    'activity_1': 'activities', 'activity_2': 'activities', 'activity_3': 'activities',
    'nightmare_nest': 'other', 'battle_pass': 'other', 'character_trial': 'other',
}
NOTE_KEY = 'account_reminder_note'
NOTE_LIMIT = 2000

from src.activity_catalog import LEGACY_ACTIVITIES

TASK_REMINDERS = {'adversity_tower': '深塔（单独启动）', 'sea_ruins': '海墟',
                 'matrix': '矩阵', 'character_trial': '初露峥嵘',
                 **{key: LEGACY_ACTIVITIES[key] for key in
                    ('echoes_remain', 'resonance_simulation', 'piano_activity', 'second_sol')},
                 'other': '其他待办'}
RESET_RULES = {'none': '不自动重置', 'day': '每日 04:00', 'week': '周一 04:00', 'custom': '自定义重置时间'}
REMINDER_STATES = {'completed': '完成', 'pending': '未完成', 'blocked': '前置未完成'}


def get_task_reminders(account):
    from src.game_period import parse_legacy_time
    rows = account.get('extensions', {}).get('task_reminders', {})
    if not isinstance(rows, dict) or any(key not in TASK_REMINDERS for key in rows):
        raise ValueError('任务提醒配置无效')
    for key, row in rows.items():
        if (not isinstance(row, dict) or type(row.get('enabled')) is not bool
                or row.get('rule') not in RESET_RULES
                or (row['rule'] == 'custom' and not parse_legacy_time(row.get('reset_at')))):
            raise ValueError('任务提醒周期无效')
        if 'status' in row and row['status'] not in REMINDER_STATES:
            raise ValueError('任务提醒状态无效')
        if 'status' in row and not parse_legacy_time(row.get('marked_at')):
            raise ValueError('任务提醒标记时间无效')
        if key == 'adversity_tower' and (row.get('priority', '两侧塔优先') not in ('两侧塔优先', '中间塔优先')
                                        or not isinstance(row.get('towers', []), list)
                                        or any(t not in ('残响之塔', '深境之塔', '回音之塔') for t in row.get('towers', []))):
            raise ValueError('深塔挑战设置无效')
    return copy.deepcopy(rows)


def set_task_reminders(account, rows):
    result = copy.deepcopy(account)
    if rows or 'task_reminders' in result.get('extensions', {}):
        result.setdefault('extensions', {})['task_reminders'] = copy.deepcopy(rows)
    get_task_reminders(result)
    return result


def reminder_period(row, now=None):
    from src.game_period import game_day_key, game_week_key
    if row['rule'] == 'day':
        return 'day:' + game_day_key(now)
    if row['rule'] == 'week':
        return 'week:' + game_week_key(now)
    return row['rule'] + ':' + str(row.get('reset_at', ''))


def manual_reminder_state(row, record, now=None):
    from src.game_period import beijing_now, parse_legacy_time, game_day_key, game_week_key
    current = beijing_now(now)
    candidates = [(parse_legacy_time(value.get('marked_at') or value.get('completed_at')), value)
                  for value in (row, record) if 'status' in value or value.get('completed_at')]
    candidates = [(stamp, value) for stamp, value in candidates if stamp and stamp <= current]
    if not candidates:
        return 'pending'
    stamp, value = max(candidates, key=lambda item: item[0])
    state = value.get('status', 'pending' if value.get('revoked_at') else 'completed')
    if row['rule'] == 'day' and game_day_key(stamp) != game_day_key(current):
        return 'pending'
    if row['rule'] == 'week' and game_week_key(stamp) != game_week_key(current):
        return 'pending'
    boundary = parse_legacy_time(row.get('reset_at')) if row['rule'] == 'custom' else None
    return 'pending' if boundary and stamp < boundary <= current else state


def manual_reminder_done(row, record, now=None):
    return manual_reminder_state(row, record, now) == 'completed'


def mark_manual_reminder(service, profile_id, task_id, row, *, done=True, state=None, now=None):
    from src.game_period import beijing_now
    if task_id not in TASK_REMINDERS or not row.get('enabled'):
        raise ValueError('只有已保存的人工提醒任务可以标记完成')
    service.get_profile_completions(profile_id)  # Require a trusted, existing account.
    stamp = beijing_now(now).isoformat()
    state = state or ('completed' if done else 'pending')
    if state not in REMINDER_STATES:
        raise ValueError('任务提醒状态无效')
    def update(value):
        value = value if isinstance(value, dict) else {}
        previous = dict(value.get(task_id, {}))
        previous.update(status=state, marked_at=stamp)
        if state == 'completed':
            previous.update(completed_at=stamp, revoked_at=None, source='manual',
                            period_id=reminder_period(row, now))
        else:
            previous['revoked_at'] = stamp
        value[task_id] = previous
        return value
    return service.update_progress('manual_task_marks:' + profile_id, update)


def get_reminders(account):
    extensions = account.get('extensions', {})
    if not isinstance(extensions, dict):
        raise ValueError('账号扩展信息格式无效')
    values = extensions.get('completion_reminders', [])
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise ValueError('账号待办提醒格式无效')
    normalized = {LEGACY_REMINDER_MAP.get(item, item) for item in values}
    if any(item not in REMINDERS for item in normalized):
        raise ValueError('账号待办提醒格式无效')
    return [key for key in REMINDERS if key in normalized]


def set_reminders(account, values):
    if not isinstance(values, list):
        raise ValueError('账号待办提醒格式无效')
    if not isinstance(account.get('extensions', {}), dict):
        raise ValueError('账号扩展信息格式无效')
    result = copy.deepcopy(account)
    if not values and 'completion_reminders' not in account.get('extensions', {}):
        return result
    extensions = result.setdefault('extensions', {})
    if not isinstance(extensions, dict):
        raise ValueError('账号扩展信息格式无效')
    extensions['completion_reminders'] = copy.deepcopy(values)
    extensions['completion_reminders'] = get_reminders(result)
    return result


def get_reminder_note(account):
    extensions = account.get('extensions', {})
    if not isinstance(extensions, dict):
        raise ValueError('账号扩展信息格式无效')
    note = extensions.get(NOTE_KEY, '')
    if not isinstance(note, str) or len(note) > NOTE_LIMIT:
        raise ValueError('账号待办备注格式无效')
    return note


def set_reminder_note(account, note):
    if not isinstance(note, str) or len(note) > NOTE_LIMIT:
        raise ValueError(f'账号待办备注不能超过 {NOTE_LIMIT} 个字符')
    result = copy.deepcopy(account)
    extensions = result.setdefault('extensions', {})
    if not isinstance(extensions, dict):
        raise ValueError('账号扩展信息格式无效')
    if note or NOTE_KEY in extensions:
        extensions[NOTE_KEY] = note
    return result
