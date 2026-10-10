"""Execute native game packages with one input owner and truthful outcomes."""

from __future__ import annotations

import copy
import logging
import threading
import uuid
from pathlib import Path

from gameframe.api import Cancelled, TaskContext
from gameframe.state import RunStore


class Runtime:
    def __init__(self, store: RunStore, events):
        self.store = store
        self.events = events
        self._input_owner = threading.Lock()

    def emit(self, value):
        # A UI/IPC observer is a diagnostic boundary, not part of game success.
        try:
            self.events(value)
        except Exception:
            logging.getLogger(__name__).exception('Unable to deliver execution event')

    def run(self, manifest, package, task_id, device, data_dir: Path,
            config=None, stop=None, pause=None, *, session=False, requests=None):
        task = None if session and task_id is None else manifest.task(task_id, data_dir)
        required = task.required_capabilities if task is not None else manifest.session_required_capabilities
        missing = required - device.capabilities
        if missing:
            raise ValueError(f'Device missing capabilities: {sorted(missing)}')
        run_id = uuid.uuid4().hex
        merged = copy.deepcopy(task.default_config) if task is not None else {}
        if config is not None:
            merged.update(config)
        context = TaskContext(device, merged, Path(data_dir), stop or threading.Event(),
                              run_id, self.emit, pause if pause is not None else threading.Event())
        context.task_definition = task
        if requests is not None:
            context.requests = requests
        if not self._input_owner.acquire(blocking=False):
            raise RuntimeError('Another task owns device input')
        context._input_owner_thread = threading.get_ident()
        begun = False
        try:
            try:
                self.store.begin(run_id, manifest.id, task_id if task_id is not None else '__session__')
                begun = True
                context.emit('started', package_id=manifest.id, task_id=task_id)
                outcome = (package.run_session(task_id, context) if session
                           else package.run(task_id, context))
                # Some production tasks catch their framework stop exception.
                # A returned value cannot turn the explicit stop into success.
                context.check_stop()
                result = dict(outcome)
                status = result.pop('status', 'success')
                if status not in {'success', 'blocked', 'skipped'}:
                    raise ValueError(f'Invalid package outcome: {status}')
            finally:
                # Cleanup is part of success, and occurs exactly once on every path.
                device.release_all()
            self.store.finish(run_id, status, result)
            context.emit('finished', status=status, result=result)
            return result
        except Cancelled as error:
            if begun:
                self.store.finish(run_id, 'cancelled', {'error': str(error)})
            context.emit('finished', status='cancelled')
            raise
        except Exception as error:
            if begun:
                self.store.finish(run_id, 'failed', {'type': type(error).__name__, 'error': str(error)})
            context.emit('finished', status='failed', error=str(error))
            raise
        finally:
            context._input_owner_thread = None
            self._input_owner.release()

    def run_service(self, manifest, package, task_id, device, data_dir, *, stop,
                    pause=None, config=None):
        """Ordinary failures retain the saved user intent and retry after a bounded wait."""
        pause_reported = False
        while not stop.is_set() and self.store.enabled(manifest.id, task_id):
            if pause is not None and pause.is_set():
                if not pause_reported:
                    self.emit({'event': 'task-paused', 'paused': True})
                    pause_reported = True
                stop.wait(0.25)
                continue
            if pause_reported:
                self.emit({'event': 'task-paused', 'paused': False})
                pause_reported = False
            try:
                self.run(manifest, package, task_id, device, data_dir, config, stop, pause)
            except Cancelled:
                break
            except Exception as error:
                self.emit({'event': 'service-waiting', 'package_id': manifest.id,
                             'task_id': task_id, 'error': str(error)})
            stop.wait(0.25)
