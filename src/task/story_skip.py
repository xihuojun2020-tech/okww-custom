"""Localized template matching for the hexagonal story-summary skip flow."""
from functools import lru_cache
from pathlib import Path
from dataclasses import dataclass

import cv2
from ok import Box


ASSETS = Path(__file__).resolve().parents[2] / 'assets/images/story_skip'


@lru_cache(maxsize=14)
def _template(name):
    image = cv2.imread(str(ASSETS / f'{name}.png'), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise RuntimeError(f'Missing story skip template: {name}')
    return image


@lru_cache(maxsize=192)
def _scaled_template(name, scale):
    return cv2.resize(_template(name), None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def _image(frame):
    height, width = frame.shape[:2]
    return cv2.cvtColor(cv2.resize(frame, (round(width * 720 / height), 720),
                                  interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)


def _match(image, name, region, scales=(1.0,), threshold=.85, inner_threshold=None):
    height, width = image.shape
    x1, y1, x2, y2 = (round(region[0] * width), round(region[1] * height),
                      round(region[2] * width), round(region[3] * height))
    crop = image[y1:y2, x1:x2]
    best = None
    for scale in scales:
        patch = _scaled_template(name, scale)
        h, w = patch.shape
        if h > crop.shape[0] or w > crop.shape[1]:
            continue
        _, score, _, point = cv2.minMaxLoc(cv2.matchTemplate(crop, patch, cv2.TM_CCOEFF_NORMED))
        if score >= threshold and inner_threshold is not None:
            # The shared hexagonal outline is not evidence of the skip symbol.
            mx, my = round(w * .27), round(h * .27)
            center = patch[my:h-my, mx:w-mx]
            observed = crop[point[1]+my:point[1]+h-my, point[0]+mx:point[0]+w-mx]
            inner_score = float(cv2.matchTemplate(observed, center, cv2.TM_CCOEFF_NORMED)[0, 0])
            if inner_score < inner_threshold:
                continue
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
    # Both observed skip positions are on the left. The right controls include an
    # eye, log and auto-play icon with the same border: never search them for skip.
    region = (0, 0, .15, .22)
    for name in ('hex_letterbox', 'hex_green'):
        rect = _match(image, name, region, scales=(.9, 1., 1.1),
                      threshold=.85, inner_threshold=.75)
        if rect:
            return _box(rect, frame, 'skip_dialog_hex')
    rect = _match(image, 'hex_icon', region,
                  scales=(.35, .4, .45, .5, .55, .6, .65, .7, .8, .9, 1.0),
                  threshold=.85, inner_threshold=.75)
    if rect:
        return _box(rect, frame, 'skip_dialog_hex')
    # Known transparent-background variants are fallback-only. Cache the scaled
    # patches so every trigger tick does not rebuild this reference bank.
    for index in range(1, 7):
        rect = _match(image, f'hex_background_{index}', region,
                      scales=(.35, .4, .45, .5, .55, .6, .65, .7, .8, .9, 1.0),
                      threshold=.85, inner_threshold=.75)
        if rect:
            return _box(rect, frame, 'skip_dialog_hex')
    return _box(rect, frame, 'skip_dialog_hex')


def find_summary_skip(frame):
    image = _image(frame)
    if not _match(image, 'summary_title', (.38, .24, .62, .36)):
        return None
    # The left "continue watching" button must never become a skip candidate.
    rect = _match(image, 'skip_story', (.57, .64, .80, .77), threshold=.88)
    return _box(rect, frame, 'skip_story_summary')


@dataclass
class WarningDialog:
    checkbox: Box
    confirm: Box
    checked: bool | None


def find_skip_warning(frame):
    image = _image(frame)
    if not _match(image, 'warning_text', (.27, .38, .73, .51), threshold=.88):
        return None
    label = _match(image, 'session_label', (.40, .51, .63, .59), threshold=.88)
    confirm = _match(image, 'warning_confirm', (.57, .59, .76, .69), threshold=.88)
    if not label or not confirm:
        return None
    # Position relative to the verified label, not an unconditional screen click.
    cx, cy = label[0] - 18, label[1] + 11
    center = image[cy-5:cy+6, cx-5:cx+6]
    circle = image[cy-9:cy+10, cx-9:cx+10]
    # A filled white center is unchecked; a dark tick inside a white circle is checked.
    # An ambiguous animation must not enable confirmation.
    checked = None
    if (center > 245).mean() > .95:
        checked = False
    elif (center < 170).mean() > .10 and (circle > 240).mean() > .40:
        checked = True
    return WarningDialog(_box((cx-10, cy-10, 20, 20), frame, 'skip_story_checkbox'),
                         _box(confirm, frame, 'skip_story_warning_confirm'), checked)
