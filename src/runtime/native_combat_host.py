"""Production Wuthering Waves tasks over explicitly owned native services.

One isolated worker owns one data_dir and explicit native production services.
The default native provider imports neither ok-script nor Qt. Legacy bridge mode
is only for separate compatibility workers. OCR and settings are explicit.
"""

import gettext
import importlib
import logging
import time
from collections import deque
from pathlib import Path
from queue import Empty
from types import SimpleNamespace

from gameframe.api import Cancelled
from src.runtime.native_combat_executor import NativeCombatExecutor


logger = logging.getLogger(__name__)


class NativeCombatHost:
    def __init__(self, context, *, coco_path, global_options, ocr_engine,
                 template_matching, window=None, device_identity='replay',
                 supported_ratio=16 / 9, translate=gettext.gettext, pause=None,
                 native=True, task_entry='src.task.AutoCombatTask:AutoCombatTask',
                 registered_tasks=(), ocr_config=None, task_requirements=None):
        from src.runtime import combat_api
        combat_api.configure(native=native, data_dir=context.data_dir)
        from src.runtime.combat_api import Box, Config, TaskDisabledException, WaitFailedException

        self.context = context
        config_root = (Path(context.data_dir) / 'configs').resolve()
        config_root.mkdir(parents=True, exist_ok=True)
        Config.config_folder = str(config_root)
        def load_task(entry):
            module, name = entry.split(':')
            return getattr(importlib.import_module(module), name)

        task_class = load_task(task_entry)
        task_classes = dict.fromkeys((task_class, *(load_task(entry) for entry in registered_tasks)))
        from src.scene.WWScene import WWScene
        from src.task.process_feature import process_feature
        from src.vision.features import FeatureSet
        from src.vision.ocr import OCR
        from src.vision.yolo import EchoDetector
        for production_class in task_classes:
            if hasattr(production_class, 'con_full_size'):
                calibration = Path(production_class.con_full_size.config_file).resolve()
                if calibration.parent != config_root:
                    raise RuntimeError('Production combat was already imported with another data_dir; use an isolated worker')

        echo_detector = EchoDetector(Path(coco_path).resolve().parent / 'echo_model' / 'echo.onnx')
        app = SimpleNamespace(logged_in=False, tr=translate, yolo_detect=echo_detector.detect)
        executor = NativeCombatExecutor(context, scene=WWScene(), pause=pause,
                                        stop_exception=TaskDisabledException,
                                        wait_exception=WaitFailedException)
        executor.debug = False
        executor.text_fix = {}
        executor.ocr_target_height = 0
        executor.ocr_engine = ocr_engine
        executor.config = {'ocr': ocr_config}
        if native:
            from src.runtime.account_runtime_bootstrap import get_account_runtime
            if get_account_runtime() is not None:
                from src.evidence.service import get_evidence_service
                executor.completion_evidence_service = get_evidence_service(
                    root=Path(context.data_dir) / 'okww监控室' / 'CompletionEvidence')
        options = {name: Config(name, defaults, folder=str(config_root))
                   for name, defaults in global_options.items()}
        executor.global_config = SimpleNamespace(get_config=options.__getitem__)
        executor.device_manager = SimpleNamespace(
            hwnd_window=window, supported_ratio=supported_ratio,
            do_refresh=executor.refresh_device, do_start=executor.start_capture,
            get_preferred_device=lambda: {'device': device_identity})
        executor.feature_set = FeatureSet(
            False, str(Path(coco_path).resolve()),
            template_matching['default_horizontal_variance'],
            template_matching['default_vertical_variance'],
            default_threshold=template_matching['default_threshold'],
            hcenter_features=template_matching['hcenter_features'],
            vcenter_features=template_matching['vcenter_features'],
            feature_processor=process_feature, box_factory=Box,
            observer=self._observe_feature)

        host = self
        class HostTaskServices:
            def ocr(self, *args, **kwargs):
                self.executor.check_enabled()
                result = super().ocr(*args, **kwargs) if native else host.ocr.ocr(*args, **kwargs)
                self.executor.check_enabled()
                return result

            @property
            def logged_in(self):
                return self._app.logged_in

            @logged_in.setter
            def logged_in(self, value):
                self._app.logged_in = value

            def screenshot(self, name=None, frame=None, show_box=False, frame_box=None):
                host.save_screenshot(name, self.frame if frame is None else frame)

            def _write_log_images(self, message, images=None, screenshot=False):
                if native:
                    self._log_images(images, screenshot)
                    return
                try:
                    frames = self._notification_images(images, screenshot)
                    for index, frame in enumerate(frames):
                        host.save_screenshot(f'log_{index + 1}', frame)
                except Exception:
                    logger.exception('Unable to save combat diagnostic images')

            def notification(self, message, title=None, error=False, tray=False,
                             show_tab=None, params=None, images=None, screenshot=False):
                self._write_log_images(message, images, screenshot)
                try:
                    context.emit('combat-notification', message=message, title=title, error=error)
                except Exception:
                    logger.exception('Unable to deliver combat notification')

        task_arguments = dict(executor=executor, app=app)
        if native:
            task_arguments.update(ocr_engine=ocr_engine, global_configs=options,
                                  supported_ratio=supported_ratio,
                                  text_fix=executor.text_fix, window=window,
                                  box_factory=Box)
        self.tasks = {}
        for production_class in task_classes:
            # Account/timing policies intentionally inspect the production name.
            adapted_class = type(production_class.__name__, (HostTaskServices, production_class),
                                 {'__module__': production_class.__module__,
                                  '__qualname__': production_class.__qualname__})
            instance = adapted_class(**task_arguments)
            instance._combat_app_services = app
            self.tasks[production_class] = instance
        task = self.tasks[task_class]
        if native:
            executor.set_task_registry(self.tasks)
            for instance in self.tasks.values():
                executor.current_task = instance
                instance.after_init(config=context.config if instance is task else None)
        else:
            for instance in self.tasks.values():
                instance.config = dict(instance.default_config)
                if instance is task:
                    instance.config.update(context.config)
                instance.scene = executor.scene
                instance.on_create()
        executor.current_task = task
        self.task = task
        self.executor = executor
        self.ocr = OCR(executor, ocr_engine, text_fix=executor.text_fix,
                       resolve_box=task.get_box_by_name, box_factory=Box,
                       screenshot_writer=task.screenshot, draw_boxes=task.draw_boxes)
        self.last_result = None
        self._combat_recovery = getattr(task, 'handle_execution_error', None)
        self.task_requirements = task_requirements or {}

    def _select_task(self, task):
        self.task = task
        self.executor.current_task = task
        self._combat_recovery = getattr(task, 'handle_execution_error', None)

    def _set_service(self, task, enabled, *, preference_only=False):
        from src.runtime.native_task import NativeTriggerTask
        from src.task.AutoCombatTask import AutoCombatTask
        if isinstance(task, AutoCombatTask):
            # The request is an explicit user toggle, executed by the input owner.
            task._manual_generation += 1
            task._manual_desired = enabled
            task._retry_at = 0
            task._error_count = 0
            task._capture_waiting = False
            task._enable_pending = enabled
            if preference_only:
                task._enabled = enabled
                task.config['_enabled'] = enabled
                task._emit_state()
                return
            if not enabled:
                NativeTriggerTask.disable(task)
                task._release_combat_inputs()
                task._release_combat_mode()
                task._emit_state()
                return
        if preference_only:
            task._enabled = enabled
            task.config['_enabled'] = enabled
            return
        task.enable() if enabled else task.disable()

    def run_session(self, initial_task_id):
        """Dispatch foreground work and background services on one input owner."""
        from src.runtime.native_task import NativeTriggerTask
        from src.runtime.native_combat_executor import SessionPreempted
        def checkpoint():
            if not self.context.requests.empty():
                raise SessionPreempted('Background service yielded to a user request')
        by_id = {('auto-combat' if cls.__name__ == 'AutoCombatTask' else cls.__name__): task
                 for cls, task in self.tasks.items()}
        if 'auto-combat' in by_id:
            by_id['AutoCombatTask'] = by_id['auto-combat']
        background = self.task
        initial = by_id[initial_task_id]
        initial_request = {'command': 'set-service' if isinstance(initial, NativeTriggerTask)
                           else 'run-task', 'task_id': initial_task_id, 'enabled': True}
        deferred_tasks = deque()
        deferred_enables = set()
        while True:
            paused = self.context.observe_pause()
            stopped = self.context.stop.is_set()
            preference_only = paused or stopped
            if initial_request is not None:
                request, initial_request = initial_request, None
            elif deferred_tasks and not preference_only:
                request = deferred_tasks.popleft()
            else:
                try:
                    request = self.context.requests.get_nowait()
                except Empty:
                    request = None
            if request is not None:
                task_id = request.get('task_id')
                try:
                    command = request.get('command')
                    if command not in ('run-task', 'set-service'):
                        raise ValueError('Unknown session command: ' + str(command))
                    task = by_id[task_id]
                    service = isinstance(task, NativeTriggerTask)
                    if command == 'set-service' and not service:
                        raise ValueError(f'{task_id} is not a background service')
                    if command == 'run-task' and service:
                        raise ValueError(f'{task_id} is a background service')
                    config = request.get('config', {})
                    if not isinstance(config, dict):
                        raise ValueError('Session task config must be a JSON object')
                    if command == 'set-service' and type(request.get('enabled')) is not bool:
                        raise ValueError('Session service enabled must be a boolean')
                    requirement_id = 'auto-combat' if task_id == 'AutoCombatTask' else task_id
                    missing = set(self.task_requirements.get(requirement_id, ())) - self.context.device.capabilities
                    if missing:
                        raise RuntimeError('Missing device capabilities: ' + ', '.join(sorted(missing)))
                    if command == 'run-task' and preference_only:
                        if not stopped:
                            deferred_tasks.append(request)
                        continue
                    self._select_task(task)
                    task.config.update(config)
                    if command == 'set-service':
                        self._set_service(task, request['enabled'], preference_only=preference_only)
                        if preference_only and request['enabled']:
                            deferred_enables.add(task)
                        else:
                            deferred_enables.discard(task)
                    else:
                        result = self.run_once()
                        self.context.emit('session-task-finished', task_id=task_id, result=result,
                                          info=dict(task.info))
                        if isinstance(result, dict) and result.get('exit_requested'):
                            return result
                except Cancelled:
                    if self.context.stop.is_set():
                        continue  # Save already-received toggles before leaving the session.
                    raise
                except Exception as error:
                    logger.exception('Session task failed: %s', task_id)
                    self.context.emit('session-task-failed', task_id=task_id,
                                      error=f'{type(error).__name__}: {error}')
                finally:
                    if not preference_only:
                        self.context.device.release_all()
                    self._select_task(background)
                continue
            if stopped:
                raise Cancelled('Task stopped')
            if paused:
                self.context.stop.wait(.1)
                continue
            for task in self.tasks.values():
                if not isinstance(task, NativeTriggerTask) or not task.enabled:
                    continue
                self._select_task(task)
                try:
                    self.executor.session_checkpoint = checkpoint
                    if task in deferred_enables:
                        self._set_service(task, True)
                        deferred_enables.discard(task)
                    if task.should_trigger():
                        self.last_result = self.poll()
                except SessionPreempted:
                    break
                except Cancelled:
                    if self.context.stop.is_set() or self.executor.paused:
                        break
                    raise
                except Exception as error:
                    if self._combat_recovery is not None:
                        self._combat_recovery(error)
                    else:
                        logger.exception('Background service failed: %s', type(task).__name__)
                        self.context.emit('session-task-failed', task_id=type(task).__name__,
                                          error=f'{type(error).__name__}: {error}')
                finally:
                    self.executor.session_checkpoint = None
                    self.context.device.release_all()
                    self._select_task(background)
            self.context.stop.wait(.1)

    def run_once(self):
        """Execute original foreground lifecycle within the caller's input scope."""
        from src.runtime.combat_api import TaskDisabledException
        task = self.task
        previous_pause_policy = self.executor.wait_on_pause
        self.executor.wait_on_pause = True
        task._enabled = True
        task.running = True
        task.start_time = time.time()
        try:
            self.executor.reset_scene()
            before_run = getattr(task, 'before_run', None)
            if before_run is not None:
                before_run()
            result = task.run()
        except TaskDisabledException as error:
            raise Cancelled(str(error)) from error
        finally:
            try:
                after_run = getattr(task, 'after_run', None)
                if after_run is not None:
                    after_run()
            finally:
                try:
                    task.on_destroy()
                finally:
                    task.running = False
                    task._enabled = False
                    self.executor.wait_on_pause = previous_pause_policy
        self.context.check_stop()
        if task.exit_after_task or task.config.get('Exit After Task'):
            self.context.device.stop_target()
            self.context.check_stop()
            return {'exit_requested': True, 'result': result}
        return result

    def save_screenshot(self, name, image):
        from src.runtime.native_screenshots import save_native_screenshot
        path = save_native_screenshot(self.context.data_dir, name, image)
        self.context.emit('combat-screenshot', path=str(path))
        return path

    def _observe_feature(self, event, **payload):
        if event == 'screenshot' and payload['save']:
            self.save_screenshot(payload['name'], payload['image'])
        else:
            self.context.emit('combat-vision', vision_event=event, name=payload.get('name'))

    def poll(self):
        from src.runtime.combat_api import TaskDisabledException
        self.task.start_time = time.time()
        self.task.running = True
        try:
            self.executor.reset_scene()
            result = self.task.run()
            return {'in_combat' if self._combat_recovery is not None else 'handled': bool(result),
                    'enabled': self.task.enabled}
        except TaskDisabledException as error:
            raise Cancelled(str(error)) from error
        finally:
            self.task.running = False

    def run_service(self):
        """Run inside the caller's single input-owner scope without changing intent."""
        while self.task.enabled:
            self.context.check_stop()
            if self.executor.paused:
                self.context.sleep(.1)
                continue
            if not self.task.should_trigger():
                delay = self.task.retry_delay if self._combat_recovery is not None else 0
                self.context.sleep(min(.1, delay or self.task.trigger_interval))
                continue
            try:
                self.last_result = self.poll()
            except Cancelled:
                # A background poll interrupted by pause resumes with the same task.
                if self.context.stop.is_set() or not self.executor.paused:
                    raise
            except Exception as error:
                if self._combat_recovery is None:
                    raise
                self._combat_recovery(error)
        return {'status': 'skipped',
                'reason': 'combat-disabled' if self._combat_recovery is not None else 'service-disabled'}
