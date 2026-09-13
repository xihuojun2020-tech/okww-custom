"""Bounded reuse of identical OCR requests on the very same task frame."""
import copy
import time
import hashlib


def cached_ocr(task, invoke, args, kwargs):
    # Side-effect requests and caller-supplied images always execute normally.
    # Feature-code verification calls the raw engine and never enters here.
    if args or any(kwargs.get(k) is not None and kwargs.get(k) is not False
                   for k in ('frame', 'frame_processor', 'screenshot', 'log')):
        return invoke(*args, **kwargs)
    frame = task.executor.frame
    if frame is None or getattr(task.executor, 'paused', False):
        return invoke(*args, **kwargs)
    pixels = memoryview(frame) if frame.flags.c_contiguous else frame.tobytes()
    key = (id(frame), getattr(task.executor, '_last_frame_time', None), frame.shape, hashlib.sha256(pixels).digest(),
           repr(sorted(kwargs.items())), task.ocr_default_threshold,
           id(getattr(task.executor, 'ocr_po_translation', None)))
    now = time.monotonic()
    cached = getattr(task, '_same_frame_ocr', None)
    if cached and cached[0] == key and now - cached[1] < .25:
        return copy.deepcopy(cached[2])
    started = time.monotonic()
    result = invoke(**dict(kwargs, frame=frame))
    task._same_frame_ocr = (key, time.monotonic(), copy.deepcopy(result))
    try:
        from src.runtime.diagnostic_lifecycle import _session
        if _session is not None:
            with _session.guard:
                _session.performance.observe('ocr', time.monotonic() - started)
    except Exception:
        pass
    return result
