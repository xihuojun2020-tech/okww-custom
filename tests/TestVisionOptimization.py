import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4
import numpy as np
import cv2


class TestVisionOptimization(unittest.TestCase):
    def test_catalog_reuses_only_exact_icon_and_threshold(self):
        from src.materials.catalog import Catalog
        catalog = Catalog()
        frame = np.zeros((120, 120, 3), np.uint8)
        with patch('src.materials.catalog.cv2.matchTemplate', wraps=cv2.matchTemplate) as match:
            first = catalog.match(frame)
            count = match.call_count
            self.assertGreater(count, 0)
            self.assertEqual(catalog.match(frame.copy()), first)
            self.assertEqual(match.call_count, count)
            catalog.match(frame, threshold=.9)
            self.assertEqual(match.call_count, count * 2)
            frame[40:50, 40:50] = 255
            catalog.match(frame)
            self.assertEqual(match.call_count, count * 3)

    def test_required_original_encoded_once_and_still_decoded(self):
        from src.evidence.repository import EvidenceRepository
        from src.evidence.model import now_iso
        with tempfile.TemporaryDirectory() as directory:
            repo = EvidenceRepository(directory)
            metadata = dict(profile_id=str(uuid4()), project_id='daily_activity', source='automatic',
                            completion_status='completed', require_image=True, event_id=str(uuid4()),
                            captured_at=now_iso())
            frame = np.zeros((720, 1280, 3), np.uint8)
            with patch('src.evidence.repository.cv2.imencode', wraps=cv2.imencode) as encode, \
                    patch('src.evidence.repository.cv2.imdecode', wraps=cv2.imdecode) as decode:
                saved = repo.save(metadata, frame)
                full = [c for c in encode.call_args_list if c.args[1].shape == frame.shape]
                self.assertEqual(len(full), 1)
                self.assertGreater(decode.call_count, 0)
                self.assertTrue(repo.asset_path(saved['image_path']).is_file())

    def test_material_static_scan_saves_one_original_per_claim(self):
        from src.task.MaterialPlannerTask import MaterialPlannerTask
        task = MaterialPlannerTask.__new__(MaterialPlannerTask)
        frame = np.zeros((1152, 2048, 3), np.uint8)
        task.next_frame = Mock()
        task.require_game_frame = Mock(return_value=frame)
        task.scroll_relative = Mock()
        task.sleep = Mock()
        task._save_frame = Mock()
        task.catalog = None
        def parser(*_): return dict(scene='reward', cells=[], errors=[])
        for claim in ('claim1', 'claim2'):
            pages = task._pages(parser, claim, (0, 0, 200, 100), (.5, .5))
            self.assertTrue(pages[0]['at_top'])
            self.assertTrue(pages[0]['at_bottom'])
            self.assertEqual(len(pages[0]['observations']), 3)
        self.assertEqual(task._save_frame.call_count, 2)
        self.assertEqual([c.args[0] for c in task._save_frame.call_args_list], ['claim1', 'claim2'])

    def test_backend_setting_reaches_compile_and_preserves_npu(self):
        from src.runtime.ocr_backend import configure_backend
        predictor = Mock(is_openvino=True, is_npu=False, model_dir='model.onnx')
        model = Mock()
        model.inputs = [Mock(any_name='input')]
        core = Mock()
        core.read_model.return_value = model
        engine = Mock(text_detector=predictor, text_recognizer=Mock(is_openvino=True, is_npu=True))
        with patch('openvino.Core', return_value=core), patch('openvino.AsyncInferQueue'):
            configure_backend(engine, Mock(), cpu_threads=4)
        self.assertEqual(core.compile_model.call_count, 1)
        self.assertEqual(core.compile_model.call_args.kwargs['config']['INFERENCE_NUM_THREADS'], 4)


if __name__ == '__main__': unittest.main()
