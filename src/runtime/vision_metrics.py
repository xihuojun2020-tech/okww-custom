"""Lightweight stage timings; no screenshot or file writes on the hot path."""
from contextlib import contextmanager
import sys
import time


@contextmanager
def measure(stage):
    started = time.perf_counter()
    try:
        yield
    finally:
        module = sys.modules.get('src.runtime.diagnostic_lifecycle')
        session = getattr(module, '_session', None)
        if session is not None:
            try:
                with session.guard:
                    session.performance.observe(stage, time.perf_counter() - started)
            except Exception:
                pass
