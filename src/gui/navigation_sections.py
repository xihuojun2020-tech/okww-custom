"""Pure feature ownership; legacy routes remain accepted at the UI boundary."""

GENERAL = "general"
ACCOUNTS = "accounts"
TASKS = "tasks"
ACTIVITIES = "activities"
TESTS = "tests"
SETTINGS = 'settings'
ASSISTANT = 'assistant'
TOOLS = 'tools'
COMPLETION = 'completion'

_MANIFEST = (
    (TASKS, "任务", 'scroll'),
    (ACCOUNTS, "账号", 'scroll'),
    (COMPLETION, "完成检查", 'scroll'),
    (ASSISTANT, "自动辅助", 'scroll'),
    (TOOLS, "工具", 'bottom'),
    (SETTINGS, "设置", 'bottom'),
)

TASK_CATEGORIES = ('每日执行', '每周任务', '声骸获取与整理', '活动', '扩展任务')
HELPER_CATEGORIES = ('战斗与拾取', '剧情与移动', '登录与输入', '扩展辅助')


def canonical_section(section):
    return {GENERAL: SETTINGS, ACTIVITIES: TASKS, TESTS: TOOLS}.get(section, section)


def classify_task(task):
    explicit = getattr(task, "navigation_section", None)
    if explicit:
        return canonical_section(explicit)
    group = getattr(task, "group_name", "")
    if group == "🧪 测试功能":
        return TOOLS
    if group in {"限时活动", "常驻活动"}:
        return TASKS
    return TASKS


def build_navigation_manifest(_executor=None, _config=None):
    return tuple({"route": route, "title": title, 'position': position} for route, title, position in _MANIFEST)


def task_category(task):
    if getattr(task, 'navigation_section', '') == ACTIVITIES or getattr(task, 'group_name', '') in ('限时活动', '常驻活动'):
        return '活动'
    name = type(task).__name__
    if name in ('DailyTask', 'MultiAccountDailyTask'):
        return '每日执行'
    if name in ('WeeklyBossTask', 'GardenTask', 'AutoAbyssTask'):
        return '每周任务'
    if name in ('FarmEchoTask', 'MergeEchoTask'):
        return '声骸获取与整理'
    return '扩展任务'


def helper_category(task):
    name = type(task).__name__
    if name in ('AutoCombatTask', 'AutoPickTask'):
        return '战斗与拾取'
    if name in ('AutoDialogTask', 'FastTravelTask'):
        return '剧情与移动'
    if name in ('AutoLoginTask', 'MouseResetTask'):
        return '登录与输入'
    return '扩展辅助'


__all__ = ["GENERAL", "ACCOUNTS", "TASKS", "ACTIVITIES", "TESTS",
           "SETTINGS", "ASSISTANT", "TOOLS", "COMPLETION", "TASK_CATEGORIES", "HELPER_CATEGORIES",
           "canonical_section", "task_category", "helper_category",
           "classify_task", "build_navigation_manifest"]
