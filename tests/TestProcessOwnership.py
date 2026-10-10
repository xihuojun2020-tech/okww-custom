"""Forced cleanup uses declared process identities, never executable names."""

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import psutil

from gameframe.process_ownership import (PROTECTED_PROCESSES_ENV, protected_process_identities,
                                         register_device_process)
from tests.TestWindowsLaunch import COMMAND, TARGET, Process
from gameframe.devices.windows import WindowsDevice
from tests.TestWindowsWindow import Platform


class TestProcessOwnership(unittest.TestCase):
    def test_device_registers_launcher_and_observed_child_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'processes.json'
            path.write_text('[]', encoding='utf-8')
            platform = Platform()
            platform.handles = {201: 11}
            child = Process(11, TARGET)
            launcher = Process(10, COMMAND[0], [child])
            device = WindowsDevice(window_backend=platform, launch_command=COMMAND,
                                   target_executable=TARGET, process_factory=Mock(return_value=launcher),
                                   launch_factory=Mock(return_value=SimpleNamespace(pid=10)))
            with patch.dict(os.environ, {PROTECTED_PROCESSES_ENV: str(path)}):
                device.prepare(threading.Event())
                register_device_process(child)
            self.assertEqual(json.loads(path.read_text()),
                             [{'pid': 10, 'created': 1010}, {'pid': 11, 'created': 1011}])
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_reused_pid_is_not_protected_and_current_descendants_are(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'processes.json'
            path.write_text(json.dumps([{'pid': 10, 'created': 1000},
                                        {'pid': 11, 'created': 1100}]))
            reused = Mock(pid=10)
            reused.create_time.return_value = 2000
            live = Mock(pid=11)
            live.create_time.return_value = 1100
            child = Mock(pid=12)
            child.create_time.return_value = 1200
            exited = Mock(pid=13)
            exited.create_time.side_effect = psutil.NoSuchProcess(13)
            live.children.return_value = [exited, child]
            with patch('gameframe.process_ownership.psutil.Process', side_effect=[reused, live]):
                self.assertEqual(protected_process_identities(path), {(11, 1100), (12, 1200)})
            reused.children.assert_not_called()


if __name__ == '__main__':
    unittest.main()
