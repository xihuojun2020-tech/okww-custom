"""Metadata-safe entrypoint for real production combat on the independent runtime."""

import json
import os
from pathlib import Path
import sys


class WutheringWavesNativePackage:
    def __init__(self):
        self.root = Path(__file__).resolve().parent
        self.manifest = json.loads((self.root / 'manifest.json').read_text(encoding='utf-8'))
        self.engine = None

    def run(self, task_id, context):
        if task_id != 'auto-combat':
            raise KeyError(f'Unknown native Wuthering Waves task: {task_id}')
        source = (self.root / self.manifest['source_root']).resolve()
        sys.path.insert(0, str(source))
        from src.runtime.native_logging import configure_logging
        from src.runtime.native_combat_host import NativeCombatHost
        from src.combat.settings import COMBAT_GLOBAL_DEFAULTS, TEMPLATE_MATCHING_DEFAULTS

        data_dir = Path(context.data_dir).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        configure_logging(data_dir)
        previous_cwd = Path.cwd()
        try:
            # The OCR dependency writes compiled model caches relative to cwd.
            # This worker owns its process; private writable data stays outside the pack.
            os.chdir(data_dir)
            if self.engine is None:
                from onnxocr.onnx_paddleocr import ONNXPaddleOcr
                self.engine = ONNXPaddleOcr(use_angle_cls=False, use_npu=False, use_openvino=True)
            host = NativeCombatHost(
                context, coco_path=source / 'assets/coco_annotations.json',
                global_options=COMBAT_GLOBAL_DEFAULTS, ocr_engine=self.engine,
                template_matching=TEMPLATE_MATCHING_DEFAULTS, native=True,
                device_identity=type(context.device).__name__)
            return host.run_service()
        finally:
            os.chdir(previous_cwd)


def create_package():
    return WutheringWavesNativePackage()
