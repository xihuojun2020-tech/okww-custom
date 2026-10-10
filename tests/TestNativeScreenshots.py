"""Native diagnostic image privacy and explicit filesystem boundary."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from src.runtime.native_screenshots import save_native_screenshot


class TestNativeScreenshots(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_identity_region_is_masked_without_changing_input_at_both_resolutions(self):
        from src.runtime.account_task_support import native_blur_area
        for width, height in ((1920, 1080), (1280, 720)):
            with self.subTest(resolution=(width, height)):
                frame = np.full((height, width, 3), 173, np.uint8)
                original = frame.copy()
                destination = save_native_screenshot(self.root, f'log/{height}', frame)
                saved = cv2.imdecode(np.fromfile(destination, np.uint8), cv2.IMREAD_COLOR)
                box = native_blur_area(width, height)
                self.assertFalse(saved[box.y:box.y + box.height,
                                       box.x:box.x + box.width].any())
                self.assertTrue(np.array_equal(frame, original))
                self.assertTrue(np.array_equal(saved[:box.y], original[:box.y]))
                self.assertEqual(destination, self.root / f'okww监控室/log/{height}.png')

    def test_path_escape_and_failed_encoding_never_write_an_image(self):
        frame = np.ones((720, 1280, 3), np.uint8)
        with self.assertRaises(ValueError):
            save_native_screenshot(self.root, '../private', frame)
        with patch('src.runtime.native_screenshots.cv2.imencode', return_value=(False, None)):
            with self.assertRaises(OSError):
                save_native_screenshot(self.root, 'failed', frame)
        self.assertFalse((self.root / 'private.png').exists())
        self.assertFalse((self.root / 'okww监控室/failed.png').exists())
        self.assertTrue(frame.all())


if __name__ == '__main__':
    unittest.main()
