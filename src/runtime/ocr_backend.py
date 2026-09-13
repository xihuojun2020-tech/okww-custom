"""Configure installed ONNXPaddleOcr before publishing it to task threads.

Keep dependency files untouched. CPU models are recompiled once at initialization
because onnxocr 0.0.20 does not forward compile properties. NPU stays unchanged.
"""
import json
import os
from pathlib import Path


def configure_backend(engine, logger, *, cpu_threads=None):
    if cpu_threads is None:
        config = Path(__file__).resolve().parents[2] / 'configs/vision_performance.json'
        values = json.loads(config.read_text(encoding='utf-8')) if config.exists() else {}
        # Preserve the established default until game-concurrent acceptance.
        cpu_threads = values.get('ocr_cpu_threads', 0)
    if not isinstance(cpu_threads, int) or not 0 <= cpu_threads <= 64:
        raise ValueError('ocr_cpu_threads must be 0 (backend default) or 1..64')
    stats = {}
    for name in ('text_detector', 'text_recognizer'):
        predictor = getattr(engine, name, None)
        if predictor is None or not getattr(predictor, 'is_openvino', False): continue
        if cpu_threads and not predictor.is_npu:
            import openvino as ov
            try:
                core = ov.Core()
                cache = Path.cwd() / 'cache/openvino'
                cache.mkdir(parents=True, exist_ok=True)
                core.set_property({'CACHE_DIR': str(cache)})
                model = core.read_model(model=predictor.model_dir)
                model.reshape({model.inputs[0].any_name: [-1, 3, -1, -1]})
                session = core.compile_model(model=model, device_name='CPU', config={
                    'INFERENCE_NUM_THREADS': min(cpu_threads, os.cpu_count() or 1), 'NUM_STREAMS': 1})
                queue = ov.AsyncInferQueue(session, jobs=1)
                queue.set_callback(predictor._on_openvino_complete)
                predictor._async_queue.wait_all()
                predictor.session, predictor._async_queue = session, queue
            except Exception as error:
                logger.warning(f'OCR thread configuration unavailable; keeping backend default: {type(error).__name__}')
        actual = {}
        for prop in ('EXECUTION_DEVICES', 'INFERENCE_NUM_THREADS', 'NUM_STREAMS'):
            try: actual[prop] = str(predictor.session.get_property(prop))
            except Exception: actual[prop] = 'unsupported'
        stats[name] = actual
    logger.info(f'OCR actual backend settings: {stats}')
    engine.okww_backend = stats
    return engine
