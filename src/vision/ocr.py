# SPDX-License-Identifier: AGPL-3.0-or-later
# Derived from ok-script 1.0.190's AGPL production OCR contract.
"""Production-shaped OCR over an explicitly supplied inference engine."""

import logging
import re
import time

import cv2

from src.vision.boxes import Box, find_boxes_by_name, relative_box, sort_boxes
from src.vision.features import resize_image


logger = logging.getLogger(__name__)


def _draw_name(name):
    if name is None:
        return ''
    if isinstance(name, list):
        return ''.join(map(str, name))
    return str(name)


class OCR:
    def __init__(self, executor, engine, *, translator=None, text_fix=None,
                 locale=None, resolve_box=None, box_factory=Box,
                 auto_simplify=False, screenshot_writer=None, draw_boxes=None):
        self.executor = executor
        self.engine = engine
        self.translator = translator
        self.text_fix = text_fix if text_fix is not None else {}
        self.locale = locale
        self.resolve_box = resolve_box
        self.box_factory = box_factory
        self.auto_simplify = auto_simplify
        self.screenshot_writer = screenshot_writer
        self.draw_boxes = draw_boxes
        self.ocr_default_threshold = 0.2
        self.ocr_target_height = 0
        if auto_simplify and locale is None:
            raise ValueError('OCR locale is required when auto_simplify is enabled')

    def add_text_fix(self, fix):
        self.text_fix.update(fix)

    def fix_match_regex(self, match):
        if not match or self.translator is None:
            return match
        translated = []
        for pattern in match if isinstance(match, list) else [match]:
            if isinstance(pattern, re.Pattern):
                value = self.translator.gettext(pattern.pattern)
                pattern = re.compile(value, pattern.flags)
            translated.append(pattern)
        return translated

    def fix_texts(self, detected_boxes):
        if self.auto_simplify and self.locale.startswith(('zh_TW', 'zh_HK', 'zh_MO')):
            from opencc import OpenCC
            if not hasattr(self, '_cc_jp2t'):
                self._cc_jp2t = OpenCC('jp2t')
                self._cc_t2s = OpenCC('t2s')
            for detected_box in detected_boxes:
                detected_box.name = self._cc_t2s.convert(
                    self._cc_jp2t.convert(detected_box.name))
        for detected_box in detected_boxes:
            detected_box.name = detected_box.name.strip()
            if self.translator is not None:
                fixed = self.translator.gettext(detected_box.name)
                if fixed != detected_box.name:
                    detected_box.name = fixed
                else:
                    no_space = detected_box.name.replace(' ', '')
                    fixed = self.translator.gettext(no_space)
                    if fixed != no_space:
                        detected_box.name = fixed
            fixed = self.text_fix.get(detected_box.name)
            if fixed:
                detected_box.name = fixed

    def ocr(self, x=0, y=0, to_x=1, to_y=1, match=None, width=0, height=0,
            box=None, name=None, threshold=0, frame=None, target_height=0,
            use_grayscale=False, log=False, screenshot=False,
            frame_processor=None, lib='default'):
        if lib != 'default':
            raise ValueError(f'OCR engine is not configured for {lib!r}')
        image = frame if frame is not None else self.executor.frame
        if image is None:
            raise ValueError('OCR requires a current frame')
        if isinstance(box, str):
            if self.resolve_box is None:
                raise ValueError(f'No OCR box resolver for {box!r}')
            box = self.resolve_box(box)
        if self.executor.paused:
            self.executor.sleep(1)
        if threshold == 0:
            threshold = self.ocr_default_threshold
        start = time.time()
        match = self.fix_match_regex(match)
        frame_height, frame_width = image.shape[:2]
        if box is None:
            box = relative_box(frame_width, frame_height, x, y, to_x, to_y,
                               width, height, name)
        image = image[box.y:box.y + box.height, box.x:box.x + box.width]
        if not box.name and match:
            box.name = str(match)
        if use_grayscale:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        image, scale_factor = resize_image(image, frame_height, target_height)
        if frame_processor is not None:
            image = frame_processor(image)
        result = self.engine.ocr(image)
        detected_boxes = []
        if result[0] is not None:
            for pos, (text, confidence) in result[0]:
                detected_width = round(pos[2][0] - pos[0][0])
                detected_height = round(pos[2][1] - pos[0][1])
                if detected_width <= 0 or detected_height <= 0:
                    logger.debug('OCR negative box %s %.3f %sx%s %s', text, confidence,
                                 detected_width, detected_height, pos)
                    continue
                if confidence < threshold:
                    continue
                detected = self.box_factory(pos[0][0], pos[0][1],
                                            detected_width, detected_height,
                                            confidence, text)
                if scale_factor != 1:
                    detected.x = round(detected.x / scale_factor)
                    detected.y = round(detected.y / scale_factor)
                    detected.width = round(detected.width / scale_factor)
                    detected.height = round(detected.height / scale_factor)
                detected.x += box.x
                detected.y += box.y
                detected_boxes.append(detected)
        all_boxes = detected_boxes[:]
        self.fix_texts(detected_boxes)
        if match is not None:
            detected_boxes = find_boxes_by_name(detected_boxes, match)
        if self.draw_boxes is not None:
            try:
                self.draw_boxes('ocr' + _draw_name(name), detected_boxes, 'red')
                self.draw_boxes('ocr_zone' + _draw_name(name), [box], 'blue')
            except Exception:
                logger.exception('Unable to deliver OCR draw boxes')
        if screenshot:
            if self.screenshot_writer is None:
                logger.error('OCR screenshot requested without a writer')
            else:
                try:
                    self.screenshot_writer('ocr', frame=image, show_box=True, frame_box=box)
                except Exception:
                    logger.exception('Unable to save OCR diagnostic screenshot')
        if log:
            logger.info('ocr_zone %s found result: %s time: %.2f scale_factor: %.2f '
                        'target_height:%s resized_shape:%s all_boxes:%s',
                        box, detected_boxes, time.time() - start, scale_factor,
                        target_height, image.shape, all_boxes)
        return sort_boxes(detected_boxes)
