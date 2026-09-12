"""Pure project, status and game-period rules, independent of production progress."""
from datetime import datetime, timedelta, timezone
from src.activity_catalog import ACTIVITIES, LEGACY_ACTIVITIES

GAME_ZONE = timezone(timedelta(hours=8))
PROJECTS = {
    'daily_activity': ('活跃度', 'day'),
    'nightmare_nest': ('残像聚落', 'day'),
    'battle_pass': ('战令', 'day'),
    'weekly_boss': ('周本', 'week'),
    'weekly_garden': ('每周乐园', 'week'),
    **{key: (title, None) for key, title in ACTIVITIES.items()},
    'adversity_tower': ('深塔', None),
    'sea_ruins': ('海墟', None),
    'matrix': ('矩阵', None),
    **{key: (title, None) for key, title in LEGACY_ACTIVITIES.items()},
}
CURRENT_PROJECTS = tuple(key for key in PROJECTS if key not in LEGACY_ACTIVITIES)
GROUPS = {'day': '每日更新', 'week': '每周更新', None: '新截图更新', 'legacy': '旧版活动记录（待归类）'}


def project_group(project):
    return 'legacy' if project in LEGACY_ACTIVITIES else PROJECTS[project][1]


TASK_PROJECTS = {
    'DailyTask': 'daily_activity', 'MultiAccountDailyTask': 'daily_activity',
    'NightmareNestTask': 'nightmare_nest', 'GardenTask': 'weekly_garden',
    'WeeklyBossTask': 'weekly_boss', 'AutoAbyssTask': 'adversity_tower',
    'PianoTeachingTask': 'piano_activity', 'SecondSolTask': 'second_sol',
}
STATUSES = {'completed': '已完成', 'partial': '部分完成', 'incomplete': '未完成',
            'unknown': '待核验', 'not_applicable': '不适用'}
SOURCES = {'automatic': '自动采集', 'manual_capture': '手动截图',
           'manual_confirmation': '手动确认', 'legacy_record': '旧完成记录'}
ASSETS = {'available': '图片已保存', 'record_only': '仅有完成记录',
          'capture_failed': '截图保存失败', 'missing': '图片文件缺失'}


def now_iso():
    return datetime.now(GAME_ZONE).isoformat()


def period_label(value, project=None):
    if not value:
        if project and PROJECTS[project][1]:
            return '周期未知 · 仅保留历史记录'
        return '新截图更新 · 保留至下一张截图'
    kind, _, day = value.partition(':')
    return {'day': '游戏日：', 'week': '游戏周起始：'}.get(kind, '周期：') + day


def period_for(project_id, when=None):
    rule = PROJECTS[project_id][1]
    when = when or datetime.now(GAME_ZONE)
    if isinstance(when, str):
        when = datetime.fromisoformat(when)
    if when.tzinfo is None:
        raise ValueError('证据时间必须包含时区')
    day = (when.astimezone(GAME_ZONE) - timedelta(hours=4)).date()
    if rule == 'day':
        return f'day:{day}'
    if rule == 'week':
        return f'week:{day - timedelta(days=day.weekday())}'
    return None


def summarize(rows):
    """Rows are newest first. A new photo never inherits an older verdict."""
    definite = [r for r in rows if r['completion_status'] != 'unknown']
    chosen = next((r for r in rows if r.get('image_path')), next(iter(definite or rows), None))
    if chosen is None:
        return None, False
    chosen = dict(chosen)
    # A same-period observation is separate from the selected photo's verdict.
    previous = next((r for r in definite if r.get('evidence_id') != chosen.get('evidence_id')), None)
    if previous and chosen.get('period_id'):
        chosen['_period_observation'] = previous
    related = [r for r in definite if r.get('evidence_id') and r.get('evidence_id') == chosen.get('evidence_id')]
    automatic = next((r for r in related if r['source'] == 'automatic'), None)
    manual = next((r for r in related if r['source'] == 'manual_confirmation'), None)
    conflict = bool(automatic and manual and automatic['completion_status'] != manual['completion_status'])
    return chosen, conflict
