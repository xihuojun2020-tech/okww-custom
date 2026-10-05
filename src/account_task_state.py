"""Account task projections; neither GUI navigation nor reminders execute tasks."""
from dataclasses import dataclass
from uuid import uuid4

from src.game_period import (beijing_now, completed_in_period, game_day_key, game_week_key,
                             next_daily_reset, next_weekly_reset, nightmare_checkpoint, parse_legacy_time)
from src.account_reminders import get_task_reminders, TASK_REMINDERS, manual_reminder_done


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


def task_signature(task_id, tasks):
    import hashlib
    import json
    keys = {'nightmare_nest': ('Tacet Discord Nests to Farm', 'Nightmare Settlements to Farm'),
            'world_boss': ('World Boss Material Targets',),
            'forgery': ('Forgery Material Goals', 'Which to Farm', 'Which Forgery Challenge to Farm'),
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
    from src.task.forgery_quota_plan import forgery_plan, green_units
    from src.task.forgery_quota_progress import ForgeryQuotaProgress
    from src.task.world_boss_material_plan import material_plan
    from src.task.world_boss_material_progress import WorldBossMaterialProgress
    from src.task.world_boss_materials import TARGETS_BY_ID
    from src.task.weekly_boss_plan import weekly_plan, plan_enabled
    from src.task.weekly_boss import WEEKLY_MONDAY, WEEKLY_SUNDAY
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
        cards.append(AccountTaskCard(key, title, status, detail, stamp or '', str(next_at),
                                     event.get('started_at') or '', route=route or key))

    daily_stamp = completed.get('Daily Task')
    activity = events.get('daily_activity', {})
    activity_done = (activity.get('result') == 'completed' and (activity.get('actual_points') or 0) >= 100
                     and activity.get('rewards_claimed') is True
                     and activity.get('period_id') == game_day_key(now))
    detail = ('实测活跃度：' + str(activity.get('actual_points', '未记录')) + '；宝箱' +
              ('已领取' if activity.get('rewards_claimed') else '领取待核验'))
    # Legacy full daily success is retained as a historical source, not fabricated points.
    if not activity and completed_in_period(daily_stamp, now=now):
        activity_done, detail = True, '旧每日完成记录；具体积分未记录'
    add('daily_activity', '活跃度与奖励', stamp=activity.get('finished_at') or daily_stamp,
        done=activity_done, detail=detail, next_at=next_daily_reset(now).isoformat())
    if events.get('daily_run', {}).get('period_id') == game_day_key(now) and events['daily_run'].get('result') == 'failed':
        add('daily_run', '每日流程（收尾／其他步骤）', state='attention', route='closing')

    nests = tasks.get('Tacet Discord Nests to Farm', DEFAULT_NEST_NAMES)
    nightmare = tasks.get('Nightmare Settlements to Farm', [])
    if nests or nightmare:
        stamp = completed.get(nightmare_checkpoint(tasks))
        add('nightmare_nest', '残像聚落', stamp=stamp, done=completed_in_period(stamp, now=now),
            detail=f'全部所选聚落：{len(nests) + len(nightmare)} 个', next_at=next_daily_reset(now).isoformat())

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
    if target == 'Forgery Challenge' and goals:
        done = all(earned.get(r['goal_id'], 0) >= green_units(r['need']) for r in goals)
        detail = '；'.join(f"目标{i + 1}：绿色当量 {earned.get(r['goal_id'], 0)}/{green_units(r['need'])}" for i, r in enumerate(goals))
        add('forgery', '凝素领域', done=done, detail=detail, state='attention' if quota.pending() else None)
    elif target in ('Forgery Challenge', 'Simulation Challenge', 'Tacet Suppression'):
        key, title = {'Forgery Challenge': ('forgery', '凝素领域（旧刷法）'),
                      'Simulation Challenge': ('simulation', '模拟训练'),
                      'Tacet Suppression': ('tacet', '无音区')}[target]
        stamp = completed.get(target)
        # A return alone only proves this run ended, not an exhausted lifetime goal.
        done = completed_in_period(stamp, now=now) and completed_in_period(daily_stamp, now=now)
        add(key, title, stamp=stamp, done=done, detail='今日安排已结束；长期选择保留' if done else '按账号配置使用当前体力',
            next_at=next_daily_reset(now).isoformat())
    if target == 'Forgery Challenge' and goals and all(earned.get(r['goal_id'], 0) >= green_units(r['need']) for r in goals):
        add('tacet', '无音区（凝素达标后续刷）', stamp=completed.get('Tacet Suppression'),
            done=completed_in_period(completed.get('Tacet Suppression'), now=now) and completed_in_period(daily_stamp, now=now),
            next_at=next_daily_reset(now).isoformat())

    if plan_enabled(weekly_plan(tasks)):
        weekday = (now - timedelta(hours=4)).weekday()
        key = WEEKLY_SUNDAY if weekday == 6 else WEEKLY_MONDAY
        stamp = completed.get(key)
        done = completed_in_period(stamp, weekly=True, now=now)
        sunday = next_weekly_reset(now) - timedelta(days=1)
        next_at = next_weekly_reset(now) if weekday == 6 else sunday
        outcome = service.get_progress('weekly_boss:' + identity, {})
        detail = ('周日复检' if weekday == 6 else '周一检查') + '；' + str(outcome.get('status', '尚未执行'))
        add('weekly_boss', '战歌重奏', stamp=stamp, done=done, detail=detail, next_at=next_at.isoformat(),
            state='waiting' if weekday not in (0, 6) and not done else None)
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
    if tasks.get('Merge Echo on Sunday'):
        stamp = completed.get('Merge Echo')
        add('merge_echo', '声骸合成', stamp=stamp, done=completed_in_period(stamp, weekly=True, now=now),
            next_at=(next_weekly_reset(now) - timedelta(days=1)).isoformat(),
            state='waiting' if (now - timedelta(hours=4)).weekday() != 6 and not completed_in_period(stamp, weekly=True, now=now) else None)

    marks = service.get_progress('manual_task_marks:' + identity, {})
    for key, row in get_task_reminders(profile.account).items():
        if not row['enabled']:
            continue
        if key == 'adversity_tower':
            from src.task.abyss_cycle_progress import abyss_overview
            state, detail, stamp, end = abyss_overview(service, identity, now, row.get('towers'))
            if live and live.get('profile_id') == identity and live.get('task_id') == key:
                state = 'running'
            cards.append(AccountTaskCard(key, TASK_REMINDERS[key], state, '单独启动；' + detail,
                                         stamp or '', end or '', route=key))
            continue
        mark = marks.get(key, {})
        done = manual_reminder_done(row, mark, now)
        next_at = (next_daily_reset(now).isoformat() if row['rule'] == 'day' else
                   next_weekly_reset(now).isoformat() if row['rule'] == 'week' else row.get('reset_at', ''))
        if row['rule'] == 'custom' and parse_legacy_time(next_at) <= now:
            next_at = ''
        cards.append(AccountTaskCard(key, TASK_REMINDERS[key], 'completed' if done else 'pending',
                                     '仅提醒，不自动执行', mark.get('completed_at', ''), next_at,
                                     source='手动标记', route='reminders', manual=True))
    return cards
