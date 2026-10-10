# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-worker observations; status never owns a task, device or configuration."""

import copy
import json
import logging
import os
from pathlib import Path
import time

import psutil

from src.runtime.diagnostic_export import atomic_json, sanitize_text


logger = logging.getLogger(__name__)


def live_directory(data_dir):
    return Path(data_dir).resolve() / 'okww监控室' / 'runtime' / 'workers'


class NativeLiveWriter:
    def __init__(self, context, package_id, version):
        from src.daily_timing import PROCESS_SESSION
        self.context = context
        self.path = live_directory(context.data_dir) / (PROCESS_SESSION + '.json')
        self.foreground = None
        self.value = {
            'worker_pid': os.getpid(), 'worker_create_time': psutil.Process().create_time(),
            'process_session': PROCESS_SESSION, 'data_dir': str(Path(context.data_dir).resolve()),
            'package_id': package_id, 'version': version, 'context_run_id': context.run_id,
            'foreground_task_id': '', 'foreground_started_ns': None,
            'running': False, 'paused': False, 'live': {}, 'timing': None,
            'services': {},
        }
        self._saved = None
        self._save()

    def _save(self):
        if self.value == self._saved:
            return
        try:
            atomic_json(self.path, self.value)
            self._saved = copy.deepcopy(self.value)
        except Exception:
            self._saved = None
            logger.exception('原生执行状态保存失败，原任务继续执行')
            # An old active snapshot must not masquerade as the current state.
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                logger.exception('无法移除过期的原生执行状态')

    def begin_foreground(self, task):
        from src.runtime.native_metadata import task_id
        self.foreground = task
        self.value.update(foreground_task_id=task_id(task),
                          foreground_started_ns=time.monotonic_ns(), running=True,
                          paused=self.context.pause.is_set(), live={}, timing=None)
        self._save()

    def publish(self, task):
        if task is not self.foreground:
            return
        info = task.info
        self.value['live'] = {
            'profile_id': str(info.get('Status Profile ID') or ''),
            'task_id': str(info.get('Status Task ID') or ''),
            'run_id': str(info.get('Status Run ID') or ''),
            'stage': sanitize_text(info.get('Status Stage') or ''),
            'detail': sanitize_text(info.get('Status Detail') or ''),
        }
        self._save()

    def publish_timing(self, timer):
        if timer.task is not self.foreground:
            return
        active = timer.active
        self.value['timing'] = ({
            'batch_id': timer.record['batch_id'], 'profile_id': active['profile_id'],
            'attempt_number': active['attempt_number'],
            'account_started_ns': int(timer.account_started[1] * 1_000_000_000),
            'batch_started_ns': int(timer.started[1] * 1_000_000_000),
        } if active is not None and timer.record['finished_at'] is None else None)
        self._save()

    def finish_foreground(self, task):
        if task is not self.foreground:
            return
        self.foreground = None
        self.value.update(foreground_task_id='', foreground_started_ns=None,
                          running=False, live={}, timing=None)
        self._save()

    def observe_event(self, event):
        if event.get('event') == 'task-paused':
            self.value['paused'] = event['paused']
            self._save()
        elif event.get('event') == 'combat-state':
            self.value['services']['auto-combat'] = {
                'enabled': event['enabled'], 'recovery_status': event['recovery_status']}
            self._save()

    def close(self):
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            logger.exception('原生执行状态清理失败')


class NativeLiveReader:
    """Reload on file events; elapsed/liveness reads only the cached observations."""
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).resolve()
        self.directory = live_directory(data_dir)
        self._cache = {}
        self.reload()

    def reload(self):
        self._cache = {}
        cache = {}
        for path in sorted(self.directory.glob('*.json')):
            try:
                value = json.loads(path.read_text(encoding='utf-8'))
            except FileNotFoundError:
                continue  # This worker closed while the directory snapshot was being read.
            if (not isinstance(value, dict) or value.get('process_session') != path.stem
                    or Path(value['data_dir']).resolve() != self.data_dir):
                raise ValueError(f'Invalid native worker status: {path.name}')
            if type(value['worker_pid']) is not int or type(value['worker_create_time']) not in (int, float):
                raise ValueError(f'Invalid native worker identity: {path.name}')
            cache[value['process_session']] = value
        self._cache = cache

    @staticmethod
    def _alive(value):
        try:
            process = psutil.Process(value['worker_pid'])
            return (process.create_time() == value['worker_create_time']
                    and process.status() != psutil.STATUS_ZOMBIE)
        except psutil.NoSuchProcess:
            return False

    def owners(self):
        return [copy.deepcopy(value) for _, value in sorted(self._cache.items()) if self._alive(value)]

    def live(self, process_session):
        value = self._cache.get(process_session)
        if value is None or not self._alive(value) or not value['running']:
            return {}
        live = copy.deepcopy(value['live'])
        live['elapsed'] = max(0, (time.monotonic_ns() - value['foreground_started_ns']) // 1_000_000_000)
        return live

    def timings(self):
        result = {}
        now = time.monotonic_ns()
        for owner in self.owners():
            timing = owner['timing']
            if timing is None:
                continue
            key = (owner['process_session'], timing['batch_id'], timing['profile_id'], timing['attempt_number'])
            result[key] = max(0, (now - timing['account_started_ns']) / 1_000_000_000)
        return result
