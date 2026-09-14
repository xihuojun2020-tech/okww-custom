"""Small in-memory diagnostics summary; raw account identities are never stored."""
from collections import deque
from threading import Lock
from time import time, monotonic
from contextlib import contextmanager
from uuid import uuid4

_lock = Lock()
_recent = deque(maxlen=30)


def publish(operation_id, task, step, status, attempts, elapsed, remaining, *, max_attempts=3, error=None, attempt_label="输入尝试"):
    row = dict(operation_id=operation_id, task=task, step=step, status=status,
               attempts=attempts, max_attempts=max_attempts, error=error, elapsed=round(elapsed, 2), remaining=None if remaining is None else round(max(0, remaining), 2),
               attempt_label=attempt_label, at=time())
    with _lock:
        if _recent and _recent[-1]['operation_id'] == operation_id:
            _recent[-1] = row
        else:
            _recent.append(row)


def snapshot():
    with _lock:
        return [dict(row) for row in _recent]


def status_text():
    rows = snapshot()
    if not rows:
        return '暂无导航记录'
    labels = {'source':'等待来源页稳定', 'target':'已到达目标',
              'unknown':'页面暂不明确，等待识别', 'loading':'加载中', 'context_changed':'上下文变化'}
    return '\n'.join(f"{r['task']} · {r['step']}：{labels.get(r['status'],r['status'])}"
                     f"｜{r.get('attempt_label', '输入尝试')} {r['attempts']}/{r['max_attempts']} 次｜耗时 {r['elapsed']} 秒"
                     + ("｜使用专用等待预算" if r['remaining'] is None else f"｜预算剩余 {r['remaining']} 秒") + (f"｜原因 {r['error']}" if r['error'] else '')
                     for r in rows[-5:])


@contextmanager
def observe_operation(task, step, *, max_attempts, timeout=None, attempt_label='输入尝试'):
    """Diagnostics only: never retry, capture frames, or expose account identities."""
    operation_id = uuid4().hex
    started = monotonic()
    attempts = 0
    def update(status, count=None, error=None):
        nonlocal attempts
        if count is not None:
            attempts = count
        try:
            elapsed = monotonic()-started
            publish(operation_id, type(task).__name__, step, status, attempts, elapsed,
                    None if timeout is None else timeout-elapsed, max_attempts=max_attempts,
                    error=error, attempt_label=attempt_label)
        except Exception:
            pass
    update('开始核验')
    try:
        yield update
    except BaseException as error:
        update('停止/失败', error=type(error).__name__)
        raise
    else:
        update('已到达目标')
