# SPDX-License-Identifier: AGPL-3.0-or-later
"""Observe native workers using the existing local diagnostic session."""

import sys
from pathlib import Path

from src.runtime import diagnostic_lifecycle
from src.runtime.diagnostic_export import sanitize_text
from src.runtime.diagnostic_storage import storage_path
from src.runtime.native_screenshots import masked_native_frame


def diagnostic_root(data_dir):
    data_dir = Path(data_dir).resolve()
    return storage_path('diagnostics', data_dir / 'okww监控室' / 'diagnostics', repo=data_dir)


def start_native_diagnostics(data_dir, version):
    try:
        return diagnostic_lifecycle.start_diagnostics(
            version, diagnostic_root(data_dir), source_root=Path(data_dir).resolve(), local_only=True)
    except Exception as error:
        _failure(error)
        return None


def _failure(error):
    # Diagnostic observers must preserve the task's result/exception, without
    # recursively feeding a failing diagnostic handler through logging.
    print('本地诊断观察失败：' + sanitize_text(error), file=sys.stderr)


def _session():
    session = diagnostic_lifecycle._session
    return session if session is not None and not session.closed_session else None


def attach_native_executor(executor):
    session = _session()
    if session is None:
        return

    def sample():
        cached = executor._diagnostic_frame
        if cached is None:
            return None
        frame, captured_at, captured_monotonic = cached
        return masked_native_frame(frame), captured_at, captured_monotonic

    def last_frame():
        cached = sample()
        return cached[0] if cached is not None else None

    session.sample_provider = sample
    session.frame_provider = last_frame


def screenshot_saved(path):
    session = _session()
    if session is not None:
        try:
            session.add_screenshot(path)
        except Exception as error:
            _failure(error)


def record_native_event(kind, *, task, status, stage, error=None):
    session = _session()
    if session is None:
        return
    # Never expose a target/profile/alias/phone or account exception message.
    data = {'task': task, 'status': status, 'stage': stage}
    if error is not None:
        data['exception_type'] = type(error).__name__
    try:
        session.record_event(kind, data)
        if status == 'failed':
            session.record_error(data)
    except Exception as observer_error:
        _failure(observer_error)
