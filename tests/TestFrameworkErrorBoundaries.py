"""Exercise production method bodies without importing device/account bootstrap."""
import ast
import importlib
import tempfile
from contextlib import contextmanager
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


from src.runtime.framework_overlay import CustomFrameworkFinder, install_framework_overlay

ROOT = Path(__file__).resolve().parents[1]


def method(path, name, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8-sig'))
    node = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


@contextmanager
def overlay_process():
    # A synthetic installed package proves routing without importing real ok.
    with tempfile.TemporaryDirectory() as temp, patch.dict(sys.modules), \
            patch.object(sys, 'meta_path', [finder for finder in sys.meta_path
                if not isinstance(finder, CustomFrameworkFinder)]), \
            patch.object(sys, 'path', list(sys.path)), patch.object(sys, 'dont_write_bytecode', True):
        for name in tuple(sys.modules):
            if name == 'ok' or name.startswith('ok.'):
                del sys.modules[name]
        root = Path(temp).resolve()
        custom = root / 'custom_ok' / 'ok'
        base = root / 'site-packages' / 'ok'
        custom.mkdir(parents=True)
        base.mkdir(parents=True)
        (base / '__init__.py').write_text('', encoding='utf-8')
        (base / 'base_probe.py').write_text("VALUE = 'base'", encoding='utf-8')
        (base / 'overlay_probe.py').write_text("VALUE = 'old'", encoding='utf-8')
        (custom / 'overlay_probe.py').write_text("VALUE = 'custom'", encoding='utf-8')
        sys.path.insert(0, str(base.parent))
        yield root


class TestFrameworkErrorBoundaries(unittest.TestCase):
    def test_overlay_loads_only_present_overrides_and_leaves_base_sources_unchanged(self):
        with overlay_process() as root:
            base = root / 'site-packages' / 'ok'
            sources = {path: path.read_bytes() for path in base.rglob('*.py')}
            finder = install_framework_overlay(root)
            overridden = importlib.import_module('ok.overlay_probe')
            inherited = importlib.import_module('ok.base_probe')
            self.assertEqual(overridden.VALUE, 'custom')
            self.assertEqual(inherited.VALUE, 'base')
            self.assertEqual(Path(overridden.__file__), root / 'custom_ok/ok/overlay_probe.py')
            self.assertEqual(Path(inherited.__file__), base / 'base_probe.py')
            self.assertIs(install_framework_overlay(root), finder)
            self.assertEqual(sum(item is finder for item in sys.meta_path), 1)
            self.assertEqual(sources, {path: path.read_bytes() for path in base.rglob('*.py')})
            self.assertIsNone(finder.find_spec('src.account_repository'))

    def test_overlay_rejects_late_installation_and_other_source_root(self):
        with overlay_process() as root:
            sys.modules['ok'] = SimpleNamespace()
            with self.assertRaisesRegex(RuntimeError, 'before importing ok'):
                install_framework_overlay(root)
            del sys.modules['ok']
            install_framework_overlay(root)
            with self.assertRaisesRegex(RuntimeError, 'different source roots'):
                install_framework_overlay(root / 'another')

    def test_overlay_missing_or_unreadable_source_reports_real_failure(self):
        with overlay_process() as root:
            with self.assertRaises(FileNotFoundError):
                install_framework_overlay(root / 'missing')
            failure = PermissionError('synthetic source IO failure')
            with patch.object(Path, 'stat', side_effect=failure), self.assertRaises(PermissionError) as caught:
                install_framework_overlay(root)
            self.assertIs(caught.exception, failure)
            finder = install_framework_overlay(root)
            with patch.object(Path, 'stat', side_effect=failure), self.assertRaises(PermissionError) as caught:
                finder.find_spec('ok.overlay_probe')
            self.assertIs(caught.exception, failure)

    def test_production_sync_hook_installs_overlay_without_importing_ok(self):
        install = Mock()
        sync = method('main.py', '_sync_custom_ok', {'Path': Path, '__file__': str(ROOT/'main.py')})
        with patch.dict(sys.modules, {'src.runtime.framework_overlay': SimpleNamespace(install_framework_overlay=install)}):
            sync()
        install.assert_called_once_with(ROOT)

    def test_yolo_inference_failure_is_not_empty_detection(self):
        for file, backend in (('OnnxYolo8Detect.py', 'onnx'), ('OpenVinoYolo8Detect.py', 'openvino')):
            with self.subTest(backend=backend):
                detect = method('src/' + file, 'detect', {'sort_boxes': lambda value: value})
                failure = RuntimeError('synthetic inference failure')
                task = SimpleNamespace(_preprocess=Mock(return_value=('pixels', (0, 0))),
                    session=Mock(), input_name='input', output_name='output',
                    compiled_model=Mock(), input_layer='input', output_layer='output', _postprocess=Mock())
                if backend == 'onnx':
                    task.session.run.side_effect = failure
                else:
                    task.compiled_model.side_effect = failure
                with self.assertRaises(RuntimeError) as caught:
                    detect(task, SimpleNamespace(shape=(2, 2, 3)))
                self.assertIs(caught.exception, failure)
                task._postprocess.assert_not_called()

    def test_yolo_real_empty_outputs_remain_empty(self):
        import cv2
        import numpy as np
        for file in ('OnnxYolo8Detect.py', 'OpenVinoYolo8Detect.py'):
            with self.subTest(backend=file):
                postprocess = method('src/' + file, '_postprocess', {'cv2': cv2, 'np': np})
                task = SimpleNamespace(preprocess_target_h=640, preprocess_target_w=640,
                    input_height=640, input_width=640, iou_threshold=.45)
                outputs = np.zeros((1, 5, 1), dtype=np.float32)
                if file.startswith('Onnx'):
                    outputs = [outputs]
                self.assertEqual(postprocess(task, outputs, (0, 0), (640, 640), .5, -1), [])

    def test_after_run_failure_releases_context_and_keeps_background_execution(self):
        for failure_kind in ('ordinary', 'reporting', 'stopped', 'finished'):
            with self.subTest(failure_kind=failure_kind):
                stop = threading.Event()
                logger = Mock()
                if failure_kind == 'reporting':
                    logger.error.side_effect = RuntimeError('diagnostic hook failed')
                exceptions = {name: type(name, (Exception,), {}) for name in (
                    'TaskDisabledException', 'FinishedException', 'CaptureException', 'HotkeyConfigException')}
                framework = SimpleNamespace(_service_diagnostic_capture=Mock())
                execute = method('custom_ok/ok/task/TaskExecutor.py', 'execute', {
                    'TaskExecutor': framework, 'logger': logger, 'communicate': Mock(),
                    'prevent_sleeping': Mock(), 'time': time, **exceptions})
                cleanup_failure = (exceptions['FinishedException']() if failure_kind == 'finished' else
                    exceptions['TaskDisabledException']() if failure_kind == 'stopped' else
                    RuntimeError('cleanup failed'))
                foreground = SimpleNamespace(name='foreground', running=False, config={},
                    run=Mock(), disable=Mock(), exit_after_task=False,
                    after_run=Mock(side_effect=cleanup_failure),
                    _release_combat_inputs=Mock())
                background = SimpleNamespace(name='combat', running=False, persistent_enabled=True,
                    config={'_enabled': True}, enabled=True, run=Mock(side_effect=lambda: stop.set() or True),
                    _release_combat_inputs=Mock())
                owner = SimpleNamespace(exit_event=stop, paused=False, _get_wake_version=lambda: 0,
                    next_task=Mock(side_effect=[(foreground, False, False), (background, False, True)]),
                    _last_frame_time=time.time(), _frame=object(), current_task=None,
                    reset_scene=Mock(), destroy=Mock(), _account_feature_run='bound')
                execute(owner)
                if failure_kind == 'finished':
                    background.run.assert_not_called()
                else:
                    background.run.assert_called_once()
                self.assertTrue(background.enabled)
                self.assertTrue(background.config['_enabled'])
                foreground._release_combat_inputs.assert_called_once()
                owner.destroy.assert_called_once()
                self.assertIsNone(owner._account_feature_run)
                self.assertIsNone(owner.current_task)
                self.assertFalse(foreground.running)
                self.assertEqual(logger.error.call_count, int(failure_kind in ('ordinary', 'reporting')))

    def test_application_and_exact_task_share_bootstrap_and_return_runtime_result(self):
        for selected in (None, 'DailyTask', 'AutoCombatTask'):
            with self.subTest(task=selected):
                events = []
                def note(name):
                    return lambda *args, **kwargs: events.append(name)
                result = object()
                app = SimpleNamespace(start=Mock(return_value=result), run_task=Mock(return_value=result))
                fake_sys = SimpleNamespace(argv=['main.py', '--headless'], exit=Mock(side_effect=SystemExit))
                namespace = {'__file__': str(ROOT/'main.py'), 'Path': Path,
                    'os': SimpleNamespace(path=os.path, chdir=Mock()), 'sys': fake_sys,
                    '_ensure_single_instance': lambda: True, '_sync_custom_ok': note('sync'),
                    '_setup_proxy': note('proxy'), 'atexit': SimpleNamespace(register=note('cleanup')),
                    '_exit_cleanup': Mock(), '_find_owned_launcher': lambda: None,
                    '_create_ok': lambda _: events.append('construct') or app,
                    '_report_startup_error': Mock()}
                run = method('main.py', 'run_application', namespace)
                modules = {
                    'config': SimpleNamespace(version='synthetic', config={}),
                    'src.runtime.storage_startup_ui': SimpleNamespace(prepare_storage=note('storage')),
                    'src.upstream_check': SimpleNamespace(check_upstream=Mock()),
                    'threading': SimpleNamespace(Thread=Mock()),
                    'src.runtime.diagnostic_lifecycle': SimpleNamespace(start_diagnostics=note('diagnostics'),
                        attach_framework_hooks=note('attach'), record_crash=Mock()),
                    'src.runtime.account_runtime_bootstrap': SimpleNamespace(initialize_account_runtime=note('preflight')),
                }
                with patch.dict(sys.modules, modules):
                    self.assertIs(run(selected), result)
                self.assertEqual(events, ['sync', 'storage', 'proxy', 'cleanup',
                    'diagnostics', 'preflight', 'construct', 'attach'])
                self.assertEqual(fake_sys.argv, ['main.py', '--headless'])
                if selected is None:
                    app.start.assert_called_once()
                    app.run_task.assert_not_called()
                else:
                    app.run_task.assert_called_once_with(selected)
                    app.start.assert_not_called()
                namespace['_report_startup_error'].assert_not_called()

    def test_sync_failure_is_reported_before_runtime_construction(self):
        failure = PermissionError('synthetic copy failure')
        namespace = {'__file__': str(ROOT/'main.py'), 'Path': Path,
            'os': SimpleNamespace(path=os.path, chdir=Mock()),
            'sys': SimpleNamespace(exit=Mock(side_effect=lambda code: (_ for _ in ()).throw(SystemExit(code)))),
            '_ensure_single_instance': lambda: True,
            '_sync_custom_ok': Mock(side_effect=failure), '_report_startup_error': Mock(), '_create_ok': Mock()}
        run = method('main.py', 'run_application', namespace)
        with patch.dict(sys.modules, {'src.runtime.storage_startup_ui': SimpleNamespace(prepare_storage=Mock())}), \
                self.assertRaises(SystemExit) as caught:
            run()
        self.assertEqual(caught.exception.code, 1)
        namespace['_report_startup_error'].assert_called_once_with(failure)
        namespace['_create_ok'].assert_not_called()

    def test_pre_set_stop_skips_all_production_initialization(self):
        stop = threading.Event()
        stop.set()
        initialize = Mock()
        run = method('main.py', 'run_application', {'_ensure_single_instance': initialize})
        self.assertIsNone(run('AutoCombatTask', stop_event=stop))
        initialize.assert_not_called()

    def test_controller_stop_quits_waits_for_cleanup_and_preserves_combat_intent(self):
        for stop_stage in ('constructor', 'running', 'natural-return'):
            with self.subTest(stage=stop_stage):
                stop = threading.Event()
                exited = threading.Event()
                result = object()
                app = SimpleNamespace(exit_event=exited, task_executor=SimpleNamespace(thread=Mock()),
                    config={'_enabled': True})
                app.quit = Mock(side_effect=exited.set)
                def run_task(selected):
                    if stop_stage == 'running':
                        stop.set()
                        self.assertTrue(exited.wait(2), 'stop bridge did not call production quit')
                    return result
                app.run_task = Mock(side_effect=run_task)
                def create(config):
                    if stop_stage == 'constructor':
                        stop.set()
                    return app
                namespace = {'__file__': str(ROOT/'main.py'), 'Path': Path,
                    'os': SimpleNamespace(path=os.path, chdir=Mock()),
                    'sys': SimpleNamespace(exit=Mock(side_effect=SystemExit)),
                    '_ensure_single_instance': lambda: True, '_sync_custom_ok': Mock(),
                    '_setup_proxy': Mock(), 'atexit': SimpleNamespace(register=Mock()),
                    '_exit_cleanup': Mock(), '_find_owned_launcher': lambda: None,
                    '_create_ok': create, '_report_startup_error': Mock()}
                namespace['_watch_application_stop'] = method('main.py', '_watch_application_stop', {})
                run = method('main.py', 'run_application', namespace)
                modules = {
                    'config': SimpleNamespace(version='synthetic', config={}),
                    'src.runtime.storage_startup_ui': SimpleNamespace(prepare_storage=Mock()),
                    'src.upstream_check': SimpleNamespace(check_upstream=Mock()),
                    'src.runtime.diagnostic_lifecycle': SimpleNamespace(start_diagnostics=Mock(),
                        attach_framework_hooks=Mock(), record_crash=Mock()),
                    'src.runtime.account_runtime_bootstrap': SimpleNamespace(initialize_account_runtime=Mock()),
                }
                with patch.dict(sys.modules, modules):
                    returned = run('AutoCombatTask', stop_event=stop)
                self.assertTrue(app.config['_enabled'])
                if stop_stage == 'constructor':
                    self.assertIsNone(returned)
                    app.run_task.assert_not_called()
                    app.quit.assert_called_once()
                else:
                    self.assertIs(returned, result)
                    app.run_task.assert_called_once_with('AutoCombatTask')
                    if stop_stage == 'running':
                        app.quit.assert_called_once()
                        app.task_executor.thread.join.assert_called_once_with()
                    else:
                        app.quit.assert_not_called()
                        app.task_executor.thread.join.assert_not_called()
                namespace['_report_startup_error'].assert_not_called()

    def test_executor_stop_uses_finished_exception_in_frame_and_sleep(self):
        finished = type('FinishedException', (Exception,), {})
        stopped = threading.Event()
        stopped.set()
        task = SimpleNamespace(exit_event=stopped, paused=False, debug_mode=False,
            reset_scene=Mock(), check_enabled=Mock(), current_task=None)
        namespace = {'FinishedException': finished, 'logger': Mock(), 'time': time,
            'TaskExecutor': SimpleNamespace(_service_diagnostic_capture=Mock())}
        frame = method('custom_ok/ok/task/TaskExecutor.py', 'frame', namespace)
        sleep = method('custom_ok/ok/task/TaskExecutor.py', 'sleep', namespace)
        with self.assertRaises(finished):
            frame.fget(task)
        with self.assertRaises(finished):
            sleep(task, .1)

    def test_executor_finished_stop_releases_inputs_and_destroys_without_disabling(self):
        stopped = threading.Event()
        finished = type('FinishedException', (Exception,), {})
        def stop_run():
            stopped.set()
            raise finished()
        task = SimpleNamespace(name='combat', running=False, config={'_enabled': True},
            run=stop_run, disable=Mock(), _release_combat_inputs=Mock())
        execute = method('custom_ok/ok/task/TaskExecutor.py', 'execute', {
            'TaskExecutor': SimpleNamespace(_service_diagnostic_capture=Mock()),
            'logger': Mock(), 'communicate': Mock(), 'time': time, 'prevent_sleeping': Mock(),
            'FinishedException': finished,
            'TaskDisabledException': type('TaskDisabledException', (Exception,), {}),
            'CaptureException': type('CaptureException', (Exception,), {}),
            'HotkeyConfigException': type('HotkeyConfigException', (Exception,), {})})
        executor = SimpleNamespace(exit_event=stopped, paused=False, _get_wake_version=lambda: 0,
            next_task=lambda: (task, False, True), _last_frame_time=time.time(), _frame=object(),
            current_task=None, destroy=Mock())
        execute(executor)
        task._release_combat_inputs.assert_called_once()
        task.disable.assert_not_called()
        self.assertTrue(task.config['_enabled'])
        executor.destroy.assert_called_once()


if __name__ == '__main__':
    unittest.main()
