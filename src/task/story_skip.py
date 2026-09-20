"""Localized template matching for the hexagonal story-summary skip flow."""
from functools import lru_cache
from pathlib import Path

import cv2
from ok import Box


ASSETS = Path(__file__).resolve().parents[2] / 'assets/images/story_skip'


@lru_cache(maxsize=3)
def _template(name):
    image = cv2.imread(str(ASSETS / f'{name}.png'), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise RuntimeError(f'Missing story skip template: {name}')
    return image


def _image(frame):
    height, width = frame.shape[:2]
    return cv2.cvtColor(cv2.resize(frame, (round(width * 720 / height), 720),
                                  interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)


def _match(image, name, region, scales=(1.0,), threshold=.85):
    height, width = image.shape
    x1, y1, x2, y2 = (round(region[0] * width), round(region[1] * height),
                      round(region[2] * width), round(region[3] * height))
    crop = image[y1:y2, x1:x2]
    template = _template(name)
    best = None
    for scale in scales:
        patch = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        h, w = patch.shape
        if h > crop.shape[0] or w > crop.shape[1]:
            continue
        _, score, _, point = cv2.minMaxLoc(cv2.matchTemplate(crop, patch, cv2.TM_CCOEFF_NORMED))
        if score >= threshold and (best is None or score > best[0]):
            best = (score, (x1 + point[0], y1 + point[1], w, h))
    return best[1] if best else None


def _box(rect, frame, name):
    if rect is None:
        return None
    scale = frame.shape[0] / 720
    return Box(*(round(value * scale) for value in rect), name=name)


def find_hex_skip(frame):
    image = _image(frame)
    # The source is a crop, so allow a bounded size range in the upper HUD corners.
    # Do not treat a similar emblem in dialogue text or the central scene as a button.
    for region in ((0, 0, .25, .22), (.75, 0, 1, .22)):
        rect = _match(image, 'hex_icon', region,
                      scales=(.35, .4, .45, .5, .55, .6, .65, .7, .8, .9, 1.0), threshold=.85)
        if rect:
            return _box(rect, frame, 'skip_dialog_hex')
    return None


def find_summary_skip(frame):
    image = _image(frame)
    if not _match(image, 'summary_title', (.38, .24, .62, .36)):
        return None
    # The left "continue watching" button must never become a skip candidate.
    rect = _match(image, 'skip_story', (.57, .64, .80, .77), threshold=.88)
    return _box(rect, frame, 'skip_story_summary')
