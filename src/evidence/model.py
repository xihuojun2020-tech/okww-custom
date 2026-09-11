"""Pure project, status and game-period rules, independent of production progress."""
from datetime import datetime, timedelta, timezone

GAME_ZONE = timezone(timedelta(hours=8))
PROJECTS = {
    'daily_activity': ('活跃度', 'day'),
    'nightmare_nest': ('残像聚落', None),
    'weekly_garden': ('周常乐园', 'week'),
    'weekly_boss': ('周本', 'week'),
    'battle_pass': ('战令', None),
    'adversity_tower': ('深塔', None),
    'piano_activity': ('清弦纪流年', None),
    'echoes_remain': ('若梦仍有回声', None),
    'resonance_simulation': ('群声共振模拟域', None),
    'activity_1': ('活动1', None),
    'activity_2': ('活动2', None),
    'activity_3': ('活动3', None),
    'second_sol': ('第二索拉·诡影迷踪', None),
    'sea_ruins': ('海墟', None),
    'matrix': ('矩阵', None),
}
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


def period_label(value):
    if not value:
        return '周期未知，仅代表本次记录'
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
    """Newest definite result wins; uncertain photos cannot erase a known result."""
    definite = [r for r in rows if r['completion_status'] != 'unknown']
    chosen = next(iter(definite or rows), None)
    automatic = next((r for r in definite if r['source'] == 'automatic'), None)
    manual = next((r for r in definite if r['source'] == 'manual_confirmation'), None)
    conflict = bool(automatic and manual and automatic['completion_status'] != manual['completion_status'])
    return chosen, conflict
