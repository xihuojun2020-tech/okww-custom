# SPDX-License-Identifier: AGPL-3.0-or-later
# Derived from ok-script 1.0.190 task API used by Wuthering Waves combat.
"""Headless production task API composed from native combat services."""

import logging
import time

import cv2

from src.runtime.native_config import Config
from src.runtime.native_errors import HotkeyConfigException
from src.runtime.native_logging import Logger
from src.vision.boxes import (Box, find_boxes_by_name, find_boxes_within_boundary,
                              find_highest_confidence_box, relative_box)
from src.vision.ocr import OCR


logger = logging.getLogger(__name__)
VALID_NAMED_KEYS = {
    'esc', 'tab', 'shift', 'lshift', 'rshift', 'shift_l', 'shift_r',
    'ctrl', 'control', 'lctrl', 'rctrl', 'lcontrol', 'rcontrol', 'ctrl_l', 'ctrl_r',
    'alt', 'lalt', 'ralt', 'alt_l', 'alt_r', 'alt_gr',
    'enter', 'return', 'space', 'backspace', 'up', 'down', 'left', 'right',
    'pageup', 'pagedown', 'page_up', 'page_down', 'home', 'end', 'insert',
    'delete', 'capslock', 'numlock', 'scrolllock', 'printscreen',
    'caps_lock', 'num_lock', 'scroll_lock', 'print_screen',
    *(f'f{number}' for number in range(1, 13)),
    *(f'num{number}' for number in range(10)),
    'windows', 'win', 'command', 'cmd', 'cmd_l', 'cmd_r', 'meta',
}


def _scale_by_anchor(value, image_size, screen_size, scale, center=False):
    if center:
        return round(screen_size * .5 + (value - image_size * .5) * scale)
    if value > image_size / 2:
        return screen_size - round((image_size - value) * scale)
    return round(value * scale)


def _adjust_coordinates(x, y, width, height, screen_width, screen_height,
                        image_width, image_height, hcenter=False, vcenter=False):
    scale = min(screen_width / image_width, screen_height / image_height)
    return (_scale_by_anchor(x, image_width, screen_width, scale, hcenter),
            _scale_by_anchor(y, image_height, screen_height, scale, vcenter),
            round(width * scale), round(height * scale))


class NativeBaseTask:
    """Combat-facing BaseTask surface; platform/UI navigation remains in the legacy app."""

    def __init__(self, executor, app, *, ocr_engine, global_configs,
                 supported_ratio, translator=None, text_fix=None, locale=None,
                 auto_simplify=False, box_factory=Box, tasks_by_class=None,
                 window=None, debug=False):
        self._executor = executor
        self._app = app
        self.scene = executor.scene
        self.hwnd = window
        self.logger = Logger.get_logger(type(self).__name__)
        self._global_configs = global_configs
        self._tasks_by_class = tasks_by_class if tasks_by_class is not None else {}
        self._supported_ratio = supported_ratio
        self._box_factory = box_factory
        self._debug = debug
        self._ocr_service = OCR(executor, ocr_engine, translator=translator,
                        text_fix=text_fix, locale=locale,
                        resolve_box=self.get_box_by_name,
                        box_factory=box_factory,
                        auto_simplify=auto_simplify,
                        screenshot_writer=self.screenshot,
                        draw_boxes=self.draw_boxes)
        self.name = type(self).__name__
        self.instructions = None
        self.description = ''
        self._enabled = False
        self.config = None
        self.capture_config = None
        self.info = {}
        self.default_config = {}
        self.global_config_names = []
        self.config_description = {}
        self.config_type = {}
        self.running = False
        self.trigger_interval = 0
        self.last_trigger_time = 0
        self.start_time = 0
        self.exit_after_task = False
        self.sleep_check_interval = -1
        self.last_sleep_check_time = 0
        self.in_sleep_check = False
        self.last_click_time = 0

    @property
    def executor(self):
        return self._executor

    @property
    def debug(self):
        return self._debug

    @property
    def ocr_default_threshold(self):
        return self._ocr_service.ocr_default_threshold

    @ocr_default_threshold.setter
    def ocr_default_threshold(self, value):
        self._ocr_service.ocr_default_threshold = value

    @property
    def frame(self):
        return self.executor.frame

    @property
    def width(self):
        if not self.executor.width:
            self.executor.frame
        return self.executor.width

    @property
    def height(self):
        if not self.executor.height:
            self.executor.frame
        return self.executor.height

    screen_width = width
    screen_height = height

    @property
    def enabled(self):
        return self._enabled

    @property
    def paused(self):
        return self.executor.paused

    @property
    def hwnd_title(self):
        return self.hwnd.hwnd_title if self.hwnd is not None else ''

    def tr(self, message):
        return self._app.tr(message)

    def get_global_config(self, option):
        return self._global_configs[option]

    def get_task_by_class(self, cls):
        return self.executor.get_task_by_class(cls)

    def run_task_by_class(self, cls):
        task = self.get_task_by_class(cls)
        old_info = task.info
        current_task = self.executor.current_task
        task.info = self.info
        try:
            return task.run()
        except Exception as error:
            self.log_error(f'run_task_by_class {cls}', error)
            raise
        finally:
            task.info = old_info
            self.executor.current_task = current_task

    def is_browser(self):
        device = self.executor.device_manager.get_preferred_device()
        if device:
            return device.get('device') == 'browser'

    def validate_config(self, key, value):
        return None

    def validate(self, key, value):
        message = self.validate_config(key, value)
        return not bool(message), message

    def load_config(self):
        self.config = Config(type(self).__name__, self.default_config,
                             validator=self.validate)

    def on_create(self):
        return None

    def on_destroy(self):
        return None

    def after_init(self, executor=None, scene=None, config=None):
        if executor is not None:
            self._executor = executor
            self._ocr_service.executor = executor
        self.scene = scene if scene is not None else self.executor.scene
        self.load_config()
        if config is not None:
            self.config.update(config)
        self.on_create()
        self.executor.current_task = self

    def run(self):
        raise NotImplementedError('NativeBaseTask subclasses must implement run')

    def sleep_check(self):
        return None

    def should_trigger(self):
        if self.trigger_interval == 0:
            return True
        now = time.time()
        if now - self.last_trigger_time > self.trigger_interval:
            self.last_trigger_time = now
            return True
        return False

    def get_status(self):
        if self.running:
            return 'Running'
        if self.enabled:
            return 'Paused' if self.paused else 'In Queue'
        return 'Not Started'

    def enable(self):
        self._enabled = True
        self.info_clear()
        self.executor.on_run()

    def disable(self):
        self._enabled = False

    def exit_is_set(self):
        return self.executor.exit_event.is_set()

    def add_exit_after_config(self):
        self.default_config['Exit After Task'] = False
        self.config_description['Exit After Task'] = 'Exit the Game and the App after Successfully Executing the Task'

    def ensure_in_front(self):
        return self.executor.ensure_in_front()

    def start_device(self):
        return self.executor.start_device()

    def ensure_capture(self, config=None):
        config = self.capture_config if config is None else config
        if config:
            raise NotImplementedError('GameFrame device selection belongs to the runtime, not task capture_config')

    def pause(self):
        self.executor.pause(None if isinstance(self, NativeTriggerTask) else self)

    def unpause(self):
        self.executor.unpause()

    def back(self, after_sleep=0):
        self.executor.back()
        if after_sleep > 0:
            self.sleep(after_sleep)

    def next_frame(self):
        return self.executor.next_frame()

    def sleep(self, timeout):
        self.executor.sleep(timeout)
        return True

    def wait_until(self, condition, time_out=0, pre_action=None, post_action=None,
                   settle_time=-1, raise_if_not_found=False):
        return self.executor.wait_condition(
            condition, time_out, pre_action, post_action,
            settle_time=settle_time, raise_if_not_found=raise_if_not_found)

    def get_box_by_name(self, name):
        if isinstance(name, (Box, self._box_factory)):
            return name
        regions = {
            'full_screen': (0, 0, 1, 1), 'right': (.5, 0, 1, 1),
            'bottom_right': (.5, .5, 1, 1), 'top_right': (.5, 0, 1, .5),
            'left': (0, 0, .5, 1), 'bottom_left': (0, .5, .5, 1),
            'top_left': (0, 0, .5, .5), 'bottom': (0, .5, 1, 1),
            'top': (0, 0, 1, .5),
        }
        if name in regions:
            return self.box_of_screen(*regions[name], name=name)
        box = self.executor.feature_set.get_box_by_name(self.frame, name)
        if box is None:
            raise ValueError(f'No box found for category {name}')
        return box

    def get_feature_by_name(self, name):
        feature = self.executor.feature_set.get_feature_by_name(self.frame, name)
        if feature is None:
            raise ValueError(f'No feature found for name {name}')
        return feature

    def feature_exists(self, feature_name):
        return self.executor.feature_set.feature_exists(feature_name)

    def find_feature(self, feature_name=None, horizontal_variance=0,
                     vertical_variance=0, threshold=0, use_gray_scale=False,
                     x=-1, y=-1, to_x=-1, to_y=-1, width=-1, height=-1,
                     box=None, canny_lower=0, canny_higher=0,
                     frame_processor=None, template=None,
                     match_method=cv2.TM_CCOEFF_NORMED, screenshot=False,
                     mask_function=None, frame=None, limit=0, target_height=0):
        image = frame if frame is not None else self.frame
        if isinstance(box, str):
            box = self.get_box_by_name(box)
        return self.executor.feature_set.find_feature(
            image, feature_name, horizontal_variance, vertical_variance,
            threshold, use_gray_scale, x, y, to_x, to_y, width, height,
            box=box, canny_lower=canny_lower, canny_higher=canny_higher,
            frame_processor=frame_processor, template=template,
            match_method=match_method, screenshot=screenshot,
            mask_function=mask_function, limit=limit,
            target_height=target_height)

    def find_one(self, feature_name=None, horizontal_variance=0,
                 vertical_variance=0, threshold=0, use_gray_scale=False,
                 box=None, canny_lower=0, canny_higher=0,
                 frame_processor=None, template=None, mask_function=None,
                 frame=None, match_method=cv2.TM_CCOEFF_NORMED,
                 screenshot=False, limit=1, target_height=0):
        boxes = self.find_feature(
            feature_name, horizontal_variance, vertical_variance, threshold,
            use_gray_scale, box=box, canny_lower=canny_lower,
            canny_higher=canny_higher, frame_processor=frame_processor,
            template=template, mask_function=mask_function, frame=frame,
            match_method=match_method, screenshot=screenshot, limit=limit,
            target_height=target_height)
        return find_highest_confidence_box(boxes)

    def find_best_match_in_box(self, box, to_find, threshold,
                               use_gray_scale=False, canny_lower=0,
                               canny_higher=0, frame_processor=None,
                               mask_function=None):
        best = None
        for name in to_find:
            found = self.find_one(name, box=box, threshold=threshold,
                                  use_gray_scale=use_gray_scale,
                                  canny_lower=canny_lower,
                                  canny_higher=canny_higher,
                                  frame_processor=frame_processor,
                                  mask_function=mask_function)
            if found is not None and (best is None or found.confidence > best.confidence):
                best = found
        return best

    def find_boxes(self, boxes, match=None, boundary=None):
        if match:
            boxes = find_boxes_by_name(boxes, match)
        if boundary:
            area = self.get_box_by_name(boundary) if isinstance(boundary, str) else boundary
            boxes = find_boxes_within_boundary(boxes, area)
        return boxes

    def wait_feature(self, feature, horizontal_variance=0, vertical_variance=0,
                     threshold=0, time_out=0, pre_action=None, post_action=None,
                     use_gray_scale=False, box=None, raise_if_not_found=False,
                     canny_lower=0, canny_higher=0, settle_time=-1,
                     frame_processor=None, target_height=0):
        return self.wait_until(
            lambda: self.find_one(feature, horizontal_variance,
                                  vertical_variance, threshold,
                                  use_gray_scale=use_gray_scale, box=box,
                                  canny_lower=canny_lower,
                                  canny_higher=canny_higher,
                                  frame_processor=frame_processor,
                                  target_height=target_height),
            time_out, pre_action, post_action, settle_time,
            raise_if_not_found)

    def wait_click_feature(self, feature, horizontal_variance=0,
                           vertical_variance=0, threshold=0, relative_x=.5,
                           relative_y=.5, time_out=0, pre_action=None,
                           post_action=None, box=None, raise_if_not_found=True,
                           use_gray_scale=False, canny_lower=0,
                           canny_higher=0, click_after_delay=0,
                           settle_time=-1, after_sleep=0, target_height=0):
        found = self.wait_feature(
            feature, horizontal_variance, vertical_variance, threshold,
            time_out, pre_action, post_action, use_gray_scale, box,
            raise_if_not_found, canny_lower, canny_higher, settle_time,
            target_height=target_height)
        if found is None:
            return False
        if click_after_delay > 0:
            self.sleep(click_after_delay)
        self.click_box(found, relative_x, relative_y, after_sleep=after_sleep)
        return True

    def ocr(self, *args, **kwargs):
        return self._ocr_service.ocr(*args, **kwargs)

    def add_text_fix(self, fix):
        self._ocr_service.add_text_fix(fix)

    def wait_ocr(self, x=0, y=0, to_x=1, to_y=1, width=0, height=0,
                 name=None, box=None, match=None, threshold=0, frame=None,
                 target_height=0, time_out=0, post_action=None,
                 raise_if_not_found=False, log=False, screenshot=False,
                 settle_time=-1, lib='default'):
        return self.wait_until(
            lambda: self.ocr(x, y, to_x, to_y, match, width, height,
                             box, name, threshold, frame, target_height,
                             log=log, screenshot=screenshot, lib=lib),
            time_out=time_out, post_action=post_action,
            settle_time=settle_time,
            raise_if_not_found=raise_if_not_found)

    def width_of_screen(self, percent):
        return int(percent * self.width)

    def height_of_screen(self, percent):
        return int(percent * self.height)

    def out_of_ratio(self):
        return bool(self.height and abs(self.width / self.height - self._supported_ratio) > .01)

    def box_of_screen_scaled(self, original_screen_width, original_screen_height,
                             x_original, y_original, to_x=0, to_y=0,
                             width_original=0, height_original=0, name=None,
                             hcenter=False, vcenter=False, confidence=1.0):
        if width_original == 0:
            width_original = to_x - x_original
        if height_original == 0:
            height_original = to_y - y_original
        x, y, width, height = _adjust_coordinates(
            x_original, y_original, width_original, height_original,
            self.width, self.height, original_screen_width,
            original_screen_height, hcenter, vcenter)
        return self._box_factory(x, y, width, height, confidence, name)

    def box_of_screen(self, x, y, to_x=1.0, to_y=1.0, width=0.0,
                      height=0.0, name=None, hcenter=False,
                      vcenter=False, confidence=1.0):
        if name is None:
            name = f'{x} {y} {width} {height}'
        if self.out_of_ratio():
            virtual_width = self._supported_ratio * self.height
            return self.box_of_screen_scaled(
                virtual_width, self.height, x * virtual_width,
                y * self.height, to_x * virtual_width,
                to_y * self.height, width * virtual_width,
                height * self.height, name, hcenter, vcenter, confidence)
        region = relative_box(self.width, self.height, x, y, to_x,
                              to_y, width, height, name, confidence)
        return self._box_factory(region.x, region.y, region.width,
                                 region.height, confidence, name)

    def validate_key(self, key):
        if isinstance(key, int):
            key = str(key)
        if not isinstance(key, str):
            raise HotkeyConfigException(key)
        lowered = key.lower()
        if len(lowered) == 1:
            if not (lowered.isalnum() or lowered in ' `~!@#$%^&*()-_=+[{]}\\|;:\'",<.>/?'):
                raise HotkeyConfigException(key)
        elif lowered not in VALID_NAMED_KEYS:
            raise HotkeyConfigException(key)
        return key

    def check_interval(self, interval):
        if interval <= 0:
            return True
        now = time.time()
        if now - self.last_click_time < interval:
            return False
        self.last_click_time = now
        return True

    def click(self, x=-1, y=-1, move_back=False, name=None, interval=-1,
              move=True, down_time=.02, after_sleep=0, key='left',
              hcenter=False, vcenter=False):
        if isinstance(x, (Box, self._box_factory, list)):
            return self.click_box(x, move_back=move_back, move=move,
                                  down_time=down_time, after_sleep=after_sleep)
        if 0 < x < 1 or 0 < y < 1:
            return self.click_relative(x, y, move_back, hcenter, vcenter,
                                       move, after_sleep, name, interval,
                                       down_time, key)
        if not self.check_interval(interval):
            self.executor.reset_scene()
            return False
        self.executor.click(x, y, move_back=move_back, name=name,
                            move=move, down_time=down_time, key=key)
        if after_sleep > 0:
            self.sleep(after_sleep)
        return True

    def click_relative(self, x, y, move_back=False, hcenter=False,
                       vcenter=False, move=True, after_sleep=0, name=None,
                       interval=-1, down_time=.02, key='left'):
        if self.out_of_ratio():
            virtual_width = self._supported_ratio * self.height
            x, y, _, _ = _adjust_coordinates(
                x * virtual_width, y * self.height, 0, 0,
                self.width, self.height, virtual_width, self.height,
                hcenter, vcenter)
        else:
            x, y = int(self.width * x), int(self.height * y)
        return self.click(x, y, move_back, name, interval, move,
                          down_time, after_sleep, key)

    def click_box(self, box=None, relative_x=.5, relative_y=.5,
                  raise_if_not_found=False, move_back=False, move=True,
                  down_time=.01, after_sleep=1):
        if isinstance(box, list):
            box = box[0] if box else None
        if isinstance(box, str):
            box = self.get_box_by_name(box)
        if box is None:
            if raise_if_not_found:
                raise ValueError('click_box box is None')
            return None
        x, y = box.relative_with_variance(relative_x, relative_y)
        return self.click(x, y, name=box.name, move_back=move_back,
                          move=move, down_time=down_time,
                          after_sleep=after_sleep)

    def middle_click(self, *args, **kwargs):
        return self.click(*args, **kwargs, key='middle')

    def middle_click_relative(self, x, y, move_back=False, down_time=.01):
        return self.middle_click(int(self.width * x), int(self.height * y), move_back,
                                 name=f'relative({x:.2f}, {y:.2f})', down_time=down_time)

    def right_click(self, *args, **kwargs):
        return self.click(*args, **kwargs, key='right')

    def send_key(self, key, down_time=.02, interval=-1, after_sleep=0):
        key = self.validate_key(key)
        if not self.check_interval(interval):
            self.executor.reset_scene()
            return False
        self.executor.send_key(key, down_time)
        if after_sleep > 0:
            self.sleep(after_sleep)
        return True

    def send_key_down(self, key, after_sleep=0):
        self.executor.send_key_down(self.validate_key(key))
        if after_sleep > 0:
            self.sleep(after_sleep)

    def send_key_up(self, key, after_sleep=0):
        self.executor.send_key_up(self.validate_key(key))
        if after_sleep > 0:
            self.sleep(after_sleep)

    def mouse_down(self, x=-1, y=-1, name=None, key='left'):
        self.executor.mouse_down(x, y, name, key)

    def mouse_up(self, name=None, key='left'):
        self.executor.mouse_up(name, key)

    def move(self, x, y):
        self.executor.move(x, y)

    def move_relative(self, x, y):
        self.move(int(self.width * x), int(self.height * y))

    def input_text(self, text):
        self.executor.input_text(text)

    def scroll_relative(self, x, y, count):
        self.scroll(int(self.width * x), int(self.height * y), count)

    def scroll(self, x, y, count):
        self.executor.scroll(x, y, count)

    def swipe_relative(self, from_x, from_y, to_x, to_y, duration=.5,
                       settle_time=0):
        self.swipe(int(self.width * from_x), int(self.height * from_y),
                   int(self.width * to_x), int(self.height * to_y),
                   duration, settle_time=settle_time)

    def swipe(self, from_x, from_y, to_x, to_y, duration=.5,
              after_sleep=.1, settle_time=0):
        self.executor.swipe(from_x, from_y, to_x, to_y, duration,
                            settle_time=settle_time)
        if after_sleep > 0:
            self.sleep(after_sleep)

    def screenshot(self, name=None, frame=None, show_box=False, frame_box=None):
        from src.runtime.native_screenshots import save_native_screenshot
        image = self.frame if frame is None else frame
        destination = save_native_screenshot(self.executor.context.data_dir, name, image)
        self._emit('screenshot', name=name, path=str(destination),
                   show_box=show_box)
        return destination

    def _emit(self, kind, **values):
        try:
            self.executor.context.emit(kind, **values)
        except Exception:
            logger.exception('Unable to deliver task diagnostic event')

    def draw_boxes(self, feature_name=None, boxes=None, color='red', debug=True):
        if not debug:
            return
        if boxes is None:
            boxes = []
        if not isinstance(boxes, list):
            boxes = [boxes]
        self._emit('draw_box', name=feature_name, color=color,
                   boxes=[{'x': box.x, 'y': box.y, 'width': box.width,
                           'height': box.height, 'name': box.name}
                          for box in boxes])

    def _log_images(self, images=None, screenshot=False):
        if images is None:
            frames = []
        elif isinstance(images, (list, tuple)):
            frames = [image for image in images if image is not None]
        else:
            frames = [images]
        if screenshot:
            frame = self.executor.nullable_frame()
            if frame is not None:
                frames.append(frame)
        for index, frame in enumerate(frames, 1):
            try:
                self.screenshot(f'log/log_{time.time_ns()}_{index}', frame=frame)
            except Exception:
                logger.exception('Unable to save task log screenshot')

    def _log(self, level, message, exception=None, notify=False,
             images=None, screenshot=False):
        if level == 'error':
            self.logger.error(message, exception)
        else:
            getattr(self.logger, level)(message)
        if level == 'info':
            self.info_set('Log', message)
        elif level == 'warning':
            self.info_set('Warning', message)
        elif level == 'error':
            self.info_set('Error', message + (str(exception) if exception else ''))
        self._emit('task-log', level=level, message=message, notify=notify)
        self._log_images(images, screenshot or level == 'error')

    def log_info(self, message, notify=False, images=None, screenshot=False):
        self._log('info', message, notify=notify, images=images,
                  screenshot=screenshot)

    def log_debug(self, message, notify=False, images=None, screenshot=False):
        self._log('debug', message, notify=notify, images=images,
                  screenshot=screenshot)

    def log_warning(self, message, notify=False, images=None, screenshot=False):
        self._log('warning', message, notify=notify, images=images,
                  screenshot=screenshot)

    def log_error(self, message, exception=None, notify=False, images=None,
                  screenshot=False):
        self._log('error', message, exception, notify, images, screenshot)

    def info_clear(self):
        self.info.clear()

    def info_set(self, key, value):
        self.info[key] = value

    def info_get(self, *args, **kwargs):
        return self.info.get(*args, **kwargs)

    def info_incr(self, key, inc=1):
        self.info[key] = self.info.get(key, 0) + inc

    def info_add(self, key, count=1):
        self.info_incr(key, count)

    def info_add_to_list(self, key, item):
        values = self.info.setdefault(key, [])
        values.extend(item) if isinstance(item, list) else values.append(item)


class NativeTriggerTask(NativeBaseTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config['_enabled'] = False

    def on_create(self):
        self._enabled = self.config.get('_enabled', False)

    def enable(self):
        super().enable()
        self.config['_enabled'] = True

    def disable(self):
        super().disable()
        self.config['_enabled'] = False
