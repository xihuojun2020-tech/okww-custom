"""One observation and at most one input per background task invocation."""
import time
from uuid import uuid4
from src.task.ui_transition import Observation, PageState, Policy, Transition, TransitionContextChanged, present
from src.runtime.navigation_status import publish


def advance(task, step, source, target, **options):
    try:
        return _advance(task, step, source, target, **options)
    except BaseException:
        pending = getattr(task, '_ui_tick_navigation', None)
        if pending is not None:
            pending['failed'] = True
        raise


def _advance(task, step, source, target, *, identity, action=None, timeout=18, attempts=3, initial_delay=0, retry_after=3):
    executor=task.executor
    def guard():
        executor.check_enabled()
        task._guard_account_input()
    guard()
    frame=task.require_game_frame()
    shape=frame.shape[:2]
    context=(getattr(task.hwnd,'hwnd',None),getattr(task,'_verified_profile_id',None),shape)
    epoch=getattr(executor,'_navigation_epoch',0)
    pending=getattr(task,'_ui_tick_navigation',None)
    reached=present(target(frame))
    selected=source(frame)
    available=present(selected)
    guard()
    if pending is None:
        if reached or not available:
            return False
        pending=dict(step=step,context=context,epoch=epoch,operation=uuid4().hex,
                     machine=Transition(Policy(timeout=timeout,max_attempts=attempts,retry_after=retry_after),time.monotonic()))
        task._ui_tick_navigation=pending
    machine=pending['machine']
    if pending.get('failed'):
        return False
    point=None
    if available and hasattr(selected,'center'):
        x,y=selected.center();point=(x/shape[1],y/shape[0])
    state=(PageState.UNKNOWN if reached and available else PageState.TARGET if reached
           else PageState.SOURCE if available else PageState.UNKNOWN)
    def emit(status, error=None):
        try:
            publish(pending['operation'],type(task).__name__,step,status,machine.attempts,
                    time.monotonic()-machine.started,machine.deadline-time.monotonic(),
                    max_attempts=attempts,error=error)
            stamp=(status,machine.attempts,error)
            if pending.get('logged')!=stamp:
                task.log_info(f'ui_transition id={pending["operation"]} step={step} state={status} '
                              f'attempt={machine.attempts} elapsed={time.monotonic()-machine.started:.2f} '
                              f'normalized={machine.last_point} error={error}')
                pending['logged']=stamp
        except Exception:
            pass
    try:
        key=(identity(frame) if callable(identity) else identity) if state==PageState.SOURCE else machine.identity
        if (pending['context']!=context or pending['step']!=step or
                epoch!=pending['epoch'] and getattr(executor,'_navigation_owner',None) is not task):
            raise TransitionContextChanged('后台导航操作所有权或窗口已变化')
        decision=machine.tick(Observation(state,key,point),getattr(executor,'_last_frame_time',None) or id(frame),time.monotonic())
        if decision=='act' and machine.attempts==0 and time.monotonic()-machine.started < initial_delay:
            decision='wait'
        status='已到达目标' if decision=='done' else state.value
        if decision=='act':
            guard()
            if context!=(getattr(task.hwnd,'hwnd',None),getattr(task,'_verified_profile_id',None),(task.height,task.width)):
                raise TransitionContextChanged('后台输入前上下文变化')
            machine.submitted(time.monotonic())
            if action is not None:action(selected)
            elif point is not None:task.click_relative(*point)
            else:raise TransitionContextChanged('后台导航缺少明确输入目标')
            status='等待切页'
        pending['epoch']=epoch
        emit(status)
        if decision=='done':task._ui_tick_navigation=None
        return decision in ('act','done')
    except BaseException as error:
        pending['failed']=True
        emit('停止/失败',type(error).__name__)
        raise
