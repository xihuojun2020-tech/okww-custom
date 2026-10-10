"""Offline parity for the production color boundary, without task/device setup."""

import ast
import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest

import cv2
import numpy as np

from src.vision import color


ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ('color_range_to_bound', 'get_mask_in_color_range', 'mask_white',
             'is_pure_black', 'calculate_color_percentage')
WHITE = {'r': (244, 255), 'g': (244, 255), 'b': (244, 255)}
FIRE = {'r': (200, 230), 'g': (100, 130), 'b': (75, 105)}


class TestPackColorVision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Read only the pinned reference functions. Importing the old utility
        # would also import its Box/Qt dependency, which this boundary removes.
        spec = importlib.util.find_spec('ok')
        source = Path(spec.origin).parent / 'util/color.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        functions = [node for node in tree.body
                     if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
        namespace = {'cv2': cv2, 'np': np}
        exec(compile(ast.Module(functions, type_ignores=[]), str(source), 'exec'), namespace)
        cls.reference = SimpleNamespace(**{name: namespace[name] for name in FUNCTIONS})

    def test_import_and_mask_work_without_old_or_new_framework(self):
        code = (
            f'import sys; sys.path.insert(0, {str(ROOT)!r}); '
            'sys.modules["ok"] = None; sys.modules["gameframe"] = None; '
            'from src.vision.color import get_mask_in_color_range; import numpy as np; '
            'mask, count = get_mask_in_color_range(np.zeros((2, 2, 3), np.uint8), '
            '{"r": (0, 0), "g": (0, 0), "b": (0, 0)}); '
            'assert count == 4 and mask.shape == (2, 2); '
            'assert not any(name.startswith(("ok.", "gameframe.", "PySide6")) for name in sys.modules)'
        )
        subprocess.run([sys.executable, '-I', '-c', code], cwd=ROOT,
                       check=True, capture_output=True, text=True)

    def test_bgr_inclusive_edges_and_crop_contract(self):
        image = np.array([[[75, 100, 200], [105, 130, 230]],
                          [[74, 100, 200], [105, 130, 231]]], dtype=np.uint8)
        lower, upper = color.color_range_to_bound(FIRE)
        np.testing.assert_array_equal(lower, (75, 100, 200))
        np.testing.assert_array_equal(upper, (105, 130, 230))
        self.assertEqual(lower.dtype, np.uint8)
        mask, count = color.get_mask_in_color_range(image, FIRE)
        np.testing.assert_array_equal(mask, ((255, 255), (0, 0)))
        self.assertEqual(count, 2)
        self.assertEqual(color.calculate_color_percentage(image, FIRE), .5)
        inside = SimpleNamespace(x=0, y=0, width=2, height=1)
        self.assertEqual(color.calculate_color_percentage(image, FIRE, inside), 1)
        outside = SimpleNamespace(x=-1, y=0, width=2, height=1)
        self.assertEqual(color.calculate_color_percentage(image, FIRE, outside), 0)
        bgra = np.dstack((image, np.zeros((2, 2), np.uint8)))
        self.assertEqual(color.calculate_color_percentage(bgra, FIRE), .5)

    def test_white_mask_and_black_channels(self):
        gray = np.array([[243, 244, 255]], dtype=np.uint8)
        for image in (gray, gray[:, :, None], cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)):
            np.testing.assert_array_equal(color.mask_white(image, 244), ((0, 255, 255),))
        frame = np.zeros((2, 2, 3), np.uint8)
        self.assertTrue(color.is_pure_black(frame))
        frame[0, 0, 2] = 1
        self.assertFalse(color.is_pure_black(frame))

    def test_existing_combat_screenshots_match_production_reference(self):
        for name in ('con_full.png', 'combat_has_cd.png', 'all_cd_1080p.png'):
            image = cv2.imdecode(np.fromfile(ROOT / 'tests/images' / name, np.uint8), cv2.IMREAD_COLOR)
            self.assertIsNotNone(image, name)
            height, width = image.shape[:2]
            roi = SimpleNamespace(x=width // 2, y=height // 2,
                                  width=width // 3, height=height // 3)
            for bounds in (WHITE, FIRE):
                with self.subTest(image=name, bounds=bounds):
                    actual, actual_count = color.get_mask_in_color_range(image, bounds)
                    expected, expected_count = self.reference.get_mask_in_color_range(image, bounds)
                    np.testing.assert_array_equal(actual, expected)
                    self.assertEqual(actual_count, expected_count)
                    for box in (None, roi):
                        self.assertEqual(color.calculate_color_percentage(image, bounds, box),
                                         self.reference.calculate_color_percentage(image, bounds, box))
            np.testing.assert_array_equal(color.mask_white(image, 244), self.reference.mask_white(image, 244))
            self.assertEqual(color.is_pure_black(image), self.reference.is_pure_black(image))


if __name__ == '__main__':
    unittest.main()
