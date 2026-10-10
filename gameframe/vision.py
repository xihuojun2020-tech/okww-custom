"""Game-independent CPU visual tools. Cropping here does not avoid GPU readback."""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class Match:
    x: int
    y: int
    width: int
    height: int
    confidence: float


def load_image(path: Path | str) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f'Invalid image: {path}')
    return image


def match_template(image: np.ndarray, template: np.ndarray, threshold: float,
                   region=None) -> Match | None:
    x, y = (region[0], region[1]) if region else (0, 0)
    haystack = image[y:y + region[3], x:x + region[2]] if region else image
    height, width = template.shape[:2]
    if height > haystack.shape[0] or width > haystack.shape[1]:
        return None
    scores = cv2.matchTemplate(haystack[:, :, :3], template[:, :, :3], cv2.TM_SQDIFF_NORMED)
    minimum, _, position, _ = cv2.minMaxLoc(scores)
    confidence = 1.0 - minimum
    if confidence < threshold:
        return None
    return Match(x + position[0], y + position[1], width, height, confidence)


def color_fraction(image: np.ndarray, lower, upper) -> float:
    mask = cv2.inRange(image[:, :, :3], np.asarray(lower, dtype=np.uint8),
                       np.asarray(upper, dtype=np.uint8))
    return cv2.countNonZero(mask) / mask.size
