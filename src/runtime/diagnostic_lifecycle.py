"""Best-effort application hooks; all network work stays in owned subprocesses."""
from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

from src.runtime.diagnostic_export import atomic_json, sanitize_text
from src.runtime.diagnostic_session import DiagnosticSession, default_root
from src.runtime.diagnostic_policy import settings, REPO

_session = None
_uploader = None
_last_wake = 0
_wake_lock = threading.Lock()
_runtime_bundle = None


def reset_incomplete_runtime_retries(root):
    for path in (Path(root) / 'states').glob('*.json'):
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
            if (state.get('status') == 'retrying'
                    and "No module named 'win32timezone'" in state.get('last_error', '')):
                state['next_retry'] = 0
                atomic_json(path, state)
        except (OSError, ValueError):
            continue


def wake_uploader(root=None):
    global _uploader, _last_wake, _runtime_bundle
    root = Path(root or default_root())
    with _wake_lock:
        if _uploader is not None and _uploader.poll() is None:
            return
        if time.monotonic() - _last_wake < 60:
            return
        settings(root)
        _last_wake = time.monotonic()
        from src.runtime.diagnostic_runtime import prepare_runtime, uploader_command, isolated_environment
        if _runtime_bundle is None:
            _runtime_bundle = prepare_runtime(REPO)
            reset_incomplete_runtime_retries(root)
        bundle = _runtime_bundle
        # A repaired immutable runtime should retry batches that were waiting
        # specifically because the previous bundle was incomplete.
        flags = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name == 'nt' else 0
        _uploader = subprocess.Popen(
            uploader_command(bundle, root), env=isolated_environment(),
            cwd=str(bundle), creationflags=flags,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def start_diagnostics(version, root=None):
    global _session
    if _session is not None:
        return _session
    try:
        root = Path(root or default_root())
        settings(root)
        try:
            import psutil
            process_started_at = psutil.Process(os.getpid()).create_time()
        except Exception:
            process_started_at = time.time()
        session = DiagnosticSession(root, version, source_root=REPO,
                                    current_run_started_at=process_started_at)
        session.on_batch_ready = lambda: wake_uploader(session.root)
        _session = session
        logging.getLogger().addHandler(session)
        previous, previous_thread = sys.excepthook, threading.excepthook

        def uncaught(kind, value, tb):
            try:
                record_crash(kind, value, tb)
            finally:
                previous(kind, value, tb)

        def thread_error(args):
            try:
                record_crash(args.exc_type, args.exc_value, args.exc_traceback, fatal=False)
            finally:
                previous_thread(args)

        sys.excepthook, threading.excepthook = uncaught, thread_error
        atexit.register(finish_diagnostics)
        wake_uploader(session.root)
        return session
    except Exception as error:
        # Diagnostic setup cannot prevent the game tool from starting.
        print('诊断初始化不可用：' + sanitize_text(error))
        return _session


def record_crash(kind, value, tb, *, fatal=True):
    if _session is None:
        return
    try:
        data = {'exception_type': kind.__name__, 'message': sanitize_text(value),
                'traceback': sanitize_text(''.join(traceback.format_exception(kind, value, tb)))}
        _session.record_event('uncaught_exception', data)
        atomic_json(_session.run / 'crash.json', data)
        if fatal:
            _session.metadata['process_status'] = 'crashed'
        _session.record_error(data)
        _session.request_batch('error')
    except Exception:
        pass


def attach_framework_hooks():
    """Wrap the existing save callback, without copying an entire framework module."""
    if _session is None:
        return
    logging.getLogger().addHandler(_session)
    try:
        from ok import og
        from ok.gui.debug.Screenshot import Screenshot
        _session.frame_provider = lambda: getattr(getattr(og, 'executor', None), '_frame', None)
        def sample():
            executor = getattr(og, 'executor', None)
            if executor is None:
                return None
            executor._diagnostic_capture_enabled = True
            _session.metadata['capture_last_ms'] = getattr(executor, '_capture_last_ms', None)
            return getattr(executor, '_diagnostic_frame', None)
        _session.sample_provider = sample
        original = Screenshot.save_pil_image
        if getattr(original, '_diagnostic_hook', False):
            return

        def saved(*args, **kwargs):
            path = original(*args, **kwargs)
            try:
                if _session is not None and not _session.closed_session:
                    _session.add_screenshot(path)
            except Exception:
                pass
            return path

        saved._diagnostic_hook = True
        Screenshot.save_pil_image = staticmethod(saved)
    except Exception:
        pass


def finish_diagnostics():
    if _session is None or _session.closed_session:
        return
    try:
        logging.getLogger().removeHandler(_session)
        _session.capture_last_frame()
        failed = _session.metadata['process_status'] == 'crashed'
        _session.finish('crashed' if failed else 'exited', 1 if failed else 0)
        wake_uploader(_session.root)
    except Exception:
        pass
