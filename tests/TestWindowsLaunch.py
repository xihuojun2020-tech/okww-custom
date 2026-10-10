"""Selected-process launch/rebind with mocked Windows, process and WGC APIs."""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import psutil

from gameframe.api import Cancelled, Frame
from gameframe.devices.windows import WindowsDevice
from tests.TestGameFrameDevices import FakeCapture, FakeGeometry
from tests.TestWindowsWindow import Platform


TARGET = r'C:\Games\Wuthering\game.exe'
COMMAND = [r'C:\Games\Wuthering\launcher.exe', '--run-game']


class Process:
    def __init__(self, pid, executable, children=None):
        self.pid, self.executable = pid, executable
        self.running = True
        self.child_list = children or []

    def children(self, recursive=True):
        if not self.running:
            raise psutil.NoSuchProcess(self.pid)
        return self.child_list

    def is_running(self):
        return self.running

    def create_time(self):
        return 1000 + self.pid

    def exe(self):
        return self.executable


class TestWindowsLaunch(unittest.TestCase):
    def make_device(self, *, handles=None, launcher=None):
        platform = Platform()
        child = Process(11, TARGET)
        launcher = launcher or Process(10, COMMAND[0], [child])
        factory = Mock(return_value=SimpleNamespace(pid=10))
        captures, capture_hwnds = [], []
        def capture_factory(**values):
            capture = FakeCapture()
            captures.append(capture)
            capture_hwnds.append(values['window_hwnd'])
            return capture
        device = WindowsDevice(100, window_backend=platform, process_factory=Mock(return_value=launcher),
                               launch_factory=factory, launch_command=COMMAND, target_executable=TARGET,
                               capture_factory=capture_factory, geometry=FakeGeometry())
        window = device.window
        platform.handles = handles if handles is not None else {201: 11}
        return device, platform, window, launcher, child, factory, captures, capture_hwnds

    def test_launch_rebind_stops_old_wgc_discards_frame_and_keeps_window_object(self):
        device, platform, window, launcher, child, launch, captures, hwnds = self.make_device()
        old_control = Mock()
        device._control, device._capture = old_control, object()
        device._latest = Frame(1, np.zeros((10, 20, 3), dtype=np.uint8), 1)
        self.assertTrue(device.start_target(threading.Event(), timeout=0))
        launch.assert_called_once_with(COMMAND)
        old_control.stop.assert_called_once_with()
        old_control.wait.assert_called_once_with()
        self.assertIs(device.window, window)
        self.assertEqual(device.hwnd, 201)
        self.assertEqual(window._pid, 11)
        self.assertIsNone(device._latest)
        self.assertTrue(device.start_capture())
        self.assertEqual(hwnds, [201])
        captures[-1].emit(np.ones((24, 32, 4), dtype=np.uint8))
        frame = device.next_frame(timeout=0)
        self.assertEqual(frame.image.shape, (24, 32, 3))

    def test_known_child_remains_trusted_after_launcher_exits(self):
        device, platform, window, launcher, child, launch, captures, hwnds = self.make_device(handles={})
        count = [0]
        def enumerate_child(recursive=True):
            count[0] += 1
            if count[0] == 2:
                launcher.running = False
                platform.handles = {201: 11}
            return []
        child.children = enumerate_child
        self.assertTrue(device.start_target(threading.Event(), timeout=1))
        self.assertEqual(device.hwnd, 201)
        self.assertEqual(window._pid, 11)
        launch.assert_called_once()

    def test_other_processes_and_wrong_executable_do_not_supply_candidates(self):
        device, platform, window, launcher, child, launch, captures, hwnds = self.make_device(handles={201: 99})
        with self.assertRaisesRegex(TimeoutError, 'unique target window'):
            device.start_target(threading.Event(), timeout=0)
        platform.handles = {201: 11}
        child.executable = r'C:\Unrelated\game.exe'
        with self.assertRaisesRegex(TimeoutError, 'unique target window'):
            device.start_target(threading.Event(), timeout=0)
        self.assertEqual(device.hwnd, 100)

    def test_multiple_matching_windows_are_explicit_failure(self):
        device, *_ = self.make_device(handles={201: 11, 202: 11})
        with self.assertRaisesRegex(RuntimeError, 'Multiple windows'):
            device.start_target(threading.Event(), timeout=0)
        self.assertEqual(device.hwnd, 100)

    def test_stop_before_or_during_wait_never_rebinds(self):
        device, platform, window, launcher, child, launch, *_ = self.make_device(handles={})
        stop = threading.Event()
        stop.set()
        with self.assertRaises(Cancelled):
            device.start_target(stop)
        launch.assert_not_called()
        stop.clear()
        def launched(command):
            stop.set()
            return SimpleNamespace(pid=10)
        device._launch_factory = launched
        with self.assertRaises(Cancelled):
            device.start_target(stop)
        self.assertEqual(device.hwnd, 100)

    def test_unrecorded_launcher_exit_is_explicit_failure(self):
        device, *_ = self.make_device()
        device._process_factory.side_effect = psutil.NoSuchProcess(10)
        with self.assertRaisesRegex(RuntimeError, 'before its process family'):
            device.start_target(threading.Event(), timeout=0)

    def test_launcher_disappears_before_observing_children_is_explicit_failure(self):
        launcher = Process(10, COMMAND[0])
        launcher.running = False
        device, *_ = self.make_device(launcher=launcher)
        with self.assertRaisesRegex(RuntimeError, 'before its process family'):
            device.start_target(threading.Event(), timeout=0)

    def test_refresh_rejects_reused_live_window_and_process(self):
        device, platform, window, *_ = self.make_device(handles={100: 99})
        with self.assertRaisesRegex(RuntimeError, 'identity has been reused'):
            device.refresh_target()
        platform.handles = {100: 7}
        platform.process_created = Mock(return_value=2000)
        with self.assertRaisesRegex(RuntimeError, 'identity has been reused'):
            device.refresh_target()
        self.assertEqual(window._pid, 7)

    def test_missing_launch_configuration_is_not_success(self):
        device = WindowsDevice(100)
        with self.assertRaisesRegex(RuntimeError, 'requires launch_command'):
            device.start_target(threading.Event())

    def test_prepare_launches_without_prior_hwnd_and_binds_first_window(self):
        platform = Platform()
        platform.handles = {201: 11}
        child = Process(11, TARGET)
        launch = Mock(return_value=SimpleNamespace(pid=10))
        device = WindowsDevice(window_backend=platform, launch_factory=launch,
                               process_factory=Mock(return_value=Process(10, COMMAND[0], [child])),
                               launch_command=COMMAND, target_executable=TARGET)
        device.prepare(threading.Event())
        self.assertEqual(device.hwnd, 201)
        self.assertEqual(device.window._pid, 11)
        launch.assert_called_once_with(COMMAND)
        device.prepare(threading.Event())
        launch.assert_called_once()

    def test_prepare_cancelled_before_initial_launch_does_not_start_process(self):
        launch = Mock()
        device = WindowsDevice(0, launch_factory=launch, launch_command=COMMAND,
                               target_executable=TARGET)
        stop = threading.Event()
        stop.set()
        with self.assertRaises(Cancelled):
            device.prepare(stop)
        launch.assert_not_called()
        self.assertIsNone(device._window)

    def test_missing_hwnd_and_launch_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'positive HWND or complete launch'):
            WindowsDevice()


if __name__ == '__main__':
    unittest.main()
