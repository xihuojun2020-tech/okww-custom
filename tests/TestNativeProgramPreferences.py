"""Offline preferences and real predictor construction with fake ONNX sessions."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from queue import Queue
from contextlib import nullcontext

from gameframe.devices.windows_preferences import WindowsPreferences
from src.runtime.native_program_preferences import DEFAULTS, NativeProgramPreferences
from src.vision.native_ocr_factory import create_ocr


class Volume:
    def __init__(self, muted): self.muted = muted
    def GetMute(self): return self.muted
    def SetMute(self, muted, context): self.muted = bool(muted)


class PreferencesTests(unittest.TestCase):
    def test_migration_exact_false_and_once(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'configs'
            folder.mkdir()
            legacy = folder / 'Basic Options.json'
            legacy.write_text(json.dumps({'Auto Resize Game Window': False,
                                          'Trigger Interval': 12, 'Use DirectML': 'No'}))
            first = NativeProgramPreferences(root)
            self.assertIs(first.config['Auto Resize Game Window'], False)
            legacy.write_text(json.dumps({'Auto Resize Game Window': True}))
            self.assertIs(NativeProgramPreferences(root).config['Auto Resize Game Window'], False)
            self.assertEqual(first.config['Trigger Interval'], 12)

    def test_audio_restores_initial_and_late_sessions(self):
        volumes = [('a', Volume(False)), ('b', Volume(True))]
        audio = SimpleNamespace(sessions=lambda pid: volumes, close=lambda: None)
        values = dict(DEFAULTS, **{'Mute Game while in Background': True})
        device = SimpleNamespace(target_exited=lambda identity: False,
                                 window=SimpleNamespace(exists=True, _pid=123, _process_created=1),
                                 foreground_pid=lambda: 456, resize_client=lambda *args: None)
        preferences = WindowsPreferences(device, values, supported_ratio=16/9,
                                         min_size=[1280, 720], resolutions=[(1280, 720)], audio=audio)
        preferences.poll()
        self.assertTrue(volumes[0][1].muted)
        volumes.append(('late', Volume(False)))
        preferences.poll()
        device.foreground_pid = lambda: 123
        preferences.poll()
        self.assertEqual([v.muted for _, v in volumes], [False, True, False])
        device.foreground_pid = lambda: 456
        preferences.poll()
        values['Mute Game while in Background'] = False
        preferences.poll()
        self.assertEqual([v.muted for _, v in volumes], [False, True, False])
        self.assertEqual(preferences.original_mutes, {})

    def test_missing_window_is_not_exit(self):
        values = dict(DEFAULTS, **{'Exit App when Game Exits': True})
        device = SimpleNamespace(target_exited=lambda identity: False,
                                 window=SimpleNamespace(exists=False, _pid=123, _process_created=1))
        preferences = WindowsPreferences(device, values, supported_ratio=16/9,
                                         min_size=[1280, 720], resolutions=[])
        self.assertFalse(preferences.poll())
        device.target_exited = lambda identity: True
        self.assertTrue(preferences.poll())

    def test_original_process_identity_survives_window_rebind(self):
        identities = []
        window = SimpleNamespace(exists=False, _pid=123, _process_created=1)
        device = SimpleNamespace(window=window,
                                 target_exited=lambda identity: identities.append(identity) or False)
        preferences = WindowsPreferences(device, dict(DEFAULTS), supported_ratio=16/9,
                                         min_size=[1280, 720], resolutions=[])
        preferences.poll()
        window._pid, window._process_created = 456, 2
        preferences.poll()
        self.assertEqual(identities, [(123, 1), (123, 1)])

    def test_resize_selects_fit_and_invalidates_capture(self):
        from gameframe.devices.windows import WindowsDevice, _WindowBackend
        client, positions = [(0, 0, 1000, 600)], []
        def move(hwnd, z, x, y, width, height, flags):
            positions.append((width, height))
            client[0] = (0, 0, width-16, height-39)
        backend = _WindowBackend.__new__(_WindowBackend)
        backend.user32 = object()
        backend.gui = SimpleNamespace(GetWindowRect=lambda hwnd: (0, 0, 1016, 639),
                                      GetClientRect=lambda hwnd: client[0], SetWindowPos=move)
        backend.api = SimpleNamespace(MonitorFromWindow=lambda *args: 1,
                                      GetMonitorInfo=lambda monitor: {'Work': (0, 0, 1920, 1080)})
        with patch('gameframe.devices.windows._physical_coordinates', return_value=nullcontext()):
            self.assertEqual(backend.resize_client(99, [(2560,1440),(1920,1080),(1600,900)],
                                                   (1280,720),16/9), (1600,900))
        self.assertEqual(positions, [(1616,939)])
        calls = []
        backend.pid = lambda hwnd: 123
        backend.process_created = lambda pid: 1
        backend.resize_client = lambda *args: calls.append('resize') or (1600,900)
        device = WindowsDevice.__new__(WindowsDevice)
        device.hwnd, device._window_backend = 99, backend
        device._window = SimpleNamespace(exists=True, _pid=123, _process_created=1,
                                         do_update_window_size=lambda: calls.append('geometry'))
        device._discard_capture = lambda: calls.append('capture')
        self.assertEqual(device.resize_client([(1600,900)],(1280,720),16/9),(1600,900))
        self.assertEqual(calls, ['capture','resize','geometry'])
        backend.process_created = lambda pid: 2
        with self.assertRaisesRegex(RuntimeError, 'trusted'): device.resize_client([], (1280,720),16/9)
        self.assertEqual(calls, ['capture','resize','geometry'])

    def test_directml_real_predictors_fake_sessions(self):
        calls = []
        def session(model, sess_options, providers):
            calls.append((model, sess_options, providers))
            return SimpleNamespace(get_providers=lambda: providers,
                                   get_inputs=lambda: [SimpleNamespace(name='input')],
                                   get_outputs=lambda: [SimpleNamespace(name='output')],
                                   run=lambda names, feed: ['fixture-result'])
        runtime = SimpleNamespace(get_available_providers=lambda: ['DmlExecutionProvider'],
                                  SessionOptions=SimpleNamespace,
                                  ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL='sequential'),
                                  InferenceSession=session)
        engine = create_ocr({'Use DirectML': 'Yes'}, runtime=runtime)
        self.assertEqual(len(calls), 2)
        for _, options, providers in calls:
            self.assertEqual(providers, ['DmlExecutionProvider'])
            self.assertFalse(options.enable_mem_pattern)
            self.assertEqual(options.execution_mode, 'sequential')
        self.assertFalse(engine.text_detector.is_openvino)
        self.assertEqual(engine.text_recognizer.run(['output'], {}), ['fixture-result'])
        runtime.InferenceSession = lambda *args, **kwargs: SimpleNamespace(
            get_providers=lambda: ['CPUExecutionProvider'])
        with self.assertRaisesRegex(RuntimeError, 'did not activate'):
            create_ocr({'Use DirectML': 'Yes'}, runtime=runtime)

    def test_directml_unavailable_selection(self):
        runtime = SimpleNamespace(get_available_providers=lambda: ['CPUExecutionProvider'])
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            create_ocr({'Use DirectML': 'Yes'}, runtime=runtime)
        with patch('onnxocr.onnx_paddleocr.ONNXPaddleOcr') as constructor:
            create_ocr({'Use DirectML': 'Auto'}, runtime=runtime)
            create_ocr({'Use DirectML': 'No'}, runtime=runtime)
            self.assertEqual(constructor.call_count, 2)
            self.assertTrue(constructor.call_args.kwargs['use_openvino'])

    def test_optional_runtime_absent_keeps_auto_openvino(self):
        with patch('src.vision.native_ocr_factory.importlib.util.find_spec', return_value=None), \
                patch('onnxocr.onnx_paddleocr.ONNXPaddleOcr') as constructor:
            create_ocr({'Use DirectML': 'Auto'})
            self.assertTrue(constructor.call_args.kwargs['use_openvino'])
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                create_ocr({'Use DirectML': 'Yes'})
            self.assertEqual(constructor.call_count, 1)

    def host_fixture(self, poll, paused=False):
        from src.runtime.native_combat_host import NativeCombatHost
        events, waits, releases = [], [], []
        stopped = [False]
        def wait(seconds):
            waits.append(seconds)
            stopped[0] = True
        host = NativeCombatHost.__new__(NativeCombatHost)
        host.notifications = None
        host.uid_overlay = None
        host.executor = SimpleNamespace(nullable_frame=lambda: None)
        host.context = SimpleNamespace(observe_pause=lambda: paused, requests=Queue(),
            stop=SimpleNamespace(is_set=lambda: stopped[0], wait=wait),
            device=SimpleNamespace(poll_preferences=poll, release_all=lambda: releases.append(True)),
            emit=lambda name, **values: events.append((name, values)))
        host.task = SimpleNamespace(native_task_id='fixture', retry_delay=2, enabled=True)
        host.tasks = {}
        host._configuration_service_enables = set()
        host.program_preferences = {'Trigger Interval': 25}
        host._combat_recovery = None
        return host, events, waits, releases

    def test_paused_host_confirmed_exit(self):
        host, events, waits, releases = self.host_fixture(lambda: True, paused=True)
        self.assertEqual(host.run_session(None), {'exit_requested': True, 'target_exited': True})
        self.assertEqual(events, [('target-exited', {})])
        self.assertEqual(len(releases), 1)
        self.assertEqual(waits, [])

    def test_host_delay_milliseconds(self):
        from gameframe.api import Cancelled
        host, events, waits, releases = self.host_fixture(lambda: False)
        with self.assertRaises(Cancelled): host.run_session(None)
        self.assertEqual(waits, [.025])
        self.assertEqual(events, [])

    def test_host_poll_failure_retains_service_intent(self):
        from gameframe.api import Cancelled
        def failed(): raise OSError('fixture preference fault')
        host, events, waits, releases = self.host_fixture(failed)
        errors = []
        host._combat_recovery = errors.append
        with self.assertRaises(Cancelled): host.run_session(None)
        self.assertTrue(host.task.enabled)
        self.assertEqual(len(errors), 1)
        self.assertEqual(waits, [2])
        self.assertEqual(events, [])
        self.assertEqual(len(releases), 1)


if __name__ == '__main__': unittest.main()
