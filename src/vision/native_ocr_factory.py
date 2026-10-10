# SPDX-License-Identifier: AGPL-3.0-or-later
"""Select OCR sessions using onnxocr-ppocrv5 0.0.20 predictor contracts.

The dependency retains ownership of preprocessing, postprocessing and OCR;
this adapter replaces only its hardcoded CPU ONNX session construction.
"""
import argparse
import importlib.util
import logging


def create_ocr(preferences, *, runtime=None):
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr
    choice = preferences['Use DirectML']
    if choice not in ('Yes', 'No', 'Auto'):
        raise ValueError('Invalid DirectML preference')
    if choice == 'No':
        return ONNXPaddleOcr(use_angle_cls=False, use_npu=False, use_openvino=True)
    if runtime is None:
        if importlib.util.find_spec('onnxruntime') is not None:
            import onnxruntime as runtime
    available = runtime is not None and 'DmlExecutionProvider' in runtime.get_available_providers()
    if not available:
        if choice == 'Yes':
            raise RuntimeError('DirectML was requested but DmlExecutionProvider is unavailable')
        return ONNXPaddleOcr(use_angle_cls=False, use_npu=False, use_openvino=True)

    from onnxocr.predict_base import PredictBase
    from onnxocr.predict_det import TextDetector
    from onnxocr.predict_rec import TextRecognizer
    from onnxocr.utils import infer_args

    class ProviderPredictBase(PredictBase):
        def __init__(self, model_dir, use_openvino=True, use_npu=True, logger=None,
                     force_static_shape=False, openvino_num_requests=1):
            self.is_openvino = False
            self.logger = logger
            options = runtime.SessionOptions()
            # DirectML requires sequential execution and disabled memory patterns.
            options.enable_mem_pattern = False
            options.execution_mode = runtime.ExecutionMode.ORT_SEQUENTIAL
            self.session = runtime.InferenceSession(model_dir, sess_options=options,
                                                   providers=['DmlExecutionProvider'])
            if 'DmlExecutionProvider' not in self.session.get_providers():
                raise RuntimeError('OCR session did not activate DirectML')

    # Predictor super() follows this local MRO into the provider constructor;
    # the dependency's detector/recognizer preprocessing and run methods remain intact.
    detector = type('NativeDmlTextDetector', (TextDetector, ProviderPredictBase), {})
    recognizer = type('NativeDmlTextRecognizer', (TextRecognizer, ProviderPredictBase), {})
    args = argparse.Namespace(**{action.dest: action.default for action in infer_args()._actions})
    args.rec_image_shape = '3, 48, 320'
    args.use_angle_cls, args.use_npu, args.use_openvino = False, False, False
    args.logger = logging.getLogger('onnxocr')
    engine = ONNXPaddleOcr.__new__(ONNXPaddleOcr)
    engine.logger = args.logger
    engine.text_detector, engine.text_recognizer = detector(args), recognizer(args)
    engine.use_angle_cls, engine.drop_score = False, args.drop_score
    engine.args, engine.crop_image_res_index = args, 0
    return engine
