"""Offline matching parity; no application, account or device initialization."""

import ast
import glob
import importlib.util
import json
import logging
import math
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile
import threading
from functools import cmp_to_key
from types import SimpleNamespace
from typing import List
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np
from PIL import Image

from src.vision import boxes
from src.vision.features import Feature, FeatureSet
from src.task.process_feature import process_feature
from src.combat.settings import TEMPLATE_MATCHING_DEFAULTS


ROOT = Path(__file__).resolve().parents[1]
COCO = ROOT / 'assets/coco_annotations.json'


def definitions(path, names=None):
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    return [node for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef))
            and (names is None or node.name in names)]


def execute(nodes, namespace, path):
    exec(compile(ast.Module(nodes, type_ignores=[]), str(path), 'exec'), namespace)


def signature(box):
    return (box.x, box.y, box.width, box.height, box.name, float(box.confidence))


class TestPackFeatureVision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The installed source is the independent reference. Extract pure
        # definitions rather than importing ok's Qt/device/application globals.
        old = Path(importlib.util.find_spec('ok').origin).parent
        namespace = dict(cv2=cv2, np=np, Image=Image, math=math, random=random,
                         re=re, os=os, json=json, glob=glob, threading=threading,
                         cmp_to_key=cmp_to_key, logger=logging.getLogger('reference'),
                         get_path_relative_to_exe=os.path.abspath,
                         communicate=Mock())
        for name in ('Box', 'Feature'):
            path = old / 'feature' / (name + '.py')
            execute(definitions(path), namespace, path)
        path = old / 'feature/FeatureSet.py'
        execute(definitions(path, {'FeatureSet', 'read_from_json', 'load_json',
                                  'un_fk_label_studio_path', 'adjust_coordinates',
                                  'scale_by_anchor', 'resize_image',
                                  'filter_and_sort_matches'}), namespace, path)
        namespace['FeatureSet']._draw_boxes_enabled = lambda self: False
        cls.reference = SimpleNamespace(**namespace)

        processor_ns = dict(cv2=cv2, np=np,
                            lower_white=np.array([244] * 3, np.uint8),
                            upper_white=np.array([255] * 3, np.uint8),
                            lower_icon_white=np.array([210] * 3, np.uint8),
                            upper_icon_white=np.array([244] * 3, np.uint8))
        # The new production processor imports only the pack's pure transforms.
        # Its independent baseline is the committed v64 source, before migration.
        for file, names in (
                ('src/task/BaseWWTask.py', {'convert_bw', 'convert_dialog_icon', 'binarize_for_matching'}),
                ('src/task/process_feature.py', {'process_feature'})):
            source = subprocess.run(['git', 'show', 'v1.97.64:' + file], cwd=ROOT,
                                    check=True, capture_output=True, text=True, encoding='utf-8').stdout
            nodes = [node for node in ast.parse(source).body
                     if isinstance(node, ast.FunctionDef) and node.name in names]
            execute(nodes, processor_ns, file)
        cls.reference_processor = staticmethod(processor_ns['process_feature'])
        baseline = subprocess.run(['git', 'show', 'v1.97.64:config.py'], cwd=ROOT,
                                  check=True, capture_output=True, text=True, encoding='utf-8').stdout
        config_tree = ast.parse(baseline)
        matching = next(node for node in ast.walk(config_tree)
                        if isinstance(node, ast.Dict) and any(
                            isinstance(key, ast.Constant) and key.value == 'coco_feature_json'
                            for key in node.keys))
        baseline_centers = {key.value: ast.literal_eval(value)
                       for key, value in zip(matching.keys, matching.values)
                       if isinstance(key, ast.Constant)
                       and key.value in {'hcenter_features', 'vcenter_features'}}
        cls.centers = {key: TEMPLATE_MATCHING_DEFAULTS[key]
                       for key in ('hcenter_features', 'vcenter_features')}
        if cls.centers != baseline_centers:
            raise AssertionError('Production matching anchors differ from v1.97.64')

        # Execute the unchanged production FindFeature methods at the seam,
        # using its real Box checks and arguments, but no GUI/config constructor.
        task_ns = dict(namespace, ExecutorOperation=object, List=List,
                       find_highest_confidence_box=namespace['find_highest_confidence_box'])
        path = old / 'task/task.py'
        execute(definitions(path, {'FindFeature'}), task_ns, path)
        cls.find_feature_api = task_ns['FindFeature']

    def pair(self, *, processor=False, **options):
        opts = dict(default_threshold=.8, **self.centers, **options)
        actual_opts = dict(opts)
        expected_opts = dict(opts)
        if processor:
            actual_opts['feature_processor'] = process_feature
            expected_opts['feature_processor'] = self.reference_processor
        return (FeatureSet(False, COCO, .002, .002, **actual_opts),
                self.reference.FeatureSet(False, str(COCO), .002, .002, **expected_opts))

    def assert_matches(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for a, e in zip(actual, expected):
            self.assertEqual(signature(a)[:5], signature(e)[:5])
            self.assertAlmostEqual(a.confidence, e.confidence, places=7)

    def test_import_and_real_match_without_frameworks(self):
        code = f'''
import sys
sys.path.insert(0, {str(ROOT)!r})
sys.modules['ok'] = None
sys.modules['gameframe'] = None
sys.modules['PySide6'] = None
import cv2
from src.vision.features import FeatureSet
from src.task.process_feature import process_feature
frame = cv2.imread({str(ROOT / 'assets/images/logout_power_icon.png')!r})
features = FeatureSet(False, {str(COCO)!r}, .002, .002, default_threshold=.7,
                      feature_processor=process_feature)
match = features.find_one_feature(frame, 'logout_power_icon', threshold=.6, limit=1)
assert len(match) == 1 and match[0].center() == (102, 1357)
assert not any(n.startswith(('ok.', 'gameframe.', 'PySide6.')) for n in sys.modules)
'''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-I', '-c', code], cwd=directory,
                           check=True, capture_output=True, text=True)

    def test_geometry_and_order_match_reference(self):
        frame = np.arange(100 * 120 * 3).reshape(100, 120, 3)
        actual = boxes.Box(2.4, 4.7, 17.2, 21.5, .81, 'a')
        expected = self.reference.Box(2.4, 4.7, 17.2, 21.5, .81, 'a')
        for a, e in ((actual, expected),
                     (actual.scale(1.4, .7), expected.scale(1.4, .7)),
                     (actual.copy(3, 7, 2, 1, 'b'), expected.copy(3, 7, 2, 1, 'b'))):
            self.assertEqual(signature(a), signature(e))
            self.assertEqual(a.center(), e.center())
            np.testing.assert_array_equal(a.crop_frame(frame), e.crop_frame(frame))
        args = [(30, 1, 10, 20, .9, 'b'), (2, 6, 12, 16, .9, 'a'),
                (2, 60, 12, 16, .9, 'c')]
        a = boxes.sort_boxes([boxes.Box(*arg) for arg in args])
        e = self.reference.sort_boxes([self.reference.Box(*arg) for arg in args])
        self.assertEqual(list(map(signature, a)), list(map(signature, e)))
        self.assertEqual(boxes.find_box_by_name(a, ['c', 'a']).name, 'c')
        self.assertEqual([b.name for b in boxes.find_boxes_by_name(a, re.compile('[ab]'))], ['a', 'b'])
        self.assertEqual(signature(boxes.get_bounding_box(a)),
                         signature(self.reference.get_bounding_box(e)))
        self.assertEqual([b.name for b in actual.in_boundary(a)],
                         [b.name for b in expected.in_boundary(e)])
        self.assertEqual(actual.closest_distance(a[-1]), expected.closest_distance(e[-1]))

    def test_existing_screenshots_default_gray_canny_and_labels(self):
        for filename, labels in (
                ('con_full.png', ['char_1_text', 'char_rover', 'e_forte']),
                ('combat_has_cd.png', ['char_2_text', 'char_carlotta', 'e_forte']),
                ('all_cd_1080p.png', ['char_1_text', 'char_camellya', 'e_forte']),
                ('angle_130.png', ['arrow']), ('mini_map.png', ['arrow']),
                ('path.png', ['arrow'])):
            frame = cv2.imread(str(ROOT / 'tests/images' / filename))
            self.assertIsNotNone(frame, filename)
            actual, expected = self.pair()
            for label in labels:
                self.assertTrue(actual.feature_exists(label), label)
                for opts in ({}, {'use_gray_scale': True},
                             {'canny_lower': 50, 'canny_higher': 150}):
                    with self.subTest(image=filename, label=label, opts=opts):
                        threshold = .2 if label == 'arrow' else .8
                        self.assert_matches(
                            actual.find_one_feature(frame, label, threshold=threshold, limit=1, **opts),
                            expected.find_one_feature(frame, label, threshold=threshold, limit=1, **opts))
                if filename != 'path.png':  # This arrow fixture requires rotation at the task layer.
                    self.assertTrue(actual.find_one_feature(
                        frame, labels[0], threshold=.2 if labels[0] == 'arrow' else .8, limit=1))

    def test_all_processor_labels_and_resolution_cache(self):
        actual, expected = self.pair(processor=True)
        frames = [np.zeros((1080, 1920, 3), np.uint8),
                  np.zeros((1440, 3440, 3), np.uint8)]
        for frame in frames:
            for label in ('illusive_realm_exit', 'purple_target_distance_icon',
                          'world_earth_icon', 'skip_dialog', 'mouse_forte', 'e_forte'):
                with self.subTest(size=frame.shape, label=label):
                    a = actual.get_feature_by_name(frame, label)
                    e = expected.get_feature_by_name(frame, label)
                    self.assertIsNotNone(a)
                    np.testing.assert_array_equal(a.mat, e.mat)
                    self.assertEqual((a.x, a.y, a.scaling), (e.x, e.y, e.scaling))
                    self.assert_matches(actual.find_one_feature(frame, label, limit=1),
                                        expected.find_one_feature(frame, label, limit=1))

    def test_real_templates_roi_external_mask_scaling_and_list(self):
        for file, label in (('logout_power_icon.png', 'logout_power_icon'), ('35.png', 'chisa_e2')):
            frame = cv2.imread(str(ROOT / 'assets/images' / file))
            actual, expected = self.pair()
            feature = actual.get_feature_by_name(frame, label)
            box = actual.get_box_by_name(frame, label).scale(1.5)
            mask = lambda mat: np.full(mat.shape[:2], 255, np.uint8)
            options = [dict(limit=1), dict(box=box, limit=1),
                       dict(x=0, y=0, to_x=1, to_y=1, limit=1),
                       dict(template=feature.mat, box=box, limit=1),
                       dict(mask_function=mask, match_method=cv2.TM_CCORR_NORMED,
                            box=box, target_height=720, limit=2),
                       dict(target_height=720, limit=1)]
            for opts in options:
                with self.subTest(file=file, opts=tuple(opts)):
                    self.assert_matches(actual.find_one_feature(frame, label, **opts),
                                        expected.find_one_feature(frame, label, **opts))
            self.assert_matches(actual.find_feature(frame, [label, label], limit=1),
                                expected.find_feature(frame, [label, label], limit=1))
            self.assertTrue(actual.find_one_feature(frame, label, threshold=.6, limit=1))

    def test_nms_order_and_target_height_coordinates(self):
        rng = np.random.default_rng(12)
        template = rng.integers(0, 256, (12, 10, 3), np.uint8)
        frame = np.zeros((160, 180, 3), np.uint8)
        frame[20:32, 70:80] = template
        frame[80:92, 20:30] = template
        actual, expected = self.pair()
        for opts in (dict(limit=0), dict(limit=1), dict(limit=2),
                     dict(target_height=80, limit=2),
                     dict(use_gray_scale=True, limit=2),
                     dict(frame_processor=lambda mat: mat.astype(np.float32), limit=2)):
            self.assert_matches(actual.find_one_feature(frame, None, template=template, **opts),
                                expected.find_one_feature(frame, None, template=template, **opts))
        result = actual.find_one_feature(frame, None, template=template, threshold=.99)
        self.assertEqual([(b.x, b.y) for b in result], [(70, 20), (20, 80)])

    def test_lazy_image_and_preprocess_cache(self):
        frame = cv2.imread(str(ROOT / 'assets/images/logout_power_icon.png'))
        features = FeatureSet(False, COCO, .002, .002)
        with patch('src.vision.features.cv2.imread', wraps=cv2.imread) as read:
            first = features.get_feature_by_name(frame, 'logout_power_icon')
            self.assertEqual(read.call_count, 1)
            second = features.get_feature_by_name(frame, 'logout_power_icon')
            self.assertIs(first, second)
            self.assertEqual(read.call_count, 1)
        features.find_one_feature(frame, 'logout_power_icon', use_gray_scale=True, limit=1)
        cached = first.template_cache[(True, 0, 0)]
        features.find_one_feature(frame, 'logout_power_icon', use_gray_scale=True, limit=1)
        self.assertIs(cached, first.template_cache[(True, 0, 0)])
        mask = Mock(side_effect=lambda mat: np.full(mat.shape[:2], 255, np.uint8))
        for _ in range(2):
            features.find_one_feature(frame, 'logout_power_icon', mask_function=mask,
                                      match_method=cv2.TM_CCORR_NORMED, limit=1)
        self.assertEqual(mask.call_count, 1)
        resized = cv2.resize(frame, (1920, 1080))
        self.assertIsNot(first, features.get_feature_by_name(resized, 'logout_power_icon'))

    def test_failure_contract_and_diagnostics(self):
        features = FeatureSet(False, COCO, .002, .002)
        frame = np.zeros((37, 33, 3), np.uint8)
        self.assertEqual(features.find_one_feature(None, 'missing'), [])
        self.assertIsNone(features.get_box_by_name(None, 'missing'))
        self.assertIsNone(features.get_feature_by_name(frame, 'missing'))
        with self.assertRaises(ValueError):
            features.find_one_feature(frame, 'missing')
        features.feature_dict['large'] = Feature(np.zeros((39, 32, 3), np.uint8))
        with self.assertRaises(cv2.error):
            features.find_one_feature(frame, 'large', box=boxes.Box(0, 0, 33, 37))
        template = np.ones((8, 8, 3), np.uint8)
        for kw in ('frame_processor', 'mask_function'):
            with self.assertRaisesRegex(RuntimeError, 'processor failed'):
                features.find_one_feature(frame, None, template=template,
                                          **{kw: Mock(side_effect=RuntimeError('processor failed'))})
        feature_processor = Mock(side_effect=RuntimeError('processor failed'))
        failed = FeatureSet(False, COCO, .002, .002, feature_processor=feature_processor)
        with self.assertRaisesRegex(RuntimeError, 'processor failed'):
            failed.get_feature_by_name(frame, 'logout_power_icon')
        self.assertEqual(failed._processed_images, set())
        self.assertTrue(failed.empty())
        events = []
        features.observer = lambda event, **payload: events.append((event, payload))
        features.find_one_feature(frame, None, template=template, screenshot=True, limit=1)
        self.assertEqual([payload['name'] for _, payload in events],
                         ['mat', 'search_area', 'template'])
        self.assertIs(events[0][1]['image'], frame)
        features.observer = Mock(side_effect=RuntimeError('diagnostics failed'))
        with self.assertLogs('src.vision.features', level='ERROR'):
            result = features.find_one_feature(frame, None, template=template,
                                               screenshot=True, limit=1)
        self.assertTrue(result)

    def test_explicit_namespace_overwrite_and_asset_boundary(self):
        rng = np.random.default_rng(1)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            cv2.imwrite(str(folder / 'image.png'), rng.integers(0, 256, (40, 60, 3), np.uint8))
            data = dict(images=[dict(id=1, file_name='image.png')],
                        categories=[dict(id=1, name='icon'), dict(id=2, name='other')],
                        annotations=[dict(image_id=1, category_id=1, bbox=[2, 3, 10, 11]),
                                     dict(image_id=1, category_id=2, bbox=[30, 20, 9, 10])])
            path = folder / 'coco.json'
            path.write_text(json.dumps(data), encoding='utf-8')
            features = FeatureSet(False, path, 0, 0)
            features.add_coco(path, namespace='extension', overwrite=True)
            frame = cv2.imread(str(folder / 'image.png'))
            features.get_feature_by_name(frame, 'icon')
            self.assertIn('other', features.feature_dict)  # Whole annotated image loaded once.
            self.assertEqual(features.get_box_by_name(frame, 'extension/icon').name, 'extension/icon')
            override = folder / 'override.json'
            data['annotations'][0]['bbox'][0] = 7
            override.write_text(json.dumps(data), encoding='utf-8')
            features.add_coco(override, overwrite=True)
            self.assertEqual(features.get_box_by_name(frame, 'icon').x, 7)
            data['images'][0]['file_name'] = 'missing.png'
            override.write_text(json.dumps(data), encoding='utf-8')
            bad = FeatureSet(False, override, 0, 0)
            with self.assertRaisesRegex(ValueError, 'Could not read image'):
                bad.get_feature_by_name(frame, 'icon')

    def test_production_find_feature_seam_uses_injected_box(self):
        frame = cv2.imread(str(ROOT / 'assets/images/logout_power_icon.png'))
        features = FeatureSet(False, COCO, .002, .002, box_factory=self.reference.Box)
        task = self.find_feature_api()
        task.executor = SimpleNamespace(frame=frame, feature_set=features)
        task.frame = frame
        found = task.find_one('logout_power_icon', threshold=.6)
        self.assertIsInstance(found, self.reference.Box)
        self.assertEqual(found.center(), (102, 1357))
        self.assertIs(task.get_box_by_name(found), found)
        self.assertIsInstance(task.get_box_by_name('logout_power_icon'), self.reference.Box)


if __name__ == '__main__':
    unittest.main()
