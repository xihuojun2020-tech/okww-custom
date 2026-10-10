"""Production AutoCombat over native services, with an explicit legacy bridge mode.

One isolated worker owns one data_dir and explicit native production services.
The default native provider imports neither ok-script nor Qt. Legacy bridge mode
is only for separate compatibility workers. OCR and settings are explicit.
"""

import gettext
import logging
from pathlib import Path
from types import SimpleNamespace

import cv2

from gameframe.api import Cancelled
from src.runtime.native_combat_executor import NativeCombatExecutor


logger = logging.getLogger(__name__)


class NativeCombatHost:
    def __init__(self, context, *, coco_path, global_options, ocr_engine,
                 template_matching, window=None, device_identity='replay',
                 supported_ratio=16 / 9, translate=gettext.gettext, pause=None,
                 native=True):
        from src.runtime import combat_api
        combat_api.configure(native=native, data_dir=context.data_dir)
        from src.runtime.combat_api import Box, Config, TaskDisabledException, WaitFailedException

        self.context = context
        config_root = (Path(context.data_dir) / 'configs').resolve()
        config_root.mkdir(parents=True, exist_ok=True)
        Config.config_folder = str(config_root)
        # The class-body calibration Config must be created in this worker's root.
        from src.task.AutoCombatTask import AutoCombatTask
        from src.scene.WWScene import WWScene
        from src.task.process_feature import process_feature
        from src.vision.features import FeatureSet
        from src.vision.ocr import OCR
        calibration = Path(AutoCombatTask.con_full_size.config_file).resolve()
        if calibration.parent != config_root:
            raise RuntimeError('Production combat was already imported with another data_dir; use an isolated worker')

        app = SimpleNamespace(logged_in=False, tr=translate)
        executor = NativeCombatExecutor(context, scene=WWScene(), pause=pause,
                                        stop_exception=TaskDisabledException,
                                        wait_exception=WaitFailedException)
        executor.debug = False
        executor.text_fix = {}
        executor.ocr_target_height = 0
        options = {name: Config(name, defaults, folder=str(config_root))
                   for name, defaults in global_options.items()}
        executor.global_config = SimpleNamespace(get_config=options.__getitem__)
        executor.device_manager = SimpleNamespace(
            hwnd_window=window, supported_ratio=supported_ratio,
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
        class HeadlessAutoCombatTask(AutoCombatTask):
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
        task = HeadlessAutoCombatTask(**task_arguments)
        task._combat_app_services = app
        task.config = dict(task.default_config)
        task.config.update(context.config)
        task.scene = executor.scene
        task.on_create()
        executor.current_task = task
        self.task = task
        self.executor = executor
        self.ocr = OCR(executor, ocr_engine, text_fix=executor.text_fix,
                       resolve_box=task.get_box_by_name, box_factory=Box,
                       screenshot_writer=task.screenshot, draw_boxes=task.draw_boxes)
        self.last_result = None

    def save_screenshot(self, name, image):
        if name is None:
            raise ValueError('screenshot name cannot be None')
        root = (Path(self.context.data_dir) / 'okww监控室').resolve()
        path = (root / f'{name}.png').resolve()
        if not path.is_relative_to(root):
            raise ValueError('Screenshot name leaves the evidence directory')
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded, payload = cv2.imencode('.png', image)
        if not encoded:
            raise RuntimeError('Unable to encode screenshot')
        payload.tofile(path)
        self.context.emit('combat-screenshot', path=str(path))
        return path

    def _observe_feature(self, event, **payload):
        if event == 'screenshot' and payload['save']:
            self.save_screenshot(payload['name'], payload['image'])
        else:
            self.context.emit('combat-vision', vision_event=event, name=payload.get('name'))

    def poll(self):
        from src.runtime.combat_api import TaskDisabledException
        self.task.running = True
        try:
            self.executor.reset_scene()
            result = self.task.run()
            return {'in_combat': bool(result), 'enabled': self.task.enabled}
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
                self.context.sleep(min(.1, self.task.retry_delay or self.task.trigger_interval))
                continue
            try:
                self.last_result = self.poll()
            except Cancelled:
                # A background poll interrupted by pause resumes with the same task.
                self.context.check_stop()
                if not self.executor.paused:
                    raise
            except Exception as error:
                self.task.handle_execution_error(error)
        return {'status': 'skipped', 'reason': 'combat-disabled'}
