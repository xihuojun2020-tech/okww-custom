"""Bounded, failure-only evidence for account switching.

The switch path keeps a small in-memory ring of recent frames.  A successful
switch simply drops that ring; only a failed/safely-stopped switch is written
to the dedicated evidence directory.  This module intentionally has no input
or window-management responsibilities.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from collections import deque
from pathlib import Path


DEFAULT_ROOT = Path("screenshots") / "account_switch_failures"
MAX_AGE_SECONDS = 7 * 24 * 60 * 60
MAX_EVENTS = 20
MAX_BYTES = 500 * 1024 * 1024
MAX_FRAMES = 30
MAX_FRAME_BYTES = 128 * 1024 * 1024
FRAME_WINDOW_SECONDS = 60.0
SAMPLE_INTERVAL_SECONDS = 2.0


def _default_root():
    try:
        from ok.util.file import get_relative_path

        return Path(get_relative_path(*DEFAULT_ROOT.parts))
    except Exception:
        return Path.cwd() / DEFAULT_ROOT


def _json_point(point):
    if point is None:
        return None
    try:
        return [float(point[0]), float(point[1])]
    except Exception:
        return None


def _json_box(box):
    if box is None:
        return None
    if isinstance(box, (list, tuple)) and len(box) >= 4:
        return [float(value) for value in box[:4]]
    values = []
    for attr in ("x", "y", "width", "height"):
        try:
            values.append(float(getattr(box, attr)))
        except Exception:
            return None
    return values


def _event_dirs(root):
    root = Path(root)
    if not root.exists():
        return []
    result = []
    for path in root.iterdir():
        if path.is_dir() and (path / "event.json").is_file():
            try:
                result.append((path.stat().st_mtime, path))
            except OSError:
                continue
    return sorted(result, key=lambda item: item[0])


def _dir_size(path):
    total = 0
    try:
        for child in path.rglob("*"):
            if child.is_file():
                try:
                    total += child.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def cleanup_account_switch_evidence(
    root=None,
    *,
    now=None,
    max_age_seconds=MAX_AGE_SECONDS,
    max_events=MAX_EVENTS,
    max_bytes=MAX_BYTES,
):
    """Delete complete oldest events until age/count/size limits are met."""
    root = Path(root) if root is not None else _default_root()
    if not root.exists():
        return []
    now = time.time() if now is None else float(now)
    entries = _event_dirs(root)
    removed = []
    # A process crash can leave a private staging directory behind.  It is
    # never a completed event and must not count toward retention limits.
    for path in root.iterdir():
        if path.is_dir() and path.name.startswith('.pending_'):
            try:
                # Leave a freshly-created writer alone; remove only stale
                # crash leftovers so periodic cleanup cannot race a stop
                # evidence writer.
                if now - path.stat().st_mtime > 300:
                    shutil.rmtree(path)
                    removed.append(str(path))
            except OSError:
                pass
    for mtime, path in list(entries):
        if now - mtime > max_age_seconds:
            try:
                shutil.rmtree(path)
                removed.append(str(path))
            except OSError:
                pass
    entries = _event_dirs(root)
    sizes = {path: _dir_size(path) for _, path in entries}
    while len(entries) > max_events or sum(sizes.values()) > max_bytes:
        _, path = entries[0]
        try:
            shutil.rmtree(path)
            removed.append(str(path))
        except OSError:
            break
        sizes.pop(path, None)
        entries = entries[1:]
    return removed


class AccountSwitchEvidenceSession:
    """One bounded account-switch evidence session."""

    def __init__(self, target_account, *, root=None, clock=None, blur_area=None,
                 max_frame_bytes=MAX_FRAME_BYTES):
        self.target_account = target_account
        self.root = Path(root) if root is not None else _default_root()
        self.clock = clock or time.time
        self.blur_area = blur_area
        self.started_at = float(self.clock())
        self.frames = deque()
        self.frame_bytes = 0
        self.max_frame_bytes = max(0, int(max_frame_bytes))
        self.events = []
        self.clicks = []
        self.identities = []
        self._finished = False
        self._last_sample_at = None
        self.event_dir = None

    def _drop_oldest_frame(self):
        self.frame_bytes -= int(self.frames.popleft()[1].nbytes)

    def _trim_frames(self, now):
        while self.frames and now - self.frames[0][0] > FRAME_WINDOW_SECONDS:
            self._drop_oldest_frame()

    def record_frame(self, frame, *, stage=None, force=False, metadata=None):
        if self._finished or frame is None:
            return False
        now = float(self.clock())
        self._trim_frames(now)
        if not force:
            if self._last_sample_at is not None and now - self._last_sample_at < SAMPLE_INTERVAL_SECONDS:
                return False
        size = int(getattr(frame, 'nbytes', 0))
        if size <= 0:
            return False
        if size > self.max_frame_bytes:
            self.events.append({'time': now, 'stage': 'frame_skipped', 'reason': 'frame_too_large',
                                'frame_bytes': size, 'source_stage': stage, 'forced': bool(force)})
            return False
        # Evict before allocation so the raw retained buffer never needs a
        # temporary extra frame beyond the cap.
        while self.frames and (len(self.frames) >= MAX_FRAMES or self.frame_bytes + size > self.max_frame_bytes):
            self._drop_oldest_frame()
        try:
            image = frame.copy()
        except Exception:
            return False
        if not force:
            self._last_sample_at = now
        self.frames.append((now, image, {"stage": stage, **(metadata or {})}))
        self.frame_bytes += size
        return True

    def record_stage(self, stage, *, attempt=None, detail=None, frame=None, metadata=None):
        if self._finished:
            return
        now = float(self.clock())
        event = {"time": now, "stage": str(stage)}
        if attempt is not None:
            event["attempt"] = int(attempt)
        if detail is not None:
            event["detail"] = str(detail)
        self.events.append(event)
        if frame is not None:
            self.record_frame(frame, stage=stage, force=True, metadata=metadata)

    def record_identity(self, account, *, frame=None, stage=None):
        if self._finished:
            return
        value = None if account is None else str(account)
        if self.identities and self.identities[-1]["account"] == value:
            return
        self.identities.append({"time": float(self.clock()), "account": value, "stage": stage})
        self.record_stage("identity", detail=value, frame=frame)

    def record_click(
        self,
        mode,
        point,
        *,
        target_box=None,
        window_point=None,
        screen_point=None,
        hwnd=None,
        attempt=None,
        stage=None,
        frame=None,
        delivered=None,
    ):
        if self._finished:
            return
        normalized_box = _json_box(target_box)
        normalized_point = _json_point(point)
        delivered_value = None if delivered is None else bool(delivered)
        click = {
            "time": float(self.clock()),
            "mode": str(mode),
            "delivery_point": normalized_point if delivered_value is not False else None,
            "actual_click_point": normalized_point if delivered_value is not False else None,
            "attempted_point": normalized_point,
            "delivered": delivered_value,
            "window_point": _json_point(window_point),
            "screen_point": _json_point(screen_point),
            "target_box": normalized_box,
            "target_ocr_box": normalized_box,
            "hwnd": hwnd,
            "attempt": attempt,
            "retry": attempt,
            "stage": stage,
        }
        click_index = len(self.clicks)
        self.clicks.append(click)
        self.record_stage(
            "click", attempt=attempt, detail=mode, frame=frame,
            metadata={"click_index": click_index},
        )

    def _annotate(self, frame, metadata=None):
        try:
            import cv2
            image = frame.copy()
            try:
                from ok import og
                from ok.util.blur import apply_blur_areas, get_blur_algorithm

                blur_area = self.blur_area
                if not callable(blur_area):
                    runtime_config = getattr(og, 'config', None)
                    blur_area = runtime_config.get('blur_area') if runtime_config is not None else None
                algorithm = get_blur_algorithm(getattr(og, 'global_config', None))
                image = apply_blur_areas(image, blur_area, algorithm)
            except Exception:
                # A missing optional GUI global must never prevent evidence
                # capture; the normal framework path remains best effort.
                pass
            metadata = metadata or {}
            # A regular/stage frame has no click association.  Never paint
            # clicks from later in the session onto it; only the forced frame
            # created by record_click carries click_index metadata.
            selected = []
            click_index = metadata.get("click_index")
            if click_index is not None:
                selected = self.clicks[click_index:click_index + 1]
            for click in selected:
                box = click.get("target_box")
                if box and len(box) >= 4:
                    x, y, w, h = [int(value) for value in box]
                    cv2.rectangle(image, (x, y), (x + w, y + h), (0, 0, 255), 2)
                # Annotate in the captured frame's client coordinates.  For
                # system clicks, delivery_point is screen-space while
                # window_point is the corresponding frame-space point.
                point = click.get("window_point") or click.get("attempted_point")
                if point:
                    x, y = int(point[0]), int(point[1])
                    cv2.circle(image, (x, y), 12, (0, 0, 255), 2)
                    cv2.drawMarker(image, (x, y), (0, 0, 255), cv2.MARKER_CROSS, 24, 2)
                    window = click.get("window_point")
                    screen = click.get("screen_point")
                    status = "delivered" if click.get("delivered") is not False else "failed"
                    text = f'{click.get("mode", "?")} #{click.get("attempt") or "-"} {status}'
                    if window:
                        text += f' win=({window[0]:.0f},{window[1]:.0f})'
                    if screen:
                        text += f' screen=({screen[0]:.0f},{screen[1]:.0f})'
                    cv2.putText(image, text[:180], (max(0, x + 14), max(18, y - 14)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)
            return image
        except Exception:
            return frame

    def _write_failure_event(self, event_dir, event_id, reason, stage, last_account, frames):
        """Write a complete event into a private directory, then publish it."""
        temp_dir = self.root / f".pending_{event_id}"
        try:
            temp_dir.mkdir(parents=True, exist_ok=False)
            image_names = []
            for index, (_timestamp, frame, metadata) in enumerate(frames):
                path = temp_dir / f"frame_{index:03d}.jpg"
                try:
                    import cv2

                    if cv2.imwrite(str(path), self._annotate(frame, metadata), [cv2.IMWRITE_JPEG_QUALITY, 85]):
                        image_names.append(path.name)
                except Exception:
                    continue
            payload = {
                "event_id": event_id,
                "target_account": self.target_account,
                "last_account": last_account if last_account is not None else (self.identities[-1]["account"] if self.identities else None),
                "reason": str(reason),
                "stage": stage,
                "started_at": self.started_at,
                "ended_at": float(self.clock()),
                "events": self.events,
                "identities": self.identities,
                "clicks": self.clicks,
                "target_ocr_boxes": [click["target_ocr_box"] for click in self.clicks if click.get("target_ocr_box")],
                "actual_clicks": [
                    {
                        "mode": click.get("mode"),
                        "delivered": click.get("delivered"),
                        "delivery_point": click.get("actual_click_point"),
                        "attempted_point": click.get("attempted_point"),
                        "window_point": click.get("window_point"),
                        "screen_point": click.get("screen_point"),
                    }
                    for click in self.clicks
                ],
                "frames": image_names,
            }
            (temp_dir / "event.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temp_dir.replace(event_dir)
            # Apply retention after asynchronous stop writes as well, so the
            # newly completed event cannot leave count/capacity over limits.
            cleanup_account_switch_evidence(root=self.root)
        except Exception:
            try:
                shutil.rmtree(temp_dir)
            except OSError:
                pass
        finally:
            frames.clear()

    def fail(self, reason, *, stage=None, last_account=None, stopped=False):
        if self._finished:
            return self.event_dir
        self._finished = True
        self._trim_frames(float(self.clock()))
        frames, self.frames = self.frames, deque()
        self.frame_bytes = 0
        cleanup_account_switch_evidence(root=self.root)
        event_id = uuid.uuid4().hex[:12]
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(self.started_at))
        safe_stage = "".join(c if c.isalnum() or c in "-_" else "_" for c in (stage or "failed"))
        event_dir = self.root / f"{stamp}_{event_id}_{safe_stage}"
        self.event_dir = event_dir
        if stopped:
            threading.Thread(
                target=self._write_failure_event,
                args=(event_dir, event_id, reason, stage, last_account, frames),
                daemon=True,
            ).start()
            return event_dir
        self._write_failure_event(event_dir, event_id, reason, stage, last_account, frames)
        cleanup_account_switch_evidence(root=self.root)
        return event_dir

    def succeed(self):
        if self._finished:
            return True
        self._finished = True
        self.frames.clear()
        self.frame_bytes = 0
        self.events.clear()
        self.clicks.clear()
        self.identities.clear()
        return True


def cleanup_account_switch_evidence_on_startup():
    return cleanup_account_switch_evidence()


def cleanup_account_switch_evidence_periodic():
    return cleanup_account_switch_evidence()
