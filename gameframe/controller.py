"""Launch and stop only the execution process created by this controller."""

import json
import os
import subprocess
import sys
from pathlib import Path

import psutil


class Controller:
    def __init__(self):
        self.process = None
        self.execution = None
        self._owner = None

    def start(self, manifest, task_id, *, data_dir, config=None, device=None):
        manifest.task(task_id)
        data_dir = Path(data_dir).resolve()
        if config is not None and not isinstance(config, dict):
            raise ValueError('Task config must be a JSON object')
        if device is not None and not isinstance(device, dict):
            raise ValueError('Device config must be a JSON object')
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError('An execution process is already running')
        if manifest.execution == 'legacy-application':
            if config or device:
                raise ValueError('Legacy tasks use their production configuration and device selection')
            launch = manifest.load().legacy_command(task_id, data_dir)
            command, cwd, environment = launch['command'], launch['cwd'], launch['env']
        else:
            if device is None:
                raise ValueError('A native task requires an explicit device configuration')
            command = [sys.executable, '-m', 'gameframe.worker', '--package', str(manifest.root),
                       '--task', task_id, '--data-dir', str(data_dir),
                       '--device', json.dumps(device), '--config', json.dumps(config or {})]
            cwd = str(Path.cwd())
            environment = os.environ.copy()
            # Preserve caller-relative assets while also supporting a source checkout.
            module_root = str(Path(__file__).resolve().parents[1])
            environment['PYTHONPATH'] = os.pathsep.join(
                path for path in (module_root, environment.get('PYTHONPATH')) if path)
        environment['PYTHONIOENCODING'] = 'utf-8'
        environment['PYTHONUNBUFFERED'] = '1'
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        self.process = subprocess.Popen(command, cwd=cwd, env=environment,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                        errors='replace', bufsize=1, **options)
        self.execution = manifest.execution
        try:
            self._owner = psutil.Process(self.process.pid)
            self._owner.create_time()  # Retain identity before any PID reuse.
        except psutil.NoSuchProcess:
            self._owner = None  # A short task may already have exited.
        return self.process

    def request_stop(self):
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.stdin.write('{"command":"stop"}\n')
                self.process.stdin.flush()
            except BrokenPipeError:
                # The execution process exited while its stop command was in flight.
                self.process.wait(timeout=3)

    def stop(self, timeout=5):
        if self.process is None:
            return
        descendants = []
        if self.process.poll() is None and self._owner is not None:
            try:
                descendants = self._owner.children(recursive=True)
            except psutil.NoSuchProcess:
                pass
        self.request_stop()
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Windows venv python.exe can be a redirector; stopping only it
            # leaves the real interpreter (and its held input) running.
            if self._owner is not None:
                try:
                    descendants += self._owner.children(recursive=True)
                except psutil.NoSuchProcess:
                    pass
            for child in reversed(list({item.pid: item for item in descendants}.values())):
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            self.process.terminate()
            self.process.wait(timeout=5)
            _, alive = psutil.wait_procs(descendants, timeout=5)
            if alive:
                raise RuntimeError(f'Owned execution processes did not exit: {[p.pid for p in alive]}')

    def close(self):
        self.stop()
        if self.process is not None:
            for stream in (self.process.stdin, self.process.stdout):
                if stream is not None:
                    stream.close()
