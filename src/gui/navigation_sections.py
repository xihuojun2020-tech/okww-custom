"""Pure ownership rules for the five project navigation sections."""

GENERAL = "general"
ACCOUNTS = "accounts"
TASKS = "tasks"
ACTIVITIES = "activities"
TESTS = "tests"

_MANIFEST = (
    (GENERAL, "通用设置"),
    (ACCOUNTS, "账号设置"),
    (TASKS, "任务"),
    (ACTIVITIES, "活动"),
    (TESTS, "测试功能"),
)


def classify_task(task):
    explicit = getattr(task, "navigation_section", None)
    if explicit:
        return explicit
    group = getattr(task, "group_name", "")
    if group == "🧪 测试功能":
        return TESTS
    if group in {"限时活动", "常驻活动"}:
        return ACTIVITIES
    return TASKS


def build_navigation_manifest(_executor=None, _config=None):
    return tuple({"route": route, "title": title} for route, title in _MANIFEST)


__all__ = ["GENERAL", "ACCOUNTS", "TASKS", "ACTIVITIES", "TESTS",
           "classify_task", "build_navigation_manifest"]
