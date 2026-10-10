"""Account task projections; neither GUI navigation nor reminders execute tasks."""
from dataclasses import dataclass
from uuid import uuid4

from src.game_period import (beijing_now, completed_in_period, game_day_key, game_week_key,
                             next_daily_reset, next_weekly_reset, nightmare_checkpoint, parse_legacy_time)
from src.account_reminders import get_task_reminders, TASK_REMINDERS, manual_reminder_state


@dataclass(frozen=True)
class AccountTaskCard:
    task_id: str
    title: str
    state: str
    detail: str = ''
    completed_at: str = ''
    next_at: str = ''
    started_at: str = ''
    source: str = '程序记录'
    route: str = ''
    manual: bool = False
    last_attempt_at: str = ''


def task_signature(task_id, tasks):
    import hashlib
    import json
    if task_id.startswith('farming:'):
        from src.task.farming_task_queue import farming_tasks
        row = next((row for row in farming_tasks(tasks) if 'farming:' + row['id'] == task_id), None)
        return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    keys = {'nightmare_nest': ('Tacet Discord Nests to Farm', 'Nightmare Settlements to Farm'),
            'world_boss': ('World Boss Material Targets',),
            'forgery': ('Forgery Material Goals', 'Forgery Limit Mode', 'Which to Farm', 'Which Forgery Challenge to Farm'),
            'tacet': ('Which Tacet Suppression to Farm',),
            'weekly_boss': ('Weekly Boss Targets', 'Weekly Boss Target'),
            'weekly_garden': ('Garden Execution Mode', 'Weekly Garden Check Day')}.get(task_id, ())
    return hashlib.sha256(json.dumps({key: tasks.get(key) for key in keys}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def record_task_event(task, task_id, result, **details):
    """Supplement existing authoritative checkpoints, never duplicate claim counts."""
    service = getattr(task, 'integrity_service', None)
    profile_id = getattr(task, '_verified_profile_id', None)
    if not service or not profile_id or not callable(getattr(service, 'update_progress', None)):
        return
    run_id = getattr(task, '_overview_run_id', None)
    if not run_id:
        run_id = task._overview_run_id = str(uuid4())
    stamp = beijing_now().isoformat(timespec='seconds')
    reader = getattr(task, '_readonly_profile_config', None)
    signature = None
    def update(value):
        if value is not None and not isinstance(value, dict):
            raise ValueError('任务状态记录无效')
        value = value or {}
        record = dict(value.get(task_id, {}))
        record.update(task_id=task_id, result=result, period_id=game_day_key(), run_id=run_id, **details)
        if signature:
            record['signature'] = signature
        if result == 'running':
            record.update(started_at=stamp, finished_at=None)
        else:
            record['finished_at'] = stamp
        value[task_id] = record
        return value
    try:
        signature = task_signature(task_id, reader()) if callable(reader) else None
        service.update_progress('task_state_v1:' + profile_id, update)
    except Exception as error:
        message = f'任务状态保存失败，界面结果待核验：{type(error).__name__}'
        try:
            task.log_warning(message)
        except Exception:
            import logging
            logging.getLogger(__name__).warning(message)


def build_account_task_cards(profile, service, *, now=None, live=None):
    from src.task.forgery_quota_plan import forgery_plan, forgery_limited, goal_units
    from src.task.forgery_quota_progress import ForgeryQuotaProgress
    from src.task.world_boss_material_plan import material_plan
    from src.task.world_boss_material_progress import WorldBossMaterialProgress
    from src.task.world_boss_materials import TARGETS_BY_ID
    from src.task.weekly_boss import (WEEKLY_DISABLED, weekly_account_plan,
                                      weekly_account_check_due, weekly_check_window)
    from src.nightmare_nests import DEFAULT_NEST_NAMES
    from datetime import timedelta

    now = beijing_now(now)
    identity, tasks = profile.profile_id, dict(profile.tasks)
    completed = service.get_profile_completions(identity)
    events = service.get_progress('task_state_v1:' + identity, {})
    if not isinstance(events, dict):
        raise ValueError('任务状态记录无法读取')
    cards = []
    def add(key, title, *, stamp=None, done=False, detail='', next_at='', route='', state=None):
        event = events.get(key, {})
        if event.get('signature') and event['signature'] != task_signature(key, tasks):
            event = {}
        current_event = event.get('period_id') == game_day_key(now)
        status = state or ('completed' if done else 'pending')
        if current_event and event.get('result') in ('failed', 'unconfirmed'):
            status, detail = 'attention', str(event.get('reason') or '执行结果待核验')
        elif current_event and event.get('result') == 'resource_shortfall' and not done:
            status, detail = 'waiting', '体力不足，下次手动启动继续；' + detail
        if (live and live.get('profile_id') == identity and live.get('task_id') == key
                and live.get('run_id') and event.get('run_id') == live['run_id']):
            status, detail = 'running', live.get('detail') or detail
        elif current_event and event.get('result') == 'running' and not done:
            status, detail = 'attention', '上次运行未确认结束，请核对记录'
        if key in ('world_boss', 'forgery') and not done:
            stamp = None
        cards.append(AccountTaskCard(key, title, status, detail, stamp or '', str(next_at),
                                     event.get('started_at') or '', route=route or key,
                                     last_attempt_at=event.get('finished_at') or ''))

    daily_stamp = completed.get('Daily Task')
    nests = tasks.get('Tacet Discord Nests to Farm', DEFAULT_NEST_NAMES)
    nightmare = tasks.get('Nightmare Settlements to Farm', [])
    if nests or nightmare:
        stamp = completed.get(nightmare_checkpoint(tasks))
        add('nightmare_nest', '残像聚落', stamp=stamp, done=completed_in_period(stamp, now=now),
            detail=f'全部所选聚落：{len(nests) + len(nightmare)} 个', next_at=next_daily_reset(now).isoformat())

    from src.task.farming_task_queue import FARMING_TASKS, farming_tasks, task_status, task_order_key, task_target_label
    weekday = (now - timedelta(hours=4)).weekday()
    weekly_target, _ = weekly_account_plan(tasks)
    weekly_stamp = completed.get(weekly_check_window(now)[1])
    weekly_done = (weekly_target != WEEKLY_DISABLED and
                   not weekly_account_check_due(tasks, weekly_stamp, identity, service, now))
    outcome = service.get_progress('weekly_boss:' + identity, {})
    weekly_review_at = next_weekly_reset(now) - timedelta(days=0 if weekday == 6 else 1)
    if FARMING_TASKS in tasks:
        for item in sorted(farming_tasks(tasks), key=task_order_key):
            done, pending, detail, stamp = task_status(item, service, identity)
            key = 'farming:' + item['id']
            weekly = item['kind'] == 'weekly'
            finite = (item['kind'] == 'world_boss' or
                      weekly and item['params']['limit'] > 0 or
                      item['kind'] == 'forgery' and item['params']['mode'] == 'materials')
            if not finite:
                if weekly:
                    done, stamp = weekly_done, weekly_stamp if weekly_done else None
                else:
                    event = events.get(key, {})
                    done = (event.get('result') == 'returned' and event.get('period_id') == game_day_key(now)
                            and event.get('signature') == task_signature(key, tasks)
                            and completed_in_period(daily_stamp, now=now))
                    stamp = event.get('finished_at') if done else None
            detail = task_target_label(item) + '；' + detail
            if weekly and finite and done:
                detail += '；材料目标已达标；' + ('本周领取次数耗尽' if weekly_done else '本周三次领奖仍待补检')
            state = 'attention' if pending else None
            if not item['enabled'] and not done:
                state, detail = 'waiting', '已暂停；' + detail
            elif weekly and not done and not pending:
                if weekly_done:
                    state = 'waiting'
                    detail += '；本周领取次数耗尽，下周继续'
                else:
                    detail += '；周日强制复核' if weekday == 6 else '；本周尚未完成，每日补检'
            if finite and done:
                next_at = ''
            elif weekly:
                check_at = (next_weekly_reset(now) if finite else weekly_review_at) if weekly_done else next_daily_reset(now)
                next_at = check_at.isoformat()
            else:
                next_at = '' if finite else next_daily_reset(now).isoformat()
            add(key, item['name'], done=done, stamp=stamp, detail=detail, state=state,
                next_at=next_at, route='weekly_boss' if weekly else 'stamina')
    else:
        material = material_plan(tasks)
        progress = WorldBossMaterialProgress(service, identity)
        counts = progress.counts()
        enabled = [r for r in material if r['boss'] != 'none' and r['limit'] > 0]
        if enabled or progress.pending() or events.get('world_boss', {}).get('result') == 'completed':
            done = bool(enabled) and all(counts.get(r['boss'], 0) >= r['limit'] for r in enabled)
            done |= not enabled and events.get('world_boss', {}).get('result') == 'completed'
            detail = '；'.join(f"{TARGETS_BY_ID[r['boss']].name} {counts.get(r['boss'], 0)}/{r['limit']} 次" for r in enabled)
            add('world_boss', '讨伐强敌', done=done, detail=detail or '累计目标已达标，已自动关闭',
                stamp=events.get('world_boss', {}).get('finished_at'),
                state='attention' if progress.pending() else None)
        goals = forgery_plan(tasks)
        quota = ForgeryQuotaProgress(service, identity)
        earned = quota.earned()
        target = tasks.get('Which to Farm', 'Tacet Suppression')
        if target in ('Forgery Challenge', 'Simulation Challenge', 'Tacet Suppression'):
            limited = target == 'Forgery Challenge' and forgery_limited(tasks)
            all_done = limited and all(earned.get(r['goal_id'], 0) >= goal_units(r) for r in goals)
            active = 'tacet' if all_done or target == 'Tacet Suppression' else 'forgery' if target == 'Forgery Challenge' else 'simulation'
            checkpoint = 'Tacet Suppression' if all_done else target
            stamp = completed.get(checkpoint)
            done = completed_in_period(stamp, now=now) and completed_in_period(daily_stamp, now=now)
            if limited:
                done = done and all_done
                detail = '；'.join(f"目标{i + 1}：新增当量 {earned.get(r['goal_id'], 0)}/{goal_units(r)}" for i, r in enumerate(goals))
                detail += '；凝素达标，后续刷无音区' if all_done else '；达标后转所选无音区'
            else:
                detail = {'Forgery Challenge': f'凝素不限 · 领域 {tasks.get("Which Forgery Challenge to Farm", 1)}',
                          'Tacet Suppression': f'无音区 · {tasks.get("Which Tacet Suppression to Farm", "未设置")}',
                          'Simulation Challenge': '模拟训练 · ' + str(tasks.get('Material Selection', ''))}[target]
            event = events.get(active, {})
            valid = not event.get('signature') or event['signature'] == task_signature(active, tasks)
            if not valid:
                done = False
            current = valid and event.get('period_id') == game_day_key(now)
            state = 'completed' if done else 'pending'
            if quota.pending():
                state, detail = 'attention', '凝素领取待核验；请先核对消费记录'
            elif current and event.get('result') in ('failed', 'unconfirmed', 'running') and not done:
                state = 'attention'
                detail = event.get('reason') or '上次体力刷取未确认结束，请核对记录'
            elif current and event.get('result') == 'resource_shortfall' and not done:
                state = 'waiting'
                detail += '；当前体力不足，下次手动启动继续'
            if (live and live.get('profile_id') == identity and live.get('task_id') in ('forgery', 'tacet', 'simulation')
                    and live.get('run_id') and events.get(live['task_id'], {}).get('run_id') == live['run_id']):
                state = 'running'
                detail = live.get('detail') or detail
            cards.append(AccountTaskCard('stamina', '体力刷取', state, detail, stamp if done else '',
                                         next_daily_reset(now).isoformat(), event.get('started_at') or '',
                                         route='stamina', last_attempt_at=event.get('finished_at') or ''))

        if weekly_target != WEEKLY_DISABLED:
            next_at = weekly_review_at if weekly_done else next_daily_reset(now)
            detail = ('周日强制复核' if weekday == 6 else
                      '本周已完成，周日复核' if weekly_done else '本周尚未完成，每日补检')
            detail += '；' + str(outcome.get('status', '尚未执行'))
            add('weekly_boss', '战歌重奏', stamp=weekly_stamp if weekly_done else None,
                done=weekly_done, detail=detail, next_at=next_at.isoformat())
    mode = tasks.get('Garden Execution Mode', 'closed')
    if mode != 'closed':
        stamp = completed.get('Weekly Garden')
        from src.account_field_metadata import WEEKDAYS, normalize_weekday
        check_day = normalize_weekday(tasks.get('Weekly Garden Check Day', '无'))
        start = next_weekly_reset(now) - timedelta(days=7)
        check_at = start + timedelta(days=WEEKDAYS.index(check_day)) if check_day in WEEKDAYS else now
        done = completed_in_period(stamp, weekly=True, now=now)
        add('weekly_garden', '每周乐园', stamp=stamp, done=done,
            detail='随每日执行' if mode == 'daily' else '独立多账号每周入口',
            next_at=(check_at if not done and now < check_at else next_weekly_reset(now)).isoformat(),
            state='waiting' if not done and mode == 'daily' and now < check_at else None)
    marks = service.get_progress('manual_task_marks:' + identity, {})
    for key, row in get_task_reminders(profile.account).items():
        if not row['enabled']:
            continue
        mark = marks.get(key, {})
        state = manual_reminder_state(row, mark, now)
        next_at = (next_daily_reset(now).isoformat() if row['rule'] == 'day' else
                   next_weekly_reset(now).isoformat() if row['rule'] == 'week' else row.get('reset_at', ''))
        if row['rule'] == 'custom' and parse_legacy_time(next_at) <= now:
            next_at = ''
        marked_stamps = [parse_legacy_time(value.get('marked_at') or value.get('completed_at'))
                         for value in (row, mark)]
        marked_stamps = [stamp for stamp in marked_stamps if stamp and stamp <= now]
        marked_at = max(marked_stamps).isoformat() if marked_stamps and state == 'completed' else ''
        cards.append(AccountTaskCard(key, TASK_REMINDERS[key], state,
                                     '仅提醒，不自动执行' + (' · 深塔单独启动' if key == 'adversity_tower' else ''),
                                     marked_at, next_at,
                                     source='手动标记', route='reminder:' + key, manual=True))
    return cards
