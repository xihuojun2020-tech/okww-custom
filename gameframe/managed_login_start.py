# SPDX-License-Identifier: MIT
"""Login points to stable external bootstrap, never to a versioned core."""
import json
import ntpath
from pathlib import Path
import subprocess

from gameframe.login_start import CurrentUserRun, _permanent_absolute


def managed_login_command(installation):
    root = _permanent_absolute(installation['managed_root'])
    pythonw = _permanent_absolute(installation['bootstrap_pythonw'])
    if ntpath.basename(pythonw).lower() != 'pythonw.exe':
        raise ValueError('Managed login requires the stable pythonw.exe')
    if ntpath.normcase(pythonw).startswith(ntpath.normcase(root) + '\\versions\\'):
        raise ValueError('Managed login cannot use a versioned interpreter')
    return subprocess.list2cmdline([pythonw, ntpath.join(root, 'bootstrap.py'), '--managed-root', root])


def configure_managed_login_start(enabled, managed_root, *, registry=None):
    if type(enabled) is not bool:
        raise TypeError('Login start must be a boolean')
    command = None
    if enabled:
        root = Path(managed_root).resolve()
        installation = json.loads((root / 'installation.json').read_text(encoding='utf-8'))
        if installation['managed_root'] != str(root):
            raise ValueError('Managed installation root changed')
        command = managed_login_command(installation)
    registry = CurrentUserRun() if registry is None else registry
    if enabled:
        registry.write(command)
    else:
        registry.remove()
    return command
