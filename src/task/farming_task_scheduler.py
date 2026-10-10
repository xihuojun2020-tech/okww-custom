"""Run instance queues through the existing daily task's production entry points."""
from src.task.farming_task_queue import (ordered_tasks, task_status, task_progress,
    instance_reader, project_task, require_resolved_claims)


def run_stamina_queue(daily, config, *, activity_ready, used_stamina):
    from src.task.WorldBossMaterialTask import WorldBossMaterialTask
    from src.task.ForgeryTask import ForgeryTask
    from src.task.TacetTask import TacetTask
    from src.task.SimulationTask import SimulationTask
    identity, service = daily._active_profile_id(), daily.integrity_service
    require_resolved_claims(config, service, identity)
    last_target = None
    for item in ordered_tasks(config):
        daily.sleep(.01)
        done, _, _, _ = task_status(item, service, identity)
        if done:
            continue
        reader = instance_reader(daily._material_plan_tasks, item)
        current = reader()
        if current.get('Which to Farm') == '无':
            continue
        key = 'farming:' + item['id']
        daily._publish_daily_stage(item['name'], '执行本账号创建的刷取任务')
        daily._overview_event(key, 'running')
        kind = item['kind']
        if kind == 'world_boss':
            result = daily.get_task_by_class(WorldBossMaterialTask).run_for_profile(
                identity, reader, daily._guard_bound_profile_identity, service,
                activity_ready=activity_ready, used_stamina=used_stamina,
                progress=task_progress(item, service, identity))
            if used_stamina is not None:
                used_stamina += result.spent
            status = 'completed' if result.status == 'complete' else result.status
        elif kind == 'forgery' and item['params']['mode'] == 'materials':
            progress = task_progress(item, service, identity)
            before = progress.earned().get(item['params']['goal']['goal_id'], 0)
            status = daily.get_task_by_class(ForgeryTask).farm_quota(
                identity, reader, service, daily._guard_bound_profile_identity,
                activity_ready=activity_ready, used_stamina=used_stamina)
            if used_stamina is not None:
                used_stamina += (progress.earned().get(item['params']['goal']['goal_id'], 0)-before) * 40 // 25
            status = 'completed' if status == 'complete' else status
            last_target = 'Forgery Challenge'
        else:
            cls, method = {'forgery': (ForgeryTask, 'farm_forgery'), 'tacet': (TacetTask, 'farm_tacet'),
                           'simulation': (SimulationTask, 'farm_simulation')}[kind]
            getattr(daily.get_task_by_class(cls), method)(daily=True, config=current,
                activity_ready=activity_ready, used_stamina=used_stamina)
            last_target = project_task(item)['Which to Farm']
            daily._overview_event(key, 'returned')
            # The unlimited task exhausts current resources; later fallback tasks wait.
            return last_target
        daily._overview_event(key, status)
    return last_target


def run_weekly_queue(daily, tasks):
    from src.task.WeeklyBossTask import WeeklyBossTask
    from src.task.weekly_boss import WeeklyBossResult, weekly_check_window, WEEKLY_AUTO, WEEKLY_TARGET
    identity, service = daily._active_profile_id(), daily.integrity_service
    require_resolved_claims(tasks, service, identity)
    window = weekly_check_window()
    queue = ordered_tasks(tasks, weekly=True)
    if not queue:
        return WeeklyBossResult(0, 0, 3, '计划未启用')
    initial, claimed, remaining = None, 0, None
    for item in queue:
        daily.sleep(.01)
        if weekly_check_window() != window:
            raise RuntimeError('周本执行跨越刷新边界，下次重新核验')
        if task_status(item, service, identity)[0]:
            continue
        reader = instance_reader(daily._weekly_plan_tasks, item)
        key = 'farming:' + item['id']
        daily._overview_event(key, 'running')
        result = daily.get_task_by_class(WeeklyBossTask).run_for_plan(identity, reader, service,
            progress=task_progress(item, service, identity), fallback=False)
        plan_finished = result.reason in ('目标已达标', '计划未启用')
        if initial is None and (result.claimed or not plan_finished):
            initial = result.initial
        claimed += result.claimed
        remaining = result.remaining
        done = task_status(item, service, identity)[0]
        daily._overview_event(key, 'completed' if done else
                              'resource_shortfall' if result.reason == '当前体力不足' else 'returned')
        if not plan_finished:
            return WeeklyBossResult(initial, claimed, remaining, result.reason)
    if weekly_check_window() != window:
        raise RuntimeError('周本执行跨越刷新边界，下次重新核验')

    def read_fallback():
        if ordered_tasks(daily._weekly_plan_tasks(), weekly=True) != queue:
            raise RuntimeError('当前周本刷取任务已删除或目标已修改，请重新启动')
        return {WEEKLY_TARGET: WEEKLY_AUTO}

    # Finite material goals do not replace the game's three weekly claims.
    # Keep fallback claims in the existing account journal, outside finite task quotas.
    result = daily.get_task_by_class(WeeklyBossTask).run_for_plan(identity, read_fallback, service)
    return WeeklyBossResult(result.initial if initial is None else initial,
                            claimed + result.claimed, result.remaining, result.reason)
