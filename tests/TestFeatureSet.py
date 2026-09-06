import unittest
from unittest.mock import patch

import cv2
import numpy as np

from ok.feature.Box import Box
from ok.feature.Feature import Feature
from ok.feature.FeatureSet import FeatureSet
from src.Labels import Labels


class TestFeatureSet(unittest.TestCase):
    def test_cached_arrow_rotations_preserve_existing_sample_matches(self):
        from src.task.BaseWWTask import BaseWWTask
        for filename, expected_angle, expected_confidence in (
                ('angle_130.png', 134, .5515261888504028),
                ('mini_map.png', 24, .6617346405982971),
                ('path.png', 158, .3197648227214813)):
            with self.subTest(sample=filename):
                frame = cv2.imread('tests/images/' + filename)
                self.assertIsNotNone(frame)
                features = FeatureSet(False, 'assets/coco_annotations.json', .002, .002, default_threshold=.7)
                task = BaseWWTask.__new__(BaseWWTask)
                task.get_feature_by_name = lambda name: features.get_feature_by_name(frame, name)
                task.get_box_by_name = lambda name: features.get_box_by_name(frame, name)
                def find(**kwargs):
                    boxes = features.find_one_feature(frame, None, **kwargs)
                    return boxes[0] if boxes else None
                task.find_one = find
                with patch.object(cv2, 'warpAffine', wraps=cv2.warpAffine) as rotate:
                    first = task.rotate_arrow_and_find()
                    self.assertEqual(rotate.call_count, 360)
                    second = task.rotate_arrow_and_find()
                    self.assertEqual(rotate.call_count, 360)
                    self.assertEqual(first[0], expected_angle)
                    self.assertEqual(first[0], second[0])
                    self.assertAlmostEqual(first[1].confidence, expected_confidence, places=6)
                    self.assertEqual(first[1].confidence, second[1].confidence)
                    feature = task.get_feature_by_name('arrow')
                    feature.mat[0, 0] ^= 1
                    task.rotate_arrow_and_find()
                    self.assertEqual(rotate.call_count, 720)

    def test_qingxiao_templates_are_loadable(self):
        feature_set = FeatureSet(
            False,
            'assets/coco_annotations.json',
            0.002,
            0.002,
            default_threshold=0.7,
        )
        frame = np.zeros((2160, 3840, 3), dtype=np.uint8)

        for label in (
            Labels.char_qingxiao,
            Labels.qingxiao_e,
            Labels.qingxiao_h1,
            Labels.qingxiao_h2,
        ):
            feature = feature_set.get_feature_by_name(frame, label)
            self.assertIsNotNone(feature, label)
            self.assertIsNotNone(feature.mat, label)
            self.assertGreater(feature.mat.size, 0, label)

    def test_logout_power_icon_template_keeps_game_resolution_scale(self):
        frame = cv2.imread('assets/images/logout_power_icon.png')
        self.assertEqual((1440, 2560), frame.shape[:2])

        feature_set = FeatureSet(
            False,
            'assets/coco_annotations.json',
            0.002,
            0.002,
            default_threshold=0.7,
        )
        matches = feature_set.find_one_feature(
            frame,
            'logout_power_icon',
            threshold=0.6,
        )

        self.assertTrue(matches)
        self.assertEqual((102, 1357), matches[0].center())

    def test_chisa_e2_template_loads_from_current_source_image(self):
        frame = cv2.imread('assets/images/35.png')
        self.assertIsNotNone(frame)

        feature_set = FeatureSet(
            False,
            'assets/coco_annotations.json',
            0.002,
            0.002,
            default_threshold=0.7,
        )
        matches = feature_set.find_one_feature(
            frame,
            'chisa_e2',
            threshold=0.7,
        )

        self.assertTrue(matches)
        self.assertEqual(matches[0].name, 'chisa_e2')
        self.assertGreaterEqual(float(matches[0].confidence), 0.7)

    def test_template_larger_than_search_area_raises(self):
        feature_set = FeatureSet(False, 'missing.json', 0.002, 0.002, default_threshold=0.8)
        feature_set.width = 33
        feature_set.height = 37
        feature_set.feature_dict['large_template'] = Feature(np.zeros((39, 32, 3), dtype=np.uint8))

        frame = np.zeros((37, 33, 3), dtype=np.uint8)
        with self.assertRaises(cv2.error):
            feature_set.find_one_feature(
                frame,
                'large_template',
                box=Box(0, 0, 33, 37, name='small_search'),
            )


if __name__ == '__main__':
    unittest.main()
