"""Build an immutable uploader runtime outside the application's update tree."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

CODE_ROOT = Path(__file__).resolve().parents[2]


def isolated_environment():
    env = dict(os.environ)
    for key in list(env):
        if key.upper().startswith(('PYTHON', 'PYAPPIFY')) or key.upper() == 'VIRTUAL_ENV':
            env.pop(key, None)
    return env


def background_home(source):
    # Keep the runtime on the installation's drive, outside its update directory.
    return Path(Path(source).resolve().anchor) / 'OKWW-Background'


def prepare_runtime(source_repo=None, *, home=None, code_repo=CODE_ROOT):
    from src.runtime.diagnostic_policy import installation_id
    from src.runtime.diagnostic_session import FileLease
    source = Path(source_repo or code_repo).resolve()
    code_repo = Path(code_repo).resolve()
    files = list((code_repo / 'src/runtime').glob('diagnostic_*.py'))
    files += [code_repo / 'src/observability.py', code_repo / 'src/runtime/install_diagnostic_task.ps1']
    fingerprint = hashlib.sha256((str(source) + sys.version + str(sys.base_prefix)).encode())
    for path in sorted(files):
        fingerprint.update(path.name.encode() + path.read_bytes())
    owner = Path(home or background_home(source)).resolve() / installation_id(source)
    if owner.is_relative_to(source):
        raise ValueError('Background runtime must be outside the application source')
    target = owner / fingerprint.hexdigest()[:20]
    owner.mkdir(parents=True, exist_ok=True)
    with FileLease(owner / '.prepare.lock'):
        if (target / 'ready.json').is_file():
            return target
        stage = owner / ('preparing-' + uuid.uuid4().hex)
        stage.mkdir()
        try:
            base = Path(sys.base_prefix)
            python = stage / 'python'
            python.mkdir()
            for pattern in ('python*.exe', '*.dll', 'python*.zip', 'python*._pth'):
                for path in base.glob(pattern):
                    shutil.copy2(path, python / path.name)
            for path in python.glob('python*._pth'):
                path.write_text('\n'.join([p.name for p in python.glob('python*.zip')]
                                          + ['Lib', 'DLLs', 'Lib/site-packages', '..', 'import site']), encoding='utf-8')
            for name in ('Lib', 'DLLs'):
                if (base / name).is_dir():
                    shutil.copytree(base / name, python / name,
                                    ignore=shutil.ignore_patterns('site-packages', '__pycache__', 'test', 'tests', 'idlelib', 'tkinter'))
            packages = python / 'Lib/site-packages'
            packages.mkdir(parents=True, exist_ok=True)
            import PIL
            shutil.copytree(Path(PIL.__file__).parent, packages / 'PIL', ignore=shutil.ignore_patterns('__pycache__'))
            pillow_libs = Path(PIL.__file__).parent.parent / 'pillow.libs'
            if pillow_libs.exists():
                shutil.copytree(pillow_libs, packages / pillow_libs.name)
            for name in ('win32cred', 'win32wnet', 'win32timezone', 'win32api'):
                spec = importlib.util.find_spec(name)
                shutil.copy2(spec.origin, packages / Path(spec.origin).name)
            import pywintypes
            dll = Path(pywintypes.__file__)
            shutil.copy2(dll, python / dll.name)
            shutil.copy2(dll, packages / 'pywintypes.pyd')
            for path in files:
                destination = stage / path.relative_to(code_repo)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
            (stage / 'src/__init__.py').write_text('', encoding='utf-8')
            (stage / 'src/runtime/__init__.py').write_text('', encoding='utf-8')
            (stage / 'source.json').write_text(json.dumps({'source_repo': str(source)}), encoding='utf-8')
            check_runtime(stage)
            (stage / 'ready.json').write_text(json.dumps({'source_repo': str(source)}), encoding='utf-8')
            stage.rename(target)
        except Exception:
            # Only the fresh, verified child of our own runtime directory.
            if stage.parent == owner and stage.name.startswith('preparing-'):
                shutil.rmtree(stage)
            raise
    return target


def check_runtime(bundle):
    bundle = Path(bundle).resolve()
    probe = ("import sys,json,win32cred,win32wnet,win32timezone,win32api,pywintypes; from PIL import Image; "
             "from src.runtime import diagnostic_uploader,diagnostic_retention; "
             "print(json.dumps(sys.path))")
    result = subprocess.run([str(bundle / 'python/python.exe'), '-E', '-s', '-c', probe],
                            cwd=str(bundle), env=isolated_environment(), capture_output=True, timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise RuntimeError('Background runtime self-check failed: ' + result.stderr.decode(errors='replace')[-1500:])
    paths = json.loads(result.stdout)
    if any(p and not Path(p).resolve().is_relative_to(bundle) for p in paths):
        raise RuntimeError('Background runtime imports outside its isolated bundle')


def uploader_command(bundle, root):
    return [str(Path(bundle) / 'python/pythonw.exe'), '-E', '-s', '-m',
            'src.runtime.diagnostic_uploader', '--root', str(root), '--ensure-task']
