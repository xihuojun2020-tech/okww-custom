"""Quiesce only this installation's scheduled and detached diagnostic workers."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess


@contextmanager
def quiesce_uploaders(repo, destination):
    from src.runtime.storage_bootstrap import read_json
    script = Path(__file__).with_name('storage_handoff.ps1')
    command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
               '-SourceRepo', str(repo), '-Journal', str(destination / 'migration/tasks.json')]
    def run(mode):
        result = subprocess.run(command + ['-Mode', mode], capture_output=True, timeout=30,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise OSError('后台上传任务交接失败：' + result.stderr.decode(errors='replace')[-600:])
    if os.name != 'nt':
        yield
        return
    try:
        run('Pause')
        import psutil
        for process in psutil.process_iter(['pid', 'cmdline', 'exe']):
            try:
                command_line = process.info['cmdline'] or []
                if 'src.runtime.diagnostic_uploader' not in command_line: continue
                executable = Path(process.info['exe']).resolve()
                binding = executable.parent.parent / 'ready.json'
                owned = binding.is_file() and Path(read_json(binding)['source_repo']).resolve() == repo
                # Older uploader executed directly from this installation.
                owned = owned or (executable.is_relative_to(repo) and Path(process.cwd()).resolve() == repo)
                if owned:
                    children = process.children(recursive=True)
                    for child in reversed(children): child.terminate()
                    process.terminate()
                    _, alive = psutil.wait_procs([process, *children], timeout=5)
                    if alive: raise OSError('当前安装上传器尚未停止，迁移未开始')
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        yield
    finally:
        current = read_json(repo / 'configs/runtime_storage.json', {})
        if current.get('root') != str(destination) or current.get('schema') != 2:
            run('Restore')
        # After commit leave old actions disabled. start_diagnostics installs
        # the new isolated action; failure stays pending and never reopens old DBs.
