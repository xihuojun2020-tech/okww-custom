"""Display-only account reminders. Never consulted by task scheduling."""
import copy

REMINDERS = {
    'daily_activity': '活跃度',
    'nightmare_nest': '残像聚落',
    'weekly_boss': '周本',
    'weekly_garden': '每周乐园',
    'activity_1': '活动1',
    'activity_2': '活动2',
    'activity_3': '活动3',
}


def get_reminders(account):
    extensions = account.get('extensions', {})
    if not isinstance(extensions, dict):
        raise ValueError('账号扩展信息格式无效')
    values = extensions.get('completion_reminders', [])
    if not isinstance(values, list) or any(not isinstance(item, str) or item not in REMINDERS for item in values):
        raise ValueError('账号待办提醒格式无效')
    return [key for key in REMINDERS if key in values]


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
