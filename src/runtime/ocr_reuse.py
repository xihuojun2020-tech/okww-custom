"""Bounded reuse of identical OCR requests on the very same task frame."""
import copy
import time
import hashlib


def cached_ocr(task, invoke, args, kwargs):
    from src.runtime.vision_metrics import measure
    with measure('ocr_total'):
        return _cached_ocr(task, invoke, args, kwargs)


def _cached_ocr(task, invoke, args, kwargs):
    from src.runtime.vision_metrics import measure
    # Side-effect requests and caller-supplied images always execute normally.
    # Feature-code verification calls the raw engine and never enters here.
    if args or any(kwargs.get(k) is not None and kwargs.get(k) is not False
                   for k in ('frame', 'frame_processor', 'screenshot', 'log')):
        with measure('ocr_bypass'):
            return invoke(*args, **kwargs)
    frame = task.executor.frame
    if frame is None or getattr(task.executor, 'paused', False):
        return invoke(*args, **kwargs)
    with measure('ocr_key'):
        pixels = memoryview(frame) if frame.flags.c_contiguous else frame.tobytes()
        pixel_hash = hashlib.sha256(pixels).digest()
    key = (id(frame), getattr(task.executor, '_last_frame_time', None), frame.shape, pixel_hash,
           repr(sorted(kwargs.items())), task.ocr_default_threshold,
           id(getattr(task.executor, 'ocr_po_translation', None)))
    now = time.monotonic()
    from collections import OrderedDict
    cache = getattr(task, '_same_frame_ocr_results', None)
    if cache is None:
        cache = task._same_frame_ocr_results = OrderedDict()
    cached = cache.get(key)
    if cached and cached[0] == key and now - cached[1] < .25:
        return copy.deepcopy(cached[2])
    started = time.monotonic()
    result = invoke(**dict(kwargs, frame=frame))
    task._same_frame_ocr = (key, time.monotonic(), copy.deepcopy(result))
    cache[key] = task._same_frame_ocr
    if len(cache) > 8:
        cache.popitem(last=False)
    try:
        from src.runtime.diagnostic_lifecycle import _session
        if _session is not None:
            with _session.guard:
                _session.performance.observe('ocr', time.monotonic() - started)
    except Exception:
        pass
    return result
