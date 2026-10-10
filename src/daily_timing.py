"""Observe daily task time without participating in account scheduling."""
import copy
import json
import logging
import time
from functools import wraps
from uuid import uuid4

from src.runtime.combat_api import TaskDisabledException
from src.game_period import beijing_now, game_day_key

logger = logging.getLogger(__name__)
PROCESS_SESSION = str(uuid4())


def clock():
    return beijing_now().isoformat(), time.monotonic()


def duration_text(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}'


class DailyTiming:
    def __init__(self, task, repository, started=None):
        self.task = task
        self.repository = repository
        self.started = started or clock()
        self.account_started = self.started
        self.active = None
        self.next_account = None
        self.previous_attempts = {}
        self.previous_elapsed = {}
        self.record = dict(batch_id=str(uuid4()), session=PROCESS_SESSION,
                           game_day=game_day_key(self.started[0]), mode=type(task).__name__,
                           started_at=self.started[0], finished_at=None, result='running',
                           elapsed_seconds=0, attempts=[])
        self.save()

    def save(self):
        # Recording failures must report themselves without changing task control flow.
        try:
            self.repository.save_daily_timing(copy.deepcopy(self.record))
        except Exception:
            logger.exception('每日耗时记录保存失败，原任务继续执行')
            self.task.info['耗时记录错误'] = '保存失败，请检查日志；任务流程不受影响'

    def begin_account(self, profile_id, account, phase='首次'):
        if self.active is not None and self.active['profile_id'] == profile_id:
            return
        if self.active is not None:
            self.handoff(profile_id, account, phase)
            return
        if profile_id not in self.previous_attempts:
            previous = [a for batch in self.repository.daily_timings(profile_id)
                if batch['game_day'] == self.record['game_day'] and batch['batch_id'] != self.record['batch_id']
                for a in batch['attempts'] if a['profile_id'] == profile_id]
            self.previous_attempts[profile_id] = len(previous)
            self.previous_elapsed[profile_id] = sum(a['elapsed_seconds'] for a in previous if a['finished_at'])
        number = self.previous_attempts[profile_id] + 1 + sum(
            a['profile_id'] == profile_id for a in self.record['attempts'])
        if phase == '首次' and number > 1:
            phase = '再次执行'
        stamp, _ = self.account_started
        attempt = dict(profile_id=profile_id, account=account, phase=phase,
                       attempt_number=number,
                       started_at=stamp, finished_at=None, result='running', reason='',
                       stage='切入账号', elapsed_seconds=0)
        self.record['attempts'].append(attempt)
        self.active = attempt
        self.save()
        self.publish()

    def executing(self):
        if self.active is not None:
            self.active['stage'] = '每日任务'
            self.save()

    def result(self, success, error=None):
        if self.active is not None:
            self.active.update(result='completed' if success else 'failed', reason=str(error or ''))
            self.save()

    def close_account(self, ended):
        if self.active is not None:
            self.active.update(finished_at=ended[0],
                               elapsed_seconds=round(ended[1] - self.account_started[1], 3))
            total = self.previous_elapsed[self.active['profile_id']] + sum(
                a['elapsed_seconds'] for a in self.record['attempts'] if a['profile_id'] == self.active['profile_id'])
            self.active['account_total_seconds'] = total
            self.task.log_info('每日耗时记录 ' + json.dumps(dict(
                batch_id=self.record['batch_id'], game_day=self.record['game_day'],
                account=self.active['account'], phase=self.active['phase'],
                attempt_number=self.active['attempt_number'], started_at=self.active['started_at'],
                finished_at=self.active['finished_at'], stage=self.active['stage'], reason=self.active['reason'],
                result=self.active['result'], elapsed=duration_text(self.active['elapsed_seconds']),
                total=duration_text(total)), ensure_ascii=False))
            self.active = None

    def handoff(self, profile_id, account, phase):
        self.next_account = None
        ended = clock()
        self.close_account(ended)
        self.account_started = ended
        self.begin_account(profile_id, account, phase)

    def queue_handoff(self, profile_id, account, phase):
        self.next_account = profile_id, account, phase

    def begin_handoff(self):
        if self.next_account is not None:
            target = self.next_account
            self.next_account = None
            self.handoff(*target)

    def finish(self, error=None):
        ended = clock()
        if error is not None and self.active is not None:
            self.active['end_reason'] = str(error)
            if self.active['result'] != 'failed':
                self.active.update(result='stopped' if isinstance(error, TaskDisabledException) else 'failed',
                                   reason=str(error))
        self.close_account(ended)
        result = ('stopped' if isinstance(error, TaskDisabledException) else 'failed') if error else 'completed'
        if not error and any(a['result'] == 'failed' and not any(
                b['profile_id'] == a['profile_id'] and b['result'] == 'completed'
                for b in self.record['attempts']) for a in self.record['attempts']):
            result = 'partial_failure'
        self.record.update(finished_at=ended[0], result=result,
                           elapsed_seconds=round(ended[1] - self.started[1], 3))
        self.save()
        self.publish()
        self.task.log_info(f'每日耗时记录 本轮总耗时={duration_text(self.record["elapsed_seconds"])}，结果={result}')

    def publish(self):
        now = clock()[1]
        self.task.info['每日耗时记录'] = [
            f'{a["account"]} 第{a["attempt_number"]}次 · {a["phase"]} '
            f'{duration_text(now - self.account_started[1] if a is self.active else a["elapsed_seconds"])} '
            f'{a["result"]}'
            for a in self.record['attempts']]
        self.task.info['本轮总耗时'] = duration_text(
            now - self.started[1] if self.record['finished_at'] is None else self.record['elapsed_seconds'])


def note_requested_start(task):
    if type(task).__name__ in ('DailyTask', 'MultiAccountDailyTask'):
        task._daily_timing_requested = clock()


def observe(task, action, *args):
    timer = task.__dict__.get('_daily_timer')
    if timer is None:
        return
    try:
        getattr(timer, action)(*args)
    except Exception:
        logger.exception('每日耗时观察失败，原任务继续执行')


def observe_account(task, account, *, handoff=False):
    if task.__dict__.get('_daily_timer') is None:
        return
    try:
        identity = task._profile_id_for(account)
        from src.task.MultiAccountDailyTask import profile_status_label
        phase = '补跑' if task.__dict__.get('_retry_phase', False) else '首次'
        observe(task, 'queue_handoff' if handoff else 'begin_account', identity, profile_status_label(account), phase)
    except Exception:
        logger.exception('每日耗时账号关联失败，原任务继续执行')


def record_daily_duration(function):
    @wraps(function)
    def run(task, *args, **kwargs):
        executor = task.executor
        kind = type(task).__name__
        overrides = getattr(task, '_runtime_overrides', None) or {}
        if (kind not in ('DailyTask', 'MultiAccountDailyTask')
                or executor.__dict__.get('_daily_timing_owner') is not None
                or overrides.get('_weekly_boss_only') or overrides.get('_world_boss_material_only')):
            return function(task, *args, **kwargs)
        timer = None
        error = None
        try:
            from src.evidence.service import get_evidence_service
            timer = DailyTiming(task, get_evidence_service().repository,
                                task.__dict__.pop('_daily_timing_requested', None))
            task._daily_timer = timer
            executor._daily_timing_owner = task
        except Exception:
            logger.exception('每日耗时记录启动失败，原任务继续执行')
        try:
            return function(task, *args, **kwargs)
        except BaseException as caught:
            error = caught
            raise
        finally:
            if timer is not None:
                observe(task, 'finish', error)
                task._daily_timer = None
                executor._daily_timing_owner = None
    return run
