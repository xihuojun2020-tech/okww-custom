"""Stable HUD checks for the manually driven resonance simulation activity."""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2] / 'assets/images/activities/resonance_simulation'


def resized(frame):
    return cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)


@lru_cache(maxsize=2)
def _key_reference(key):
    return cv2.imread(str(ROOT / f'key_{key}.png'), cv2.IMREAD_GRAYSCALE)


def _keycap(image, center_x, key):
    """Match the fixed E/Q key cap despite scene-dependent HUD brightness."""
    crop = image[668:690, center_x - 9:center_x + 9]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    pale = (hsv[:, :, 1] < 130) & (hsv[:, :, 2] > 125)
    if np.count_nonzero(pale) < crop.shape[0] * crop.shape[1] * .35:
        return False
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return cv2.matchTemplate(gray, _key_reference(key), cv2.TM_CCOEFF_NORMED)[0, 0] >= .5


def skill_bar_visible(frame):
    """E/Q key caps stay stable across mixed skills, charges and cooldowns."""
    image = resized(frame)
    return _keycap(image, 1145, 'e') and _keycap(image, 1210, 'q')


def liberation_ready(frame):
    """Detect a complete yellow ring around Q while ignoring its inner icon."""
    image = resized(frame)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(hsv, (17, 105, 150), (42, 255, 255))
    center_x, center_y = 1210, 646
    covered = 0
    for angle in np.linspace(0, 2 * np.pi, 72, endpoint=False):
        found = False
        for radius in range(29, 40):
            x = int(round(center_x + radius * np.cos(angle)))
            y = int(round(center_y + radius * np.sin(angle)))
            if yellow[y, x]:
                found = True
                break
        covered += found
    return covered >= 58
