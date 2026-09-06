"""Run one unittest file with redaction installed before project imports."""

from __future__ import annotations

import argparse
import builtins
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.observability import install_redaction_filters, redact_message


def _write_result(path, result):
    if path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


def run_isolated(test_file, *, timeout=180.0):
    """Supervise only this test's process tree, including interpreter shutdown."""
    if timeout <= 0:
        raise ValueError('test timeout must be positive')
    started = time.monotonic()
    job = None
    process = None
    timed_out = False
    with tempfile.TemporaryDirectory(prefix='okww-test-') as temp:
        result_path = Path(temp) / 'result.json'
        command = [sys.executable, str(Path(__file__).resolve()), str(Path(test_file).resolve()),
                   '--child', '--result-file', str(result_path)]
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        try:
            if os.name == 'nt':
                import win32api
                import win32con
                import win32job
                job = win32job.CreateJobObject(None, '')
                limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
                limits['BasicLimitInformation']['LimitFlags'] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
            process = subprocess.Popen(command, stdout=sys.stdout, stderr=sys.stderr, **options)
            if job is not None:
                handle = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE,
                                             False, process.pid)
                try:
                    win32job.AssignProcessToJobObject(job, handle)
                finally:
                    handle.Close()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
        finally:
            if job is not None:
                job.Close()
            elif process is not None and os.name != 'nt':
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=10)
        result = json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else {}
        exit_code = process.returncode or (0 if 'tests_run' in result else 1)
        result.update(test_file=str(Path(test_file).resolve()),
                      elapsed_seconds=round(time.monotonic() - started, 3),
                      exit_code=124 if timed_out else exit_code,
                      status='timed_out' if timed_out else ('passed' if exit_code == 0 else 'failed'))
        return result


def _run_test(test_file, result_file):
    original_print = builtins.print

    def safe_print(*values, **kwargs):
        original_print(*(redact_message(value) for value in values), **kwargs)

    install_redaction_filters()
    builtins.print = safe_print
    sys.argv[0] = str(ROOT / "python.exe -m unittest")
    path = Path(test_file).resolve()
    sys.path.insert(0, str(path.parent))
    program = unittest.main(module=None, argv=[sys.argv[0], path.stem], exit=False)
    result = program.result
    _write_result(result_file, {'tests_run': result.testsRun, 'skipped': len(result.skipped),
                                'failures': len(result.failures), 'errors': len(result.errors)})
    return 0 if result.wasSuccessful() else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('test_file')
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--result-file', type=Path)
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        raise SystemExit(_run_test(args.test_file, args.result_file))
    result = run_isolated(args.test_file, timeout=args.timeout)
    _write_result(args.result_file, result)
    print(f"{Path(args.test_file).name}: {result['status']} ({result['elapsed_seconds']:.3f}s)")
    raise SystemExit(result['exit_code'])


if __name__ == "__main__":
    main()
