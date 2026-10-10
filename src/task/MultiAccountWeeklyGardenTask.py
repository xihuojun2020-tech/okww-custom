"""Sequence-driven weekly garden runner using the production account switcher."""

from src.runtime.combat_api import TaskDisabledException, FinishedException
from src.runtime.account_task_support import get_relative_path
from src.task.DailyTask import DailyTask
from src.task.MultiAccountDailyTask import MultiAccountDailyTask, CURRENT_SEQUENCE_MEMBERS
from src.task.weekly_garden import (GARDEN_CLOSED, GARDEN_DAILY, GARDEN_INDEPENDENT,
                                    garden_completed_this_week, garden_week_key)
from src.config_integrity import ConfigIntegrityBlocked, ConfigWriteBlocked

class MultiAccountWeeklyGardenTask(MultiAccountDailyTask):
    """Reuse account selection/login/recovery while replacing only per-account work."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '👥 多账号每周乐园'
        self.description = '按当前序列逐账号检查并完成本周乐园，和每日入口共享完成记录。'
        self._garden_week_key = None
        self._garden_progress_file = get_relative_path('configs', 'multi_account_garden_progress.json')

    def _progress_namespace(self):
        return 'multi_account_garden'

    def _progress_period(self):
        return self._garden_week_key or garden_week_key()

    def _current_progress_period(self):
        return garden_week_key()

    def _completion_key(self):
        return 'Weekly Garden'

    def _progress_path(self):
        return self._garden_progress_file

    def run(self):
        self._garden_week_key = garden_week_key()
        super().run()

    def _garden_mode(self, account):
        profile = (self._load_profiles().get(account) or {})
        tasks = profile.get('task_config', profile)
        return tasks.get('Garden Execution Mode', GARDEN_CLOSED)

    def get_readonly_config_value(self, key):
        if key != CURRENT_SEQUENCE_MEMBERS:
            return super().get_readonly_config_value(key)
        accounts = self.get_sequence_accounts()
        if not accounts:
            return ['该序列暂无账号']
        labels = []
        for account in accounts:
            mode = self._garden_mode(account)
            mode_label = {GARDEN_DAILY: '随每日执行', GARDEN_INDEPENDENT: '跟随多账号每周乐园',
                          GARDEN_CLOSED: '关闭'}.get(mode, '待检查设置')
            if mode == GARDEN_CLOSED:
                state = '已关闭'
            elif self._garden_done(account):
                state = '本周已完成'
            elif self._is_failed(account):
                state = '失败待补跑'
            else:
                state = '待执行'
            labels.append(f'{self._status_label(account)} · {mode_label} · {state}')
        return labels

    def _garden_done(self, account):
        identity = self._profile_id_for(account)
        if self.integrity_service is not None:
            completion = self.integrity_service.get_completion(identity, 'Weekly Garden')
        else:
            profile = self._load_profiles().get(account) or {}
            completion = (profile.get('last_completed') or {}).get('Weekly Garden')
        return self._garden_mode(account) == GARDEN_CLOSED or garden_completed_this_week(completion)

    def _is_done(self, account):
        return self._garden_done(account)

    def _reconcile_failures(self, sequence):
        for account in sequence:
            key = self._failure_key(account)
            record = self.failed_accounts.get(key)
            if record and record.get('status') != 'resolved' and self._garden_done(account):
                self._resolve_failure(account)
            elif record and record.get('status') != 'resolved':
                self.done_set.discard(key)
                self.done_set.discard(account)
        self._refresh_garden_status(sequence)

    def _refresh_garden_status(self, sequence=None):
        if sequence is None:
            snapshot = getattr(self, '_active_run_snapshot', None)
            sequence = (self._snapshot_profile_names(snapshot) if snapshot is not None
                        else self.get_sequence_accounts())
        states = {}
        for account in sequence:
            label = self._status_label(account)
            if self._garden_mode(account) == GARDEN_CLOSED:
                states[label] = '已关闭'
            elif self._garden_done(account):
                states[label] = '已完成'
            elif self._is_failed(account):
                states[label] = '失败待补跑'
            else:
                states[label] = '待执行'
        self.info_set('本周进度', states)
        self.info_set('已完成数', sum(value == '已完成' for value in states.values()))
        self.info_set('待执行数', sum(value == '待执行' for value in states.values()))
        self.info_set('失败待补跑数', sum(value == '失败待补跑' for value in states.values()))
        self.info_set('已关闭数', sum(value == '已关闭' for value in states.values()))

    @staticmethod
    def _status_label(account):
        from src.task.MultiAccountDailyTask import profile_status_label
        return profile_status_label(account)

    def _next_target_account(self):
        snapshot = getattr(self, '_active_run_snapshot', None)
        sequence = self._snapshot_profile_names(snapshot) if snapshot is not None else self.get_sequence_accounts()
        self._reconcile_failures(sequence)
        return super()._next_target_account()

    def _task_label(self):
        return '每周乐园'

    def _execute_account_task(self, account):
        self._check_progress_date()
        identity = self._failure_key(account)
        self._account_attempts[identity] = self._account_attempts.get(identity, 0) + 1
        self._attempt_scope = 'weekly'
        retry = '失败补跑 1/1' if getattr(self, '_retry_phase', False) else '正常执行'
        self.info_set('执行轮次', retry)
        daily = None
        self._last_garden_result = None
        try:
            self._require_daily_profile(account)
            daily = self.get_task_by_class(DailyTask)
            result = daily.run_weekly_garden_only()
            self._last_garden_result = result
            if not result.done:
                raise RuntimeError(result.error or '乐园积分未确认完成')
            # The shared Weekly Garden completion is written by DailyTask before
            # this batch progress checkpoint, so a progress write failure is recoverable.
            self._mark_done(account)
            self._save_today_progress()
            self._resolve_failure(account)
            self._refresh_garden_status()
            self.log_info(f'账号 {self._status_label(account)} 本周乐园已确认完成')
            return True, None
        except (TaskDisabledException, FinishedException, ConfigIntegrityBlocked, ConfigWriteBlocked):
            raise
        except Exception as error:
            if daily is not None:
                try:
                    from src.task.GardenTask import GardenTask
                    garden = daily.get_task_by_class(GardenTask)
                    self._last_garden_result = getattr(garden, 'last_result', None)
                except Exception:
                    pass
            self._mark_failed(account, error)
            self.log_error(f'账号 {self._status_label(account)} 乐园失败，保留补跑记录', error)
            try:
                self.screenshot(f'multi_account_garden_{self._status_label(account)}_failed')
            except Exception:
                pass
            self._refresh_garden_status()
            return False, error

    def _mark_failed(self, account, error):
        result = getattr(self, '_last_garden_result', None)
        week_key = getattr(result, 'week_key', None) or self._progress_period()
        evidence_ref = getattr(result, 'evidence_ref', None)
        old = getattr(self, '_attempt_scope', None)
        self._attempt_scope = 'weekly'
        try:
            super()._mark_failed(account, error)
            record = self.failed_accounts.get(self._failure_key(account))
            if record is not None:
                record['week_key'] = week_key
                record['evidence_ref'] = evidence_ref
                self._save_failed_accounts()
            return record
        finally:
            self._attempt_scope = old

    def _finish_sequence(self, current_account=None):
        self._refresh_garden_status()
        states = self.info.get('本周进度', {}) if isinstance(self.info, dict) else {}
        failures = [name for name, state in states.items() if state == '失败待补跑']
        pending = [name for name, state in states.items() if state == '待执行']
        message = '多账号每周乐园批次结束'
        if failures:
            message += '；失败待补跑：' + '、'.join(failures)
        if pending:
            message += '；剩余待执行：' + '、'.join(pending)
        if current_account:
            message += f'；停留在账号 {self._status_label(current_account)}'
        self.log_info(message, notify=True)
