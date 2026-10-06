"""Per-account material targets with inventory snapshots and legacy additional goals."""
import copy
from uuid import UUID, uuid4

FORGERY_GOALS = 'Forgery Material Goals'
FORGERY_MODE = 'Forgery Limit Mode'
TIERS = {'gold': 27, 'purple': 9, 'blue': 3, 'green': 1}


def green_units(need):
    if not isinstance(need, dict) or set(need) != set(TIERS):
        raise ValueError('凝素需求必须包含金、紫、蓝、绿四种数量')
    if any(type(n) is not int or not 0 <= n <= 999999 for n in need.values()):
        raise ValueError('凝素需求请输入非负整数')
    return sum(need[tier] * weight for tier, weight in TIERS.items())


def forgery_plan(tasks):
    rows = tasks.get(FORGERY_GOALS, [])
    if not isinstance(rows, list) or len(rows) > 2:
        raise ValueError('凝素目标最多两组')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) not in ({'goal_id', 'domain', 'need'}, {'goal_id', 'domain', 'need', 'inventory'}):
            raise ValueError('凝素目标格式无效')
        try:
            if str(UUID(row['goal_id'])) != row['goal_id'] or row['goal_id'] in seen:
                raise ValueError()
        except (TypeError, ValueError, AttributeError):
            raise ValueError('凝素目标轮次标识无效或重复') from None
        seen.add(row['goal_id'])
        if type(row['domain']) is not int or not 1 <= row['domain'] <= 20:
            raise ValueError('请选择有效的凝素领域')
        green_units(row['need'])
        if 'inventory' in row:
            green_units(row['inventory'])
    mode = tasks.get(FORGERY_MODE)
    if mode is not None and mode not in ('unlimited', 'materials'):
        raise ValueError('凝素上限模式无效')
    if mode == 'materials' and not rows and tasks.get('Which to Farm', 'Forgery Challenge') == 'Forgery Challenge':
        raise ValueError('按材料需求刷取需要设置至少一个领域目标')
    domains = [row['domain'] for row in rows]
    if any('inventory' in row and domains.count(row['domain']) > 1 for row in rows):
        raise ValueError('同一领域请合并为一个材料目标，避免库存重复计算')
    return copy.deepcopy(rows)


def forgery_limited(tasks):
    rows = forgery_plan(tasks)
    return (tasks.get(FORGERY_MODE) or ('materials' if rows else 'unlimited')) == 'materials'


def goal_units(row):
    """Old goals retain their additional-demand meaning; new goals have a snapshot."""
    return max(0, green_units(row['need']) - green_units(row['inventory'])) if 'inventory' in row else green_units(row['need'])


def claim_estimate(remaining):
    double, rest = divmod(max(0, remaining), 50)
    single = (rest + 24) // 25
    return double, single, double * 80 + single * 40


def claim_width(remaining_units, current_stamina):
    if remaining_units >= 50 and current_stamina >= 80:
        return 2
    return 1 if remaining_units > 0 and current_stamina >= 40 else 0


def next_forgery_goal(rows, earned):
    for row in rows:
        remaining = goal_units(row) - earned.get(row['goal_id'], 0)
        if remaining > 0:
            return row, remaining
    return None


def next_forgery_claim(rows, earned, current_stamina):
    choice = next_forgery_goal(rows, earned)
    if choice and (width := claim_width(choice[1], current_stamina)):
        return choice[0]['domain'], width
    return None


def fresh_forgery_goals(rows):
    result = copy.deepcopy(rows)
    for row in result:
        row['goal_id'] = str(uuid4())
    return result
