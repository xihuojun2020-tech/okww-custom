"""Per-account farming instances; reuse validated production plans and claim journals."""
from copy import deepcopy
from uuid import UUID, uuid4

from src.task.world_boss_material_plan import MATERIAL_TARGETS, material_plan
from src.task.weekly_boss_plan import WEEKLY_PLAN, weekly_plan
from src.task.weekly_boss import WEEKLY_AUTO
from src.task.forgery_quota_plan import (FORGERY_GOALS, FORGERY_MODE, forgery_plan,
                                        forgery_limited, goal_units)
from src.task.tacet_targets import TACET_IDS

FARMING_TASKS = 'Farming Tasks'
KINDS = {'weekly': '战歌重奏', 'world_boss': '讨伐强敌', 'forgery': '凝素领域',
         'tacet': '无音区', 'simulation': '模拟领域'}
LEGACY_FARM_FIELDS = {WEEKLY_PLAN, MATERIAL_TARGETS, FORGERY_GOALS, FORGERY_MODE,
                      'Weekly Boss Target', 'Which to Farm', 'Which Forgery Challenge to Farm',
                      'Which Tacet Suppression to Farm', 'Material Selection'}


def new_task(kind, params, name=''):
    return dict(id=str(uuid4()), kind=kind, name=name or KINDS[kind], enabled=True, params=deepcopy(params))


def project_task(item):
    """One instance becomes an existing production plan, never a new combat path."""
    kind, params = item['kind'], item['params']
    disabled = not item['enabled']
    if kind == 'world_boss':
        row = dict(params, limit=0 if disabled else params['limit'])
        return {MATERIAL_TARGETS: [row, {'boss': 'none', 'limit': 0}, {'boss': 'none', 'limit': 0}]}
    if kind == 'weekly':
        row = dict(params, limit=0 if disabled else params['limit'])
        return {WEEKLY_PLAN: [row, {'boss': '无', 'limit': 0}, {'boss': '无', 'limit': 0}]}
    if kind == 'forgery':
        return {'Which to Farm': '无' if disabled else 'Forgery Challenge',
                'Which Forgery Challenge to Farm': params['domain'], FORGERY_MODE: params['mode'],
                FORGERY_GOALS: [deepcopy(params['goal'])] if params['mode'] == 'materials' else []}
    if kind == 'tacet':
        return {'Which to Farm': '无' if disabled else 'Tacet Suppression',
                'Which Tacet Suppression to Farm': params['target']}
    return {'Which to Farm': '无' if disabled else 'Simulation Challenge', 'Material Selection': params['target']}


def farming_tasks(tasks):
    rows = tasks.get(FARMING_TASKS, [])
    if not isinstance(rows, list):
        raise ValueError('刷取任务必须为列表')
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or not {'id', 'kind', 'name', 'enabled', 'params'} <= row.keys()
                or row.keys() - {'id', 'kind', 'name', 'enabled', 'params', 'legacy_progress'}):
            raise ValueError('刷取任务格式无效')
        try:
            if str(UUID(row['id'])) != row['id'] or row['id'] in seen:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValueError('刷取任务标识无效或重复') from None
        seen.add(row['id'])
        if (not isinstance(row['kind'], str) or row['kind'] not in KINDS or not isinstance(row['name'], str) or not row['name'].strip()
                or type(row['enabled']) is not bool or not isinstance(row['params'], dict)):
            raise ValueError('刷取任务类型、名称或启用状态无效')
        kind, params = row['kind'], row['params']
        if 'legacy_progress' in row and (row['legacy_progress'] is not True or kind not in ('weekly', 'world_boss')):
            raise ValueError('旧领取进度引用无效')
        expected = ({'boss', 'limit'} if kind in ('weekly', 'world_boss') else
                    {'mode', 'domain', 'goal'} if kind == 'forgery' and params.get('mode') == 'materials' else
                    {'mode', 'domain'} if kind == 'forgery' else {'target'})
        if set(params) != expected:
            raise ValueError('刷取任务参数无效')
        projected = project_task(dict(row, enabled=True))
        if kind == 'world_boss':
            material_plan(projected)
            if params['boss'] == 'none' or params['limit'] <= 0:
                raise ValueError('突破任务请选择首领和至少一次领取')
        elif kind == 'weekly':
            weekly_plan(projected)
            if params['boss'] == '无' or params['limit'] == 0:
                raise ValueError('周本任务请选择目标和领取次数，或不限')
        elif kind == 'forgery':
            forgery_plan(projected)
            if type(params['domain']) is not int or not 1 <= params['domain'] <= 20:
                raise ValueError('请选择有效的凝素领域')
            if params['mode'] == 'materials' and params['goal']['domain'] != params['domain']:
                raise ValueError('凝素关卡与材料目标不一致')
        elif kind == 'tacet':
            if type(params['target']) is not int or params['target'] not in TACET_IDS:
                raise ValueError('请选择有效的无音区')
        elif params['target'] not in ('Resonator EXP', 'Weapon EXP', 'Shell Credit'):
            raise ValueError('请选择有效的模拟领域材料')
    # A migrated account may share its old journal across DIFFERENT targets only.
    legacy = [(r['kind'], r['params']['boss']) for r in rows if r.get('legacy_progress')]
    if len(legacy) != len(set(legacy)):
        raise ValueError('迁移任务不能重复引用同一旧进度')
    goals = [r['params']['goal']['goal_id'] for r in rows
             if r['kind'] == 'forgery' and r['params']['mode'] == 'materials']
    if len(goals) != len(set(goals)):
        raise ValueError('凝素任务不能共享同一材料进度')
    return deepcopy(rows)


def migrate_farming_tasks(tasks):
    if FARMING_TASKS in tasks:
        farming_tasks(tasks)
        return
    rows = []
    for kind, plan in (('weekly', weekly_plan(tasks)), ('world_boss', material_plan(tasks))):
        for row in plan:
            if row['boss'] in ('无', 'none') or row['limit'] == 0:
                continue
            item = new_task(kind, row)
            item['legacy_progress'] = True
            rows.append(item)
    target = tasks.get('Which to Farm', 'Tacet Suppression')
    if target == 'Forgery Challenge':
        if forgery_limited(tasks):
            for goal in forgery_plan(tasks):
                rows.append(new_task('forgery', dict(mode='materials', domain=goal['domain'], goal=goal)))
            rows.append(new_task('tacet', dict(target=tasks.get('Which Tacet Suppression to Farm', 1)), '无音区保底'))
        else:
            rows.append(new_task('forgery', dict(mode='unlimited', domain=tasks.get('Which Forgery Challenge to Farm', 1))))
    elif target == 'Tacet Suppression':
        rows.append(new_task('tacet', dict(target=tasks.get('Which Tacet Suppression to Farm', 1)), '无音区保底'))
    elif target == 'Simulation Challenge':
        rows.append(new_task('simulation', dict(target=tasks.get('Material Selection', 'Shell Credit'))))
    tasks[FARMING_TASKS] = farming_tasks({FARMING_TASKS: rows})


def fresh_farming_tasks(tasks):
    result = deepcopy(tasks)
    migrate_farming_tasks(result)
    for row in result[FARMING_TASKS]:
        row['id'] = str(uuid4())
        row.pop('legacy_progress', None)
        if row['kind'] == 'forgery' and row['params']['mode'] == 'materials':
            row['params']['goal']['goal_id'] = str(uuid4())
    return result


def task_group(row):
    if row['kind'] == 'weekly':
        return 0
    if row['kind'] == 'world_boss':
        return 1
    if row['kind'] == 'forgery' and row['params']['mode'] == 'materials':
        return 2
    return 3


def ordered_tasks(tasks, *, weekly=False):
    return sorted([row for row in farming_tasks(tasks) if row['enabled'] and
                   (row['kind'] == 'weekly') == weekly],
                  key=task_order_key)


def task_order_key(row):
    return task_group(row), row['kind'] == 'weekly' and row['params']['limit'] == -1


def task_progress(row, service, profile_id):
    from src.task.world_boss_material_progress import WorldBossMaterialProgress
    from src.task.weekly_boss_progress import WeeklyBossProgress
    from src.task.forgery_quota_progress import ForgeryQuotaProgress
    cls = {'world_boss': WorldBossMaterialProgress, 'weekly': WeeklyBossProgress,
           'forgery': ForgeryQuotaProgress}.get(row['kind'])
    if cls is None:
        return None
    journal = cls(service, profile_id)
    if row['kind'] != 'forgery' and not row.get('legacy_progress'):
        journal.key += ':' + row['id']
    return journal


def task_status(row, service=None, profile_id=None):
    journal = task_progress(row, service, profile_id) if service and profile_id else None
    params = row['params']
    stamp = ''
    done = False
    if row['kind'] in ('weekly', 'world_boss'):
        counts = journal.counts() if journal else {}
        count = sum(counts.values()) if params['boss'] == WEEKLY_AUTO else counts.get(params['boss'], 0)
        done = params['limit'] > 0 and count >= params['limit']
        detail = f'已领取 {count} / ' + ('不限' if params['limit'] == -1 else f'{params["limit"]} 次')
    elif row['kind'] == 'forgery' and params['mode'] == 'materials':
        goal = params['goal']
        count = journal.earned().get(goal['goal_id'], 0) if journal else 0
        total = goal_units(goal)
        done = count >= total
        detail = f'绿色当量 {count} / {total} · 尚缺 {max(0, total-count)}'
    else:
        detail = '不限 · 有限任务结束后执行'
    pending = bool(journal and journal.pending())
    if done and journal:
        events = journal.read()['events'].values()
        stamps = [e.get('resolved_at', e.get('time', '')) for e in events if e['state'] == 'confirmed'
                  and (e.get('boss') == params.get('boss') if row['kind'] != 'forgery'
                       else e.get('goal_id') == params['goal']['goal_id'])]
        if row['kind'] != 'forgery':
            stamps.extend(c['time'] for c in journal.read().get('corrections', [])
                          if c['boss'] == params['boss'])
        stamp = max(stamps, default='')
    return done, pending, detail, stamp


def task_target_label(item):
    params = item['params']
    if item['kind'] == 'weekly':
        from src.task.weekly_boss import WEEKLY_BOSSES
        return {b.key: b.name for b in WEEKLY_BOSSES}.get(params['boss'], params['boss'])
    if item['kind'] == 'world_boss':
        from src.task.world_boss_materials import TARGETS_BY_ID
        return TARGETS_BY_ID[params['boss']].name
    if item['kind'] == 'forgery':
        from src.task.forgery_targets import FORGERY_DOMAIN_OPTIONS
        return dict(FORGERY_DOMAIN_OPTIONS)[params['domain']]
    if item['kind'] == 'tacet':
        from src.task.tacet_targets import TACET_OPTIONS
        return dict(TACET_OPTIONS)[params['target']]
    return {'Resonator EXP': '共鸣者经验', 'Weapon EXP': '武器经验', 'Shell Credit': '贝币'}[params['target']]


def instance_reader(read_tasks, item):
    def read():
        tasks = read_tasks()
        current = next((r for r in farming_tasks(tasks) if r['id'] == item['id']), None)
        if current is None or current['kind'] != item['kind'] or current['params'] != item['params']:
            raise RuntimeError('当前刷取任务已删除或目标已修改，请重新启动')
        return {**tasks, **project_task(current)}
    return read


def require_resolved_claims(tasks, service, profile_id):
    """Pending claims must remain visible/blocking, even after deleting their task."""
    from src.task.world_boss_material_progress import WorldBossMaterialProgress
    from src.task.weekly_boss_progress import WeeklyBossProgress
    from src.task.forgery_quota_progress import ForgeryQuotaProgress
    for cls in (WorldBossMaterialProgress, WeeklyBossProgress, ForgeryQuotaProgress):
        journal = cls(service, profile_id)
        prefix = journal.key
        for key in service.get_progress_entries(prefix):
            journal.key = key
            if journal.pending():
                raise RuntimeError('有刷取领取待核验，请在刷取任务中核对后继续；本账号消费已暂停')
