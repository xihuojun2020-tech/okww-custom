# SPDX-License-Identifier: MIT
"""Current-user login entry; registry access occurs only on explicit save."""
import ntpath
import subprocess
import tempfile


RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'GameFrame'


class CurrentUserRun:
    def __init__(self):
        import winreg
        self.registry = winreg

    def read(self):
        registry = self.registry
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, kind = registry.QueryValueEx(key, VALUE_NAME)
        except FileNotFoundError:
            return None
        if kind != registry.REG_SZ:
            raise ValueError('GameFrame login entry must be a string')
        return value

    def write(self, command):
        registry = self.registry
        with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, RUN_KEY, 0,
                                  registry.KEY_SET_VALUE) as key:
            registry.SetValueEx(key, VALUE_NAME, 0, registry.REG_SZ, command)

    def remove(self):
        registry = self.registry
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, RUN_KEY, 0,
                                  registry.KEY_SET_VALUE) as key:
                registry.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass  # Own value already absent: requested disabled state is achieved.


def _permanent_absolute(value):
    path = ntpath.normpath(str(value))
    if not ntpath.isabs(path) or not ntpath.splitdrive(path)[0] or path.startswith('\\\\'):
        raise ValueError('Login entry requires an absolute local installed path')
    parts = path.lower().replace('/', '\\').split('\\')
    if any(part in ('.venv', 'test_out', 'temp', 'tmp') for part in parts):
        raise ValueError('Development and temporary paths cannot be login entries')
    temporary = ntpath.normcase(ntpath.normpath(tempfile.gettempdir()))
    if (ntpath.splitdrive(ntpath.normcase(path))[0] == ntpath.splitdrive(temporary)[0]
            and ntpath.commonpath((ntpath.normcase(path), temporary)) == temporary):
        raise ValueError('Temporary paths cannot be login entries')
    return path


def login_command(launch_argv, installation_root):
    """Validate the explicit installer-issued GUI command, never infer sys.executable."""
    argv = list(launch_argv)
    if (len(argv) != 8 or argv[1:5] != ['-m', 'gameframe', 'gui', '--packages']
            or argv[6] != '--data-dir'):
        raise ValueError('Login entry must open only the GameFrame GUI')
    root = ntpath.normcase(_permanent_absolute(installation_root))
    executable, packages, data = (_permanent_absolute(argv[index]) for index in (0, 5, 7))
    if ntpath.basename(executable).lower() != 'pythonw.exe':
        raise ValueError('Login entry requires the installed pythonw.exe')
    for path in (executable, packages):
        if ntpath.commonpath((root, ntpath.normcase(path))) != root:
            raise ValueError('Login executable and packages must belong to the installation')
    argv[0], argv[5], argv[7] = executable, packages, data
    # GUI-only installation metadata keeps the same explicit entry available after login.
    argv.extend(['--installed-root', _permanent_absolute(installation_root),
                 '--login-pythonw', executable])
    return subprocess.list2cmdline(argv)


def read_login_start(registry):
    """Read the own value through an explicit adapter, e.g. during user save."""
    return registry.read()


def configure_login_start(enabled, launch_argv, *, installation_root, registry=None):
    if type(enabled) is not bool:
        raise TypeError('Login start must be a boolean')
    command = login_command(launch_argv, installation_root) if enabled else None
    registry = CurrentUserRun() if registry is None else registry
    if enabled:
        registry.write(command)
    else:
        registry.remove()
    return command
