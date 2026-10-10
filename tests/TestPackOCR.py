"""Offline parity checks for pack-owned OCR geometry and text handling."""

import re
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from src.vision.boxes import Box
from src.vision.ocr import OCR


def detection(x, y, width, height, text, confidence=0.9):
    polygon = [[x, y], [x + width, y], [x + width, y + height],
               [x, y + height]]
    return [polygon, (text, confidence)]


class TestPackOCR(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((120, 200, 3), np.uint8)
        self.executor = SimpleNamespace(frame=self.frame, paused=False,
                                        sleep=Mock())

    def test_region_resize_and_coordinates_return_to_full_frame(self):
        engine = SimpleNamespace(ocr=Mock(return_value=[[
            detection(4, 6, 10, 6, 'target')]]))
        reader = OCR(self.executor, engine)
        result = reader.ocr(.1, .2, .5, .6, target_height=60)
        self.assertEqual(engine.ocr.call_args.args[0].shape, (24, 40, 3))
        self.assertEqual((result[0].x, result[0].y,
                          result[0].width, result[0].height),
                         (28, 36, 20, 12))

    def test_threshold_text_fix_match_and_reading_order(self):
        engine = SimpleNamespace(ocr=Mock(return_value=[[
            detection(50, 5, 12, 8, 'Ｅ'),
            detection(2, 5, 12, 8, ' A '),
            detection(5, 30, 12, 8, 'low', 0.1)]]))
        reader = OCR(self.executor, engine, text_fix={'Ｅ': 'e'})
        result = reader.ocr(frame=self.frame)
        self.assertEqual([box.name for box in result], ['A', 'e'])
        self.assertEqual([box.x for box in result], [2, 50])
        self.assertEqual([box.name for box in reader.ocr(match=re.compile(r'^e$'))], ['e'])

    def test_translation_of_regex_and_space_stripped_ocr_text(self):
        translations = {'^確認$': '^Confirm$', 'Con firm': 'Confirm'}
        translator = SimpleNamespace(gettext=lambda value: translations.get(value, value))
        engine = SimpleNamespace(ocr=Mock(return_value=[[
            detection(2, 5, 30, 8, ' Con firm ')]]))
        reader = OCR(self.executor, engine, translator=translator,
                     text_fix={'Confirm': 'confirmed'})
        self.assertEqual(reader.ocr()[0].name, 'confirmed')
        self.assertEqual(reader.ocr(match=re.compile(r'^確認$')),
                         [])  # Match is applied after text_fix, as in production.
        reader.text_fix.clear()
        self.assertEqual(reader.ocr(match=re.compile(r'^確認$'))[0].name,
                         'Confirm')

    def test_named_box_grayscale_processor_and_engine_failure(self):
        engine = SimpleNamespace(ocr=Mock(return_value=[[detection(1, 2, 5, 4, 'ok')]]))
        reader = OCR(self.executor, engine,
                     resolve_box=lambda name: Box(20, 30, 40, 20, name=name))
        result = reader.ocr(box='team', use_grayscale=True,
                            frame_processor=lambda image: image + 1)
        self.assertEqual(engine.ocr.call_args.args[0].shape, (20, 40))
        self.assertEqual((result[0].x, result[0].y), (21, 32))
        engine.ocr.side_effect = RuntimeError('model failed')
        with self.assertRaisesRegex(RuntimeError, 'model failed'):
            reader.ocr(box='team')

    def test_traditional_locale_simplification_is_explicit(self):
        engine = SimpleNamespace(ocr=Mock(return_value=[[
            detection(1, 2, 12, 8, '確認')]]))
        reader = OCR(self.executor, engine, locale='zh_TW', auto_simplify=True)
        self.assertEqual(reader.ocr()[0].name, '确认')
        self.assertEqual(OCR(self.executor, engine).ocr()[0].name, '確認')

    def test_diagnostic_failure_does_not_lose_ocr_result(self):
        engine = SimpleNamespace(ocr=Mock(return_value=[[]]))
        def fail(*args, **kwargs):
            raise OSError('diagnostic unavailable')
        reader = OCR(self.executor, engine, screenshot_writer=fail,
                     draw_boxes=fail)
        with self.assertLogs('src.vision.ocr', level='ERROR') as logs:
            self.assertEqual(reader.ocr(screenshot=True), [])
        self.assertIn('Unable to deliver OCR draw boxes', logs.output[0])
        self.assertIn('Unable to save OCR diagnostic screenshot', logs.output[1])


if __name__ == '__main__':
    unittest.main()
