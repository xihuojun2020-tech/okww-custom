# SPDX-License-Identifier: AGPL-3.0-or-later
# Derived from ok-script 1.0.190's AGPL production geometry/feature matching.
# Kept in the AGPL game pack, independently of the GameFrame core.
"""COCO templates and production matching without framework/UI/device imports."""

import json
import logging
import math
import os
import re
import threading

import cv2
import numpy as np

from src.vision.boxes import Box, sort_boxes

logger = logging.getLogger(__name__)

class Feature:

    def __init__(self, mat: np.ndarray, x: int=0, y: int=0, scaling=1) -> None:
        self.mat = mat
        self.scaling = scaling
        self.x = round(x)
        self.y = round(y)
        self.mask = None
        self.template_cache = {}

    @property
    def width(self):
        return self.mat.shape[1]

    @property
    def height(self):
        return self.mat.shape[0]

    def __str__(self) -> str:
        return str(f'self.x: {self.x}, self.y: {self.y}, width: {self.width}, height: {self.height}')

class FeatureSet:

    def __init__(self, debug, coco_json, default_horizontal_variance,
                 default_vertical_variance, default_threshold=.95, feature_processor=None,
                 hcenter_features=None, vcenter_features=None, *, box_factory=Box, observer=None):
        self.coco_json = os.path.abspath(coco_json)
        self.debug = debug
        self.feature_processor = feature_processor
        self.hcenter_features = hcenter_features if hcenter_features is not None else []
        self.vcenter_features = vcenter_features if vcenter_features is not None else []
        self.default_threshold = .95 if default_threshold == 0 else default_threshold
        self.default_horizontal_variance = default_horizontal_variance
        self.default_vertical_variance = default_vertical_variance
        self.box_factory = box_factory
        self.observer = observer
        self.width = self.height = 0
        self.feature_dict = {}
        self.box_dict = {}
        self._processed_images = set()
        self._coco_sources = [(self.coco_json, None, False)]
        self.load_success = False
        self.lock = threading.Lock()

    def feature_exists(self, feature_name: str) -> bool:
        self.ensure_feature(feature_name)
        return feature_name in self.feature_dict

    def empty(self) -> bool:
        return len(self.feature_dict) == 0 and len(self.box_dict) == 0

    def check_size(self, frame) -> bool:
        with self.lock:
            height, width = frame.shape[:2]
            if (self.width != width or self.height != height) and height > 0 and (width > 0):
                logger.info(f'FeatureSet: Width and height changed from {self.width}x{self.height} to {width}x{height}')
                self.width = width
                self.height = height
                self.feature_dict = {}
                self.box_dict = {}
                self._processed_images = set()
                self.load_success = os.path.exists(self.coco_json)
        return self.load_success

    def ensure_feature(self, feature_name):
        if feature_name is None or feature_name in self.feature_dict:
            return
        with self.lock:
            if feature_name not in self.feature_dict:
                self.process_data(feature_name)

    def get_box_by_name(self, mat, category_name):
        if mat is None:
            return None
        self.check_size(mat)
        self.ensure_feature(category_name)
        return self.box_dict.get(category_name)

    def get_feature_by_name(self, mat, name):
        if mat is None:
            return None
        self.check_size(mat)
        self.ensure_feature(name)
        return self.feature_dict.get(name)

    def find_one_feature(self, mat: np.ndarray, category_name,
                         horizontal_variance: float = 0, vertical_variance: float = 0,
                         threshold: float = 0, use_gray_scale: bool = False,
                         x=-1, y=-1, to_x=-1, to_y=-1, width=-1, height=-1, box=None,
                         canny_lower=0, canny_higher=0, frame_processor=None,
                         template=None, mask_function=None,
                         match_method=cv2.TM_CCOEFF_NORMED,
                         screenshot=False, limit=0, target_height=0):
        if mat is None:
            return []
        self.check_size(mat)
        if threshold == 0:
            threshold = self.default_threshold
        if horizontal_variance == 0:
            horizontal_variance = self.default_horizontal_variance
        if vertical_variance == 0:
            vertical_variance = self.default_vertical_variance
        if template is None:
            self.ensure_feature(category_name)
        if template is None and category_name not in self.feature_dict:
            raise ValueError(f'FeatureSet: {category_name} not found in featureDict')
        if template is None:
            feature = self.feature_dict[category_name]
            template = feature.mat
        else:
            feature = None
        if box is not None:
            search_x1 = max(box.x, 0)
            search_y1 = max(box.y, 0)
            search_x2 = min(box.x + box.width, mat.shape[1])
            search_y2 = min(box.y + box.height, mat.shape[0])
        elif x != -1 and y != -1:
            frame_height, frame_width, *_ = mat.shape
            if width == -1:
                width = to_x - x
            if height == -1:
                height = to_y - y
            search_x1 = round(x * frame_width)
            search_y1 = round(y * frame_height)
            search_x2 = round((x + width) * frame_width)
            search_y2 = round((y + height) * frame_height)
        elif feature is None:
            search_x1 = 0
            search_y1 = 0
            search_y2, search_x2 = mat.shape[:2]
        else:
            x_offset = self.width * horizontal_variance
            y_offset = self.height * vertical_variance
            if feature.scaling != 1:
                if horizontal_variance == 0:
                    x_offset = 1
                if vertical_variance == 0:
                    y_offset = 1
            search_x1 = max(0, round(feature.x - x_offset))
            search_y1 = max(0, round(feature.y - y_offset))
            feature_width, feature_height = (feature.width, feature.height)
            search_x2 = min(self.width, round(feature.x + feature_width + x_offset))
            search_y2 = min(self.height, round(feature.y + feature_height + y_offset))
        search_area = mat[search_y1:search_y2, search_x1:search_x2, :3]
        feature_height, feature_width = template.shape[:2]
        preprocess_key = None
        if use_gray_scale or (canny_lower != 0 and canny_higher != 0):
            preprocess_key = (bool(use_gray_scale), canny_lower, canny_higher)
            cached_template = feature.template_cache.get(preprocess_key) if feature is not None else None
        else:
            cached_template = None
        if cached_template is not None:
            template = cached_template
        if use_gray_scale:
            search_area = cv2.cvtColor(search_area, cv2.COLOR_BGR2GRAY)
            if cached_template is None and len(template.shape) != 2:
                template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        if canny_lower != 0 and canny_higher != 0:
            if len(search_area.shape) != 2:
                search_area = cv2.cvtColor(search_area, cv2.COLOR_BGR2GRAY)
            search_area = cv2.Canny(search_area, canny_lower, canny_higher)
            if cached_template is None and len(template.shape) != 2:
                template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
            if cached_template is None:
                template = cv2.Canny(template, canny_lower, canny_higher)
        if feature is not None and preprocess_key is not None and (cached_template is None):
            feature.template_cache[preprocess_key] = template
        if feature is not None and feature.mask is None:
            if mask_function is not None:
                feature.mask = mask_function(feature.mat)
        mask = None
        if feature is not None:
            mask = feature.mask
        elif mask_function is not None:
            mask = mask_function(template)
        if frame_processor is not None:
            search_area = frame_processor(search_area)
        if template.shape[1] > search_area.shape[1] or template.shape[0] > search_area.shape[0]:
            logger.error(f"feature template {category_name} {(box.name if box else '')} size greater than search area {template.shape} > {search_area.shape}")
        scale_factor = 1.0
        if target_height > 0:
            search_area, scale_factor = resize_image(search_area, mat.shape[0], target_height)
            if scale_factor != 1:
                template = cv2.resize(template, (0, 0), fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_AREA)
                if mask is not None:
                    mask = cv2.resize(mask, (template.shape[1], template.shape[0]), interpolation=cv2.INTER_NEAREST)
        if search_area.dtype != template.dtype or search_area.ndim != template.ndim:
            logger.warning(
                f'Type mismatch for {category_name}: '
                f'search_area={search_area.shape} {search_area.dtype}, '
                f'template={template.shape} {template.dtype}')
            if search_area.dtype != template.dtype:
                template = template.astype(search_area.dtype)
            if search_area.ndim == 3 and template.ndim == 2:
                template = cv2.cvtColor(template, cv2.COLOR_GRAY2BGR)
            elif search_area.ndim == 2 and template.ndim == 3:
                search_area = cv2.cvtColor(search_area, cv2.COLOR_GRAY2BGR)
        result = cv2.matchTemplate(search_area, template, match_method, mask=mask)
        np.nan_to_num(result, copy=False, nan=0, posinf=0, neginf=0)
        if screenshot:
            logger.info(f'template matching screenshot match_method:{match_method} canny:{(canny_lower, canny_higher)}')
            self._observe('screenshot', image=mat, name='mat', save=True, box=None)
            self._observe('screenshot', image=search_area, name='search_area', save=False, box=box)
            self._observe('screenshot', image=template, name='template', save=False, box=None)
        boxes = []
        if limit == 1 and match_method == cv2.TM_CCOEFF_NORMED:
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            if max_val >= threshold:
                x, y = (round(max_loc[0] / scale_factor) + search_x1, round(max_loc[1] / scale_factor) + search_y1)
                boxes.append(self.box_factory(x, y, feature_width, feature_height, max_val, category_name))
        else:
            locations = filter_and_sort_matches(result, threshold, template.shape[1], template.shape[0])
            for loc in locations:
                x, y = (round(loc[0][0] / scale_factor) + search_x1, round(loc[0][1] / scale_factor) + search_y1)
                confidence = 1.0 if math.isinf(loc[1]) and loc[1] > 0 else loc[1]
                boxes.append(self.box_factory(x, y, feature_width, feature_height, confidence, category_name))
            boxes = sort_boxes(boxes)
            if limit > 0:
                boxes = boxes[:limit]
        if category_name and self.debug:
            self._observe('draw_box', name=category_name, boxes=boxes, color='red')
            search_name = 'search_' + category_name
            self._observe(
                'draw_box', name=search_name,
                boxes=self.box_factory(search_x1, search_y1, search_x2 - search_x1,
                                       search_y2 - search_y1, name=search_name),
                color='blue')
        return boxes

    def find_feature(self, mat: np.ndarray, category_name,
                     horizontal_variance: float = 0, vertical_variance: float = 0,
                     threshold: float = 0, use_gray_scale: bool = False,
                     x=-1, y=-1, to_x=-1, to_y=-1, width=-1, height=-1, box=None,
                     canny_lower=0, canny_higher=0, frame_processor=None,
                     template=None, mask_function=None,
                     match_method=cv2.TM_CCOEFF_NORMED,
                     screenshot=False, limit=0, target_height=0):
        if mat is None:
            return []
        if type(category_name) is list:
            results = []
            for cn in category_name:
                results += self.find_one_feature(
                    mat=mat, category_name=cn, horizontal_variance=horizontal_variance,
                    vertical_variance=vertical_variance, threshold=threshold,
                    use_gray_scale=use_gray_scale, x=x, y=y, to_x=to_x, to_y=to_y,
                    width=width, height=height, box=box, canny_lower=canny_lower,
                    canny_higher=canny_higher, frame_processor=frame_processor,
                    template=template, mask_function=mask_function,
                    match_method=match_method, screenshot=screenshot, limit=limit,
                    target_height=target_height)
            return sort_boxes(results)
        else:
            return self.find_one_feature(
                mat=mat, category_name=category_name, horizontal_variance=horizontal_variance,
                vertical_variance=vertical_variance, threshold=threshold,
                use_gray_scale=use_gray_scale, x=x, y=y, to_x=to_x, to_y=to_y,
                width=width, height=height, box=box, canny_lower=canny_lower,
                canny_higher=canny_higher, frame_processor=frame_processor,
                template=template, mask_function=mask_function,
                match_method=match_method, screenshot=screenshot, limit=limit,
                target_height=target_height)

    def add_coco(self, coco_json, *, namespace=None, overwrite=False):
        """Register a pack asset explicitly; never scan the caller's cwd."""
        with self.lock:
            self._coco_sources.append((os.path.abspath(coco_json), namespace, overwrite))
            self.feature_dict = {}
            self.box_dict = {}
            self._processed_images = set()

    def process_data(self, feature_name=None):
        if feature_name is None:
            self.feature_dict = {}
            self.box_dict = {}
            self._processed_images = set()
        for path, namespace, overwrite in self._coco_sources:
            target = feature_name
            if namespace and target:
                if not target.startswith(namespace + '/'):
                    continue
                target = target[len(namespace) + 1:]
            features, boxes, keys = read_from_json(
                path, self.width, self.height, self.hcenter_features, self.vcenter_features,
                target_category_name=target, processed_images=self._processed_images,
                image_key_prefix=namespace, box_factory=self.box_factory)
            pending = {}
            for name, feature in features.items():
                qualified = namespace + '/' + name if namespace else name
                if qualified in self.feature_dict and not overwrite:
                    continue
                if self.feature_processor:
                    self.feature_processor(qualified, feature)
                box = boxes[name]
                pending[qualified] = (feature, self.box_factory(
                    box.x, box.y, box.width, box.height, box.confidence, qualified))
            for name, (feature, box) in pending.items():
                self.feature_dict[name] = feature
                self.box_dict[name] = box
            self._processed_images.update(keys)
        self.load_success = True
        return self.load_success

    def _observe(self, event, **payload):
        if self.observer is not None:
            try:
                self.observer(event, **payload)
            except Exception:
                # Combat diagnostics must not stop the enabled combat service.
                logger.exception('Vision diagnostic consumer failed: %s', event)


def read_from_json(coco_json, width=-1, height=-1,
                   hcenter_features=None, vcenter_features=None, adjust=True,
                   target_category_name=None, processed_images=None,
                   image_key_prefix=None, box_factory=Box):
    feature_dict = {}
    box_dict = {}
    loaded_image_keys = set()
    data = load_json(coco_json)
    coco_folder = os.path.dirname(coco_json)
    logger.info(f'read_from_json {coco_folder} {coco_json}')
    image_map = {image['id']: image['file_name'] for image in data['images']}
    category_map = {category['id']: category['name'] for category in data['categories']}
    annotations_by_image = {}
    target_image_ids = set()
    for annotation in data['annotations']:
        annotations_by_image.setdefault(annotation['image_id'], []).append(annotation)
        if target_category_name and category_map[annotation['category_id']] == target_category_name:
            target_image_ids.add(annotation['image_id'])
    if target_category_name and (not target_image_ids):
        return feature_dict, box_dict, loaded_image_keys
    for image_id, file_name in image_map.items():
        if target_category_name and image_id not in target_image_ids:
            continue
        image_key = (image_key_prefix, os.path.abspath(coco_json), image_id)
        if processed_images and image_key in processed_images:
            loaded_image_keys.add(image_key)
            continue
        image_path = str(os.path.join(coco_folder, file_name))
        whole_image = cv2.imread(image_path)
        if whole_image is None:
            logger.error(f'Could not read image {image_path}')
            raise ValueError(f'Could not read image {image_path}')
        _, original_width = whole_image.shape[:2]
        image_height, image_width = whole_image.shape[:2]
        loaded_image_keys.add(image_key)
        for annotation in annotations_by_image.get(image_id, []):
            category_id = annotation['category_id']
            bbox = annotation['bbox']
            x, y, w, h = bbox
            image = whole_image[round(y):round(y + h), round(x):round(x + w), :3]
            x, y = (round(x), round(y))
            h, w, _ = image.shape
            category_name = category_map[category_id]
            is_hcenter = 'hcenter' in category_name or (hcenter_features and category_name in hcenter_features)
            is_vcenter = 'vcenter' in category_name or (vcenter_features and category_name in vcenter_features)
            if adjust and width > 0 and (height > 0):
                x, y, w, h, scale = adjust_coordinates(x, y, w, h, width, height, image_width, image_height, hcenter=is_hcenter, vcenter=is_vcenter)
                w = max(1, w)
                h = max(1, h)
                image = cv2.resize(image, (w, h))
            else:
                scale = 1
            logger.debug(f'loaded {category_name} resized width {width} / original_width:{original_width},scale_x:{width / original_width}')
            if category_name in feature_dict:
                existing_box = box_dict[category_name]
                if existing_box.x == x and existing_box.y == y and (existing_box.width == image.shape[1]) and (existing_box.height == image.shape[0]):
                    continue
                raise ValueError(f'Multiple boxes found for category {category_name}')
            feature_dict[category_name] = Feature(image, x, y, scale)
            box_dict[category_name] = box_factory(x, y, image.shape[1], image.shape[0], name=category_name)
    return feature_dict, box_dict, loaded_image_keys

def resize_image(image, frame_height: int, target_height: int) -> tuple:
    scale_factor = 1.0
    if target_height > 0 and frame_height >= 1.5 * target_height:
        image_height, image_width = image.shape[:2]
        scale_factor = target_height / frame_height
        new_width = int(round(image_width * scale_factor))
        new_height = int(round(image_height * scale_factor))
        image = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)
    return (image, scale_factor)

def load_json(coco_json):
    with open(coco_json, 'r', encoding='utf-8') as file:
        data = json.load(file)
        for images in data['images']:
            images['file_name'] = _normalize_asset_path(images['file_name'])
        return data

def _normalize_asset_path(path):
    if os.path.isabs(path):
        match = re.search('\\\\(images\\\\.*\\.(jpg|png)$)', path)
        if match:
            return match.group(1).replace('images\\', 'images/')
    return path

def adjust_coordinates(x, y, w, h, screen_width, screen_height, image_width, image_height, hcenter=False, vcenter=False):
    if screen_width != -1 and screen_height != -1 and (screen_width != image_width or screen_height != image_height):
        scale_x = screen_width / image_width
        scale_y = screen_height / image_height
        scale = min(scale_x, scale_y)
    else:
        scale = 1
    w, h = (round(w * scale), round(h * scale))
    x = scale_by_anchor(x, image_width, screen_width, scale, center=hcenter)
    y = scale_by_anchor(y, image_height, screen_height, scale, center=vcenter)
    return (x, y, w, h, scale)

def scale_by_anchor(val, image_dim, screen_dim, scale, center=False):
    if center:
        return round(screen_dim * 0.5 + (val - image_dim * 0.5) * scale)
    if val > image_dim / 2:
        return screen_dim - round((image_dim - val) * scale)
    return round(val * scale)

def filter_and_sort_matches(result, threshold, w, h):
    threshold_mask = result >= threshold
    loc = np.where(threshold_mask)
    matches = list(zip(*loc[::-1]))
    confidences = result[threshold_mask]
    matches_with_confidence = sorted(zip(matches, confidences), key=lambda x: x[1], reverse=True)
    selected_matches = []

    def is_overlapping(match, selected):
        x1, y1 = match
        for (x2, y2), _ in selected:
            if x1 < x2 + w and x1 + w > x2 and (y1 < y2 + h) and (y1 + h > y2):
                return True
        return False
    for match, confidence in matches_with_confidence:
        if not is_overlapping(match, selected_matches):
            selected_matches.append((match, confidence))
    return selected_matches
