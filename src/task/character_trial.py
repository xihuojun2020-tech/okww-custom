"""Pure recognition and overlap checks for the 16:9 character trial page."""
from dataclasses import dataclass
import unicodedata

import cv2
import numpy as np


def compact(text):
    return ''.join(unicodedata.normalize('NFKC', text).split())


def exact_button(boxes, text):
    matches = [b for b in boxes if compact(b.name) == text]
    return matches[0] if len(matches) == 1 else None


def reward_state(boxes):
    states = {'进行中': 'pending', '领取': 'claim', '已完成': 'complete'}
    found = {states[compact(b.name)] for b in boxes if compact(b.name) in states}
    return next(iter(found)) if len(found) == 1 else None


def start_prompt(boxes, height):
    label = exact_button(boxes, '开启挑战')
    key = exact_button(boxes, 'F')
    return bool(label and key and key.x < label.x and
                abs(key.y + key.height / 2 - label.y - label.height / 2) < height * .015)


@dataclass(eq=False)
class Portrait:
    x: int
    y: int
    width: int
    height: int
    image: np.ndarray

    @property
    def center(self):
        return self.x + self.width // 2, self.y + self.height // 2


def similarity(a, b):
    # Inner crops exclude notification/completion badges and selection borders.
    a, b = (cv2.resize(im, (160, 60)) for im in (a, b))
    # Selection slightly enlarges a portrait. Search a small translation/scale
    # margin rather than requiring identical pixels at a fitted grid origin.
    scores = []
    for source, target in ((a, b), (b, a)):
        template = source[15:39, 42:114]
        for scale in (.94, 1., 1.06):
            resized = cv2.resize(template, None, fx=scale, fy=scale)
            scores.append(float(cv2.minMaxLoc(cv2.matchTemplate(
                target[7:48, 25:133], resized, cv2.TM_CCOEFF_NORMED))[1]))
    return max(scores)


def unique_match(image, cards, threshold=.78):
    scores = sorted([(similarity(image, c.image), i) for i, c in enumerate(cards)], reverse=True)
    if not scores or scores[0][0] < threshold:
        return None
    if len(scores) > 1 and scores[0][0] - scores[1][0] < .12:
        raise RuntimeError('角色头像匹配有歧义')
    return scores[0][1]


def portrait_selected(frame, card):
    h, w = frame.shape[:2]
    im = cv2.resize(frame, (2048, 1152))
    x, width = round(card.x*2048/w), round(card.width*2048/w)
    mask = cv2.inRange(cv2.cvtColor(im[:, x:x+width], cv2.COLOR_BGR2HSV),
                       (0,0,70), (180,100,255))
    # Outside the artwork: both extended selection-border rows must be present.
    return bool(np.max(np.mean(mask[1006:1012] > 0, axis=1)) > .70 and
                np.max(np.mean(mask[1076:1081] > 0, axis=1)) > .70)


def merge_view(known, current):
    """Append a rightward viewport only when a unique contiguous overlap exists."""
    if not known:
        return list(current)
    possibilities = []
    for start in range(len(known)):
        overlap = min(len(current), len(known) - start)
        if overlap and all(unique_match(current[i].image, known) == start + i for i in range(overlap)):
            possibilities.append((start, overlap))
    if len(possibilities) != 1:
        raise RuntimeError('头像列表缺少唯一连续重叠，不能确认完整名单')
    start, overlap = possibilities[0]
    for card in current[overlap:]:
        if unique_match(card.image, known) is not None:
            raise RuntimeError('头像顺序矛盾')
    return known + current[overlap:] if start + overlap == len(known) else known


def detect_portraits(frame):
    """Fit the observed regular card geometry, validating visible vertical edges.

    Work at the reference size; do not recognize character artwork. The allowed
    pitch/width are UI geometry from supplied screenshots, not a character count.
    Unfamiliar layouts fail rather than clicking guessed slots.
    """
    h, w = frame.shape[:2]
    if abs(w / h - 16 / 9) > .02:
        raise RuntimeError('角色试用仅支持16:9画面')
    im = cv2.resize(frame, (2048, 1152))
    left, right, top, bottom = 575, 1371, 1013, 1074
    band = im[top+6:bottom-10, left:right].astype(np.float32)
    edges = np.mean(np.abs(band[:, 1:] - band[:, :-1]), axis=(0, 2))
    def strength(x):
        i = int(x-left)
        if i < 0 or i >= len(edges):
            return 0.
        return float(max(edges[max(0, i-8):min(len(edges), i+9)]))
    fits = []
    for pitch in range(173, 179):
        width = pitch - 16
        for offset in range(-pitch+1, 1):
            starts = [left+offset+i*pitch for i in range(7)]
            full = [x for x in starts if left <= x and x+width < right]
            scores = [min(strength(x), strength(x+width)) for x in full]
            if len(scores) >= 3 and min(scores) >= 10:
                fits.append((float(np.sum(np.minimum(scores, 40))/4), pitch, starts, width))
    if not fits:
        raise RuntimeError('无法定位角色头像条')
    score, pitch, starts, width = max(fits, key=lambda f: f[0])
    if score < 20:
        raise RuntimeError('角色头像边界不清晰')
    full = [x for x in starts if left <= x and x+width < right]
    if any(min(strength(x), strength(x+width)) < 10 for x in full):
        raise RuntimeError('角色头像边界不完整')
    cards = []
    for x in full:
        image = im[top:bottom, x:x+width].copy()
        cards.append(Portrait(round(x*w/2048), round(top*h/1152),
                              round(width*w/2048), round((bottom-top)*h/1152), image))
    # A partial portrait at either edge must not be silently counted as covered.
    partial_left = any(x < left < x+width-15 for x in starts)
    partial_right = any(x+15 < right < x+width for x in starts)
    return cards, partial_left, partial_right
