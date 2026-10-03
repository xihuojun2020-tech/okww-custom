"""Finite lifetime claim quotas, followed by the account's normal stamina task."""
import hashlib
import json
from src.task.world_boss_materials import TARGETS_BY_ID

MATERIAL_TARGETS = 'World Boss Material Targets'
MATERIAL_DISABLED = 'none'


def material_plan(tasks):
    rows = tasks.get(MATERIAL_TARGETS)
    if rows is None or rows == []:
        rows = [{'boss': MATERIAL_DISABLED, 'limit': 0} for _ in range(3)]
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError('首领材料必须保存三个优先级目标')
    seen, result = set(), []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'boss', 'limit'}:
            raise ValueError('首领材料目标必须包含boss和limit')
        boss, limit = row['boss'], row['limit']
        if not isinstance(boss, str) or boss not in (MATERIAL_DISABLED, *TARGETS_BY_ID):
            raise ValueError('首领材料目标名称无效，请重新选择')
        if type(limit) is not int or not 0 <= limit <= 9999:
            raise ValueError('首领材料累计领取上限需为0至9999整数')
        if boss != MATERIAL_DISABLED:
            if boss in seen:
                raise ValueError('三个优先级不能重复选择同一材料首领')
            seen.add(boss)
        result.append({'boss': boss, 'limit': limit})
    return result


def choose_material_target(rows, counts):
    for row in rows:
        if row['boss'] == MATERIAL_DISABLED or row['limit'] == 0:
            continue
        remaining = row['limit'] - counts.get(row['boss'], 0)
        if remaining > 0:
            return row['boss'], remaining
    return None


def material_plan_revision(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
