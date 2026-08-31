"""Small, failure-tolerant status bridge for the optional task monitor."""

from dataclasses import dataclass
import time


STATUS_ACCOUNT = "Status Account"
STATUS_STAGE = "Status Stage"
STATUS_DETAIL = "Status Detail"


@dataclass(frozen=True)
class TaskStatusSnapshot:
    task_name: str
    account: str
    stage: str
    detail: str
    elapsed_seconds: int
    level: str
    message: str
    completed_count: int


def _status_owner(task):
    executor = getattr(task, "executor", None)
    return getattr(executor, "current_task", None) or task


def publish_task_status(task, *, account=None, stage=None, detail=None):
    """Publish status without allowing an optional UI failure to stop a task."""
    try:
        owner = _status_owner(task)
        setter = getattr(owner, "info_set", None)
        for key, value in (
            (STATUS_ACCOUNT, account),
            (STATUS_STAGE, stage),
            (STATUS_DETAIL, detail),
        ):
            if value is None:
                continue
            if callable(setter):
                setter(key, value)
            else:
                owner.info[key] = value
    except Exception:
        pass


def _translated_info_value(task, info, key):
    keys = [key]
    translator = getattr(task, "tr", None)
    if callable(translator):
        try:
            keys.append(str(translator(key)))
        except Exception:
            pass
    for candidate in dict.fromkeys(keys):
        value = str(info.get(candidate) or "").strip()
        if value:
            return value
    return ""


def read_task_status(task, *, paused=False, now=None):
    now = time.time() if now is None else float(now)
    info = dict(getattr(task, "info", {}) or {})
    error = _translated_info_value(task, info, "Error")
    warning = _translated_info_value(task, info, "Warning")
    detail = str(info.get(STATUS_DETAIL) or info.get("Log") or "").strip()
    if error:
        level, message = "error", error
    elif warning:
        level, message = "warning", warning
    elif paused:
        level, message = "paused", "任务已暂停"
    else:
        level, message = "running", detail
    start_time = float(getattr(task, "start_time", 0) or 0)
    elapsed = max(0, int(now - start_time)) if start_time else 0
    completed = info.get("Completed") or []
    completed_count = len(completed) if isinstance(completed, (list, tuple, set)) else 0
    return TaskStatusSnapshot(
        task_name=str(getattr(task, "name", "") or ""),
        account=str(info.get(STATUS_ACCOUNT) or "-"),
        stage=str(info.get(STATUS_STAGE) or getattr(task, "name", "") or ""),
        detail=detail,
        elapsed_seconds=elapsed,
        level=level,
        message=message,
        completed_count=completed_count,
    )


def _intersects(left, right):
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    return not (
        lx + lw <= rx or rx + rw <= lx or
        ly + lh <= ry or ry + rh <= ly
    )


def choose_status_position(work_areas, game_rect, status_size, gap=12):
    width, height = status_size
    for area in work_areas:
        if not _intersects(area, game_rect):
            x, y, area_width, _area_height = area
            return x + area_width - width - gap, y + gap

    gx, gy, gw, gh = game_rect
    candidates = (
        (gx + gw + gap, gy + gap),
        (gx - width - gap, gy + gap),
        (gx + gw - width - gap, gy - height - gap),
        (gx + gw - width - gap, gy + gh + gap),
    )
    for px, py in candidates:
        status_rect = (px, py, width, height)
        if _intersects(status_rect, game_rect):
            continue
        for ax, ay, aw, ah in work_areas:
            if px >= ax and py >= ay and px + width <= ax + aw and py + height <= ay + ah:
                return px, py
    return None
