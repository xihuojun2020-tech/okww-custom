"""Launch and stop only the execution process created by this controller."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import psutil

from gameframe.process_ownership import PROTECTED_PROCESSES_ENV, protected_process_identities
from gameframe.process_locks import package_lease
from gameframe.packages import PackageManifest


class Controller:
    def __init__(self):
        self.process = None
        self.execution = None
        self._owner = None
        self.session = False
        self._protected_path = None

    def assert_idle(self):
        """Require this owned execution/management process to have exited."""
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError('An owned execution process is still running')

    def start(self, manifest, task_id, *, data_dir, config=None, device=None, session=False):
        data_dir = Path(data_dir).resolve()
        manifest.task(task_id, data_dir)
        if config is not None and not isinstance(config, dict):
            raise ValueError('Task config must be a JSON object')
        if device is not None and not isinstance(device, dict):
            raise ValueError('Device config must be a JSON object')
        if session and (manifest.execution != 'native' or not manifest.supports_session):
            raise ValueError('This package does not provide a shared task session')
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError('An execution process is already running')
        if manifest.execution == 'legacy-application':
            if config or device:
                raise ValueError('Legacy tasks use their production configuration and device selection')
            with package_lease(manifest.root):
                if PackageManifest.read(manifest.root).version != manifest.version:
                    raise ValueError('Gamepack version changed before launch')
                launch = manifest.load().legacy_command(task_id, data_dir)
            command, cwd, environment = launch['command'], launch['cwd'], launch['env']
        else:
            if device is None:
                raise ValueError('A native task requires an explicit device configuration')
            command = [sys.executable, '-m', 'gameframe.worker', '--package', str(manifest.root),
                       '--expected-version', manifest.version,
                       '--task', task_id, '--data-dir', str(data_dir),
                       '--device', json.dumps(device), '--config', json.dumps(config or {})]
            if session:
                command.append('--session')
            cwd = str(Path.cwd())
            environment = os.environ.copy()
            environment['GAMEFRAME_CONTROLLER_PID'] = str(os.getpid())
            # Preserve caller-relative assets while also supporting a source checkout.
            module_root = str(Path(__file__).resolve().parents[1])
            environment['PYTHONPATH'] = os.pathsep.join(
                path for path in (module_root, environment.get('PYTHONPATH')) if path)
        return self._launch(command, cwd, environment, manifest.execution, session)

    def start_management(self, manifest, *, data_dir):
        if not manifest.management:
            raise ValueError('This package does not provide a management application')
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError('A management process is already running')
        with package_lease(manifest.root):
            if PackageManifest.read(manifest.root).version != manifest.version:
                raise ValueError('Gamepack version changed before management launch')
            launch = manifest.load().management_command(Path(data_dir).resolve())
        return self._launch(launch['command'], launch['cwd'], launch['env'], 'management', False)

    def start_overview(self, manifest, *, data_dir):
        if not manifest.overview:
            raise ValueError('This package does not provide a read-only overview')
        self.assert_idle()
        with package_lease(manifest.root):
            if PackageManifest.read(manifest.root).version != manifest.version:
                raise ValueError('Gamepack version changed before overview launch')
            launch = manifest.load().overview_command(Path(data_dir).resolve())
        return self._launch(launch['command'], launch['cwd'], launch['env'], 'overview', False)

    def _launch(self, command, cwd, environment, execution, session):
        if self._protected_path is not None:
            self._protected_path.unlink(missing_ok=True)
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', prefix='gameframe-processes-',
                                         suffix='.json', delete=False) as stream:
            stream.write('[]')
            self._protected_path = Path(stream.name)
        environment[PROTECTED_PROCESSES_ENV] = str(self._protected_path)
        environment['PYTHONIOENCODING'] = 'utf-8'
        environment['PYTHONUNBUFFERED'] = '1'
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        try:
            self.process = subprocess.Popen(command, cwd=cwd, env=environment,
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                            errors='replace', bufsize=1, **options)
        except BaseException:
            self._protected_path.unlink(missing_ok=True)
            self._protected_path = None
            raise
        self.execution = execution
        self.session = session
        try:
            self._owner = psutil.Process(self.process.pid)
            self._owner.create_time()  # Retain identity before any PID reuse.
        except psutil.NoSuchProcess:
            self._owner = None  # A short task may already have exited.
        return self.process

    def _send_control(self, command, **values):
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.stdin.write(json.dumps({'command': command, **values}) + '\n')
                self.process.stdin.flush()
                return True
            except BrokenPipeError:
                # The execution process exited while its stop command was in flight.
                self.process.wait(timeout=3)
        return False

    def request_live(self, command, request_id, **values):
        if command not in {'get-schema', 'set-config', 'invoke-action',
                           'inspect-frame', 'inspect-account-feature'}:
            raise ValueError(f'Unsupported live request: {command}')
        if not self.session or not self._send_control(command, request_id=request_id, **values):
            raise RuntimeError('A shared execution session is not running')

    def deliver_live_response(self, response):
        if self.execution != 'management' or not self._send_control('live-response', response=response):
            raise RuntimeError('The management process is not running')

    def request_stop(self):
        self._send_control('stop')

    def request_task(self, task_id, config):
        if not self.session:
            raise ValueError('A shared task session is not running')
        self._send_control('run-task', task_id=task_id, config=config)

    def request_user_task_reload(self):
        if not self.session:
            raise RuntimeError('User task reload requires a shared task session')
        self._send_control('reload-user-tasks')

    def set_service(self, task_id, enabled, config=None):
        if not self.session:
            raise ValueError('A shared task session is not running')
        self._send_control('set-service', task_id=task_id, enabled=enabled, config=config or {})

    def request_character_reload(self):
        if not self.session:
            raise RuntimeError('Character reload requires a shared task session')
        self._send_control('reload-character-code')

    def pause(self):
        if self.execution != 'native':
            raise ValueError('Compatibility application controls its own pause')
        self._send_control('pause')

    def resume(self):
        if self.execution != 'native':
            raise ValueError('Compatibility application controls its own pause')
        self._send_control('resume')

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
            protected = protected_process_identities(self._protected_path)
            owned = {}
            for child in descendants:
                try:
                    identity = (child.pid, child.create_time())
                except psutil.NoSuchProcess:
                    continue
                if identity not in protected:
                    owned[identity] = child
            descendants = list(owned.values())
            for child in reversed(descendants):
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
        if self._protected_path is not None:
            self._protected_path.unlink(missing_ok=True)
            self._protected_path = None
