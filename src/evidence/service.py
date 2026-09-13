"""Bounded evidence saving and executor-owned, input-free manual capture."""
import copy
import logging
import os
import queue
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from src.evidence.model import now_iso
from src.evidence.repository import EvidenceRepository

logger = logging.getLogger(__name__)
_CURRENT_FRAME = object()


def evidence_frame(task):
    """Copy a recognized frame without letting an observer interrupt the task."""
    try:
        executor = getattr(task, 'executor', None)
        if isinstance(getattr(executor, 'completion_evidence_service', None), EvidenceService):
            frame = executor.nullable_frame()
            return frame.copy() if frame is not None else None
    except Exception:
        logger.warning('结果帧复制失败，任务继续')
    return None


class EvidenceService:
    def __init__(self, repository):
        self.repository = repository
        self._slots = threading.BoundedSemaphore(4)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='CompletionEvidence')
        self.revision = 0
        self.last_error = ''
        if callable(getattr(repository, 'recover_required', None)):
            self._pool.submit(repository.recover_required)

    def submit(self, metadata, frame, *, run=False):
        if not self._slots.acquire(blocking=False):
            self.last_error = '证据保存队列已满，未删除旧截图，请稍后重试'
            raise RuntimeError(self.last_error)
        try:
            metadata = copy.deepcopy(metadata)
            if frame is not None and frame.nbytes > 64 * 1024 * 1024:
                raise ValueError('截图过大，请检查游戏分辨率')
            frame = frame.copy() if frame is not None else None
            future = (self._pool.submit(self.repository.save_run, metadata) if run else
                      self._pool.submit(self._save, metadata, frame))
        except Exception:
            self._slots.release()
            raise

        def finished(result):
            self._slots.release()
            error = RuntimeError('保存已取消') if result.cancelled() else result.exception()
            if error:
                self.last_error = f'证据保存失败，旧截图仍保留：{type(error).__name__}'
                logger.error(self.last_error, exc_info=(type(error), error, error.__traceback__))
            self.revision += 1
        future.add_done_callback(finished)
        return future

    def _save(self, metadata, frame):
        try:
            return self.repository.save(metadata, frame)
        except Exception:
            if frame is not None and metadata.get('source') == 'automatic' and not metadata.get('require_image'):
                try:
                    self.repository.save(metadata, None)
                except Exception:
                    pass  # Disk/index failure is reported by the Future; never delete originals.
            raise

    def close(self):
        self._pool.shutdown(wait=True)


_service = None
_service_lock = threading.Lock()


def get_evidence_service():
    global _service
    with _service_lock:
        if _service is None:
            root = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share'))) / 'OKWW' / 'CompletionEvidence'
            from src.runtime.diagnostic_storage import storage_path
            root = storage_path('CompletionEvidence', root)
            _service = EvidenceService(EvidenceRepository(root))
        return _service


def begin_daily_run(task):
    from uuid import uuid4
    try:
        service = getattr(getattr(task, 'executor', None), 'completion_evidence_service', None)
        identity = getattr(task, '_verified_profile_id', None)
        if not isinstance(service, EvidenceService) or not identity:
            return None
        record = dict(run_id=str(uuid4()), profile_id=identity, started_at=now_iso(),
                      finished_at=None, result='running', video_paths=[],
                      scope='weekly_boss' if (getattr(task, '_runtime_overrides', None) or {}).get('_weekly_boss_only') else 'daily')
        service.submit(record, None, run=True)
        return record
    except Exception:
        logger.warning('运行记录开始保存失败，不改变任务流程')
        return None


def finish_daily_run(task, result):
    try:
        record = getattr(task, '_completion_run_record', None)
        if not isinstance(record, dict):
            return
        record = copy.deepcopy(record)
        record.update(finished_at=now_iso(), result=result)
        task.executor.completion_evidence_service.submit(record, None, run=True)
    except Exception:
        logger.warning('运行记录结束保存失败，不改变任务结果')


def bound_profile(executor):
    task = getattr(executor, 'current_task', None)
    if task is None:
        return None
    if getattr(task, '_active_account_switch_capture', None) is not None:
        return None
    verified = getattr(task, '_verified_profile_id', None)
    if verified:
        return verified
    if type(task).__name__ == 'MultiAccountDailyTask':
        from src.task.DailyTask import DailyTask
        daily = task.get_task_by_class(DailyTask)
        verified = getattr(daily, '_verified_profile_id', None)
        if verified and verified == getattr(task, '_current_profile_id', None):
            return verified
    return None


def request_capture(executor, *, feature_code=False):
    requests = getattr(executor, '_completion_capture_requests', None)
    if requests is None:
        requests = executor._completion_capture_requests = queue.Queue(maxsize=1)
    future = Future()
    future.feature_code = feature_code
    try:
        requests.put_nowait((future, time.monotonic() + 8, bound_profile(executor)))
    except queue.Full:
        raise RuntimeError('已有截图请求等待处理')
    wake = getattr(executor, '_wake_executor', None)
    if callable(wake):
        wake()
    return future


def process_capture(executor):
    """Called only on the executor thread. Never call task.next_frame or any input helper."""
    requests = getattr(executor, '_completion_capture_requests', None)
    if requests is None:
        return
    try:
        future, deadline, profile_id = requests.get_nowait()
    except queue.Empty:
        return
    if not future.set_running_or_notify_cancel():
        return
    try:
        if time.monotonic() > deadline:
            raise TimeoutError('截图请求已过期，请重新截图')
        if profile_id != bound_profile(executor):
            raise RuntimeError('截图期间账号绑定变化，请重新截图')
        task = getattr(executor, 'current_task', None)
        if getattr(task, '_active_account_switch_capture', None) is not None:
            raise RuntimeError('正在切换账号，请等待切换完成后截图')
        window = executor.device_manager.hwnd_window
        if window is None or not window.exists:
            raise RuntimeError('游戏窗口不可用')
        hwnd = window.hwnd
        if getattr(future, 'feature_code', False):
            if task is not None and getattr(task, 'running', False):
                raise RuntimeError('请先停止当前任务，再读取并绑定特征码')
            from src.task.CharacterTrialTask import CharacterTrialTask
            from src.task.account_feature_verification import observe, read_code
            reader = executor.get_task_by_class(CharacterTrialTask)
            def check():
                if (executor.exit_event.is_set() or not window.exists or window.hwnd != hwnd
                        or executor.current_task is not task):
                    raise RuntimeError('特征码读取期间窗口或任务变化')
            observed = observe(executor.method.get_frame, lambda image: read_code(reader, image),
                               check, time.sleep)
            if observed.status != 'verified':
                raise RuntimeError('未稳定读取特征码，请显示游戏右下角完整特征码后重试')
            future.set_result(dict(code=observed.code, verification=observed.metadata()))
            return
        frame = executor.method.get_frame()
        if frame is None or not frame.size or time.monotonic() > deadline:
            raise RuntimeError('未取得及时有效的游戏画面')
        if not window.exists or window.hwnd != hwnd or profile_id != bound_profile(executor):
            raise RuntimeError('截图期间窗口或账号变化')
        value = dict(frame=frame.copy(), profile_id=profile_id, captured_at=now_iso(),
                     identity_source='runtime_bound' if profile_id else 'user_confirmed')
        future.set_result(value)
    except Exception as error:
        future.set_exception(error)


def record_task_evidence(task, project_id, status, reason, frame=_CURRENT_FRAME, **details):
    """Best-effort observer: cannot change task success or production completion data."""
    try:
        executor = getattr(task, 'executor', None)
        # UI installation owns the service; unit tests/headless runs do not create a real store.
        service = getattr(executor, 'completion_evidence_service', None)
        if not isinstance(service, EvidenceService):
            return None
        profile_id = getattr(task, '_verified_profile_id', None) or bound_profile(executor)
        if not profile_id:
            return None
        current = getattr(executor, 'current_task', None)
        run_id = str(getattr(current, 'start_time', '') or '')
        if frame is _CURRENT_FRAME:
            frame = evidence_frame(task)
        metadata = dict(profile_id=profile_id, project_id=project_id, source='automatic',
                        completion_status=status, reason=reason, run_id=run_id,
                        identity_source='runtime_bound', captured_at=now_iso(), **details)
        if run_id:
            import hashlib
            import json
            metadata['event_id'] = hashlib.sha256(json.dumps(
                [profile_id, project_id, run_id, status, reason, details],
                sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return service.submit(metadata, frame)
    except Exception as error:
        logger.warning('完成证据未保存，不改变原任务结果：%s', type(error).__name__)
        return None
