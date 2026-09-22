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
