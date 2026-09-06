import unittest
from unittest.mock import patch

import numpy as np

from src.runtime.game_runtime_errors import FrameUnavailable, GameProcessLost
from src.task.BaseWWTask import BaseWWTask


class _Window:
    def __init__(self, exists):
        self.exists = exists


class _DeviceManager:
    def __init__(self, exists):
        self.hwnd_window = _Window(exists)


class _Executor:
    frame = None

    def __init__(self, exists, connected):
        self.device_manager = _DeviceManager(exists)
        self._connected = connected

    def connected(self):
        return self._connected


class TestGameRuntimeErrors(unittest.TestCase):
    def test_yolo_restores_non_square_frames_and_single_detection(self):
        # Test postprocessing without loading either model or optional runtime.
        with patch.dict('sys.modules', {'onnxruntime': None}):
            from src.OnnxYolo8Detect import OnnxYolo8Detect
        from src.OpenVinoYolo8Detect import OpenVinoYolo8Detect
        for cls in (OnnxYolo8Detect, OpenVinoYolo8Detect):
            for model_h, model_w in ((384, 640), (640, 384), (640, 640)):
                for orig_h, orig_w in ((384, 640), (640, 384)):
                    for count in (0, 1, 2):
                        with self.subTest(backend=cls.__name__, model=(model_h, model_w),
                                          frame=(orig_h, orig_w), count=count):
                            detector = cls.__new__(cls)
                            detector.preprocess_target_h = detector.input_height = model_h
                            detector.preprocess_target_w = detector.input_width = model_w
                            detector.iou_threshold = .45
                            detector.dic_labels = {0: 'echo'}
                            frame = np.zeros((orig_h, orig_w, 3), np.uint8)
                            tensor, pad = detector._preprocess(frame)
                            self.assertEqual(tensor.shape, (1, 3, model_h, model_w))
                            gain = min(model_h / orig_h, model_w / orig_w)
                            raw = np.array([100 * gain + pad[1], 100 * gain + pad[0],
                                            50 * gain, 50 * gain, .9], np.float32)
                            output = np.tile(raw[:, None], (1, count))[None, ...]
                            original = output.copy()
                            result = detector._postprocess(
                                [output] if cls is OnnxYolo8Detect else output,
                                pad, (orig_h, orig_w), .5, -1)
                            self.assertEqual(len(result), 1 if count else 0)
                            if result:
                                np.testing.assert_allclose(
                                    (result[0].x, result[0].y, result[0].width, result[0].height),
                                    (75, 75, 50, 50), atol=1, rtol=0)  # Existing integer truncation.
                            np.testing.assert_array_equal(original, output)

    def test_missing_selected_backend_has_actionable_error(self):
        with patch.dict('sys.modules', {'onnxruntime': None}):
            from src.OnnxYolo8Detect import OnnxYolo8Detect
            with self.assertRaisesRegex(RuntimeError, 'onnxruntime'):
                OnnxYolo8Detect()

    def test_missing_window_is_not_reported_as_missing_asset(self):
        task = BaseWWTask.__new__(BaseWWTask)
        task._executor = _Executor(False, False)

        with self.assertRaises(GameProcessLost):
            task.require_game_frame()

    def test_connected_window_without_frame_has_specific_error(self):
        task = BaseWWTask.__new__(BaseWWTask)
        task._executor = _Executor(True, True)

        with self.assertRaises(FrameUnavailable):
            task.require_game_frame()


if __name__ == '__main__':
    unittest.main()
