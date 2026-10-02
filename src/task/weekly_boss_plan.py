"""Per-account priorities; quotas count confirmed claims across weeks."""
import hashlib
import json

from src.task.weekly_boss import WEEKLY_AUTO, WEEKLY_DISABLED, WEEKLY_TARGET, WEEKLY_BOSSES

WEEKLY_PLAN = 'Weekly Boss Targets'


def weekly_plan(tasks):
    rows = tasks.get(WEEKLY_PLAN)
    if rows is None or rows == []:
        rows = [{'boss': tasks.get(WEEKLY_TARGET, WEEKLY_AUTO), 'limit': -1},
                {'boss': WEEKLY_DISABLED, 'limit': 0}, {'boss': WEEKLY_DISABLED, 'limit': 0}]
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError('周本必须保存三个优先级目标')
    valid = {WEEKLY_DISABLED, WEEKLY_AUTO, *(b.key for b in WEEKLY_BOSSES)}
    seen, result = set(), []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'boss', 'limit'}:
            raise ValueError('周本目标必须包含boss和limit')
        boss, limit = row['boss'], row['limit']
        if not isinstance(boss, str) or boss not in valid:
            raise ValueError('周本目标名称无效')
        if type(limit) is not int or not -1 <= limit <= 9999:
            raise ValueError('周本次数需为0至9999的整数；-1表示不限')
        if boss == WEEKLY_AUTO and limit not in (-1, 0):
            raise ValueError('有限次数必须选择具体周本，自动列表首项仅支持不限')
        if boss != WEEKLY_DISABLED:
            if boss in seen:
                raise ValueError('三个优先级不能重复选择同一周本')
            seen.add(boss)
        result.append({'boss': boss, 'limit': limit})
    return result


def plan_enabled(rows):
    return any(row['boss'] != WEEKLY_DISABLED and row['limit'] != 0 for row in rows)


def choose_weekly_target(rows, counts):
    if not plan_enabled(rows):
        return None
    for row in rows:
        boss, limit = row['boss'], row['limit']
        if boss == WEEKLY_DISABLED or limit == 0:
            continue
        if limit == -1:
            return boss, None, '不限'
        needed = max(0, limit - counts.get(boss, 0))
        if needed:
            return boss, needed, '优先目标'
    return WEEKLY_AUTO, None, '游戏列表首项保底'


def plan_revision(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
