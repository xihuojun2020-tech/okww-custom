"""Pixel thresholds and import isolation for the production image transforms."""

import subprocess
import sys
import unittest

import numpy as np

from src.vision.preprocess import (binarize_for_matching, convert_bw,
                                   convert_dialog_icon, isolate_white_text_to_black)


class TestPackPreprocess(unittest.TestCase):
    def test_exact_white_and_dialog_boundaries(self):
        image = np.array([[[level] * 3 for level in (209, 210, 240, 244, 245, 255)]], dtype=np.uint8)
        self.assertEqual(convert_bw(image)[0, :, 0].tolist(), [0, 0, 0, 255, 255, 255])
        self.assertEqual(convert_dialog_icon(image)[0, :, 0].tolist(), [0, 255, 255, 255, 0, 0])
        self.assertEqual(isolate_white_text_to_black(image)[0, :, 0].tolist(), [255, 255, 255, 0, 0, 0])
        self.assertEqual(binarize_for_matching(image)[0].tolist(), [0, 0, 0, 0, 255, 255])
        self.assertEqual(binarize_for_matching(image, 220)[0].tolist(), [0, 0, 255, 255, 255, 255])

    def test_production_feature_processor_imports_without_task_framework(self):
        script = '''
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ok', 'PySide6', 'qfluentwidgets'} or fullname == 'src.task.BaseWWTask':
            raise ImportError(fullname)
sys.meta_path.insert(0, Block())
from src.task.process_feature import process_feature
import numpy as np
from types import SimpleNamespace
feature = SimpleNamespace(mat=np.array([[[255, 255, 255], [0, 0, 0]]], dtype=np.uint8))
process_feature('mouse_forte', feature)
assert feature.mat.tolist() == [[255, 0]]
'''
        result = subprocess.run([sys.executable, '-c', script], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
