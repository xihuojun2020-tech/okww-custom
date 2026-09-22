"""Stable HUD checks for the manually driven resonance simulation activity."""
import cv2
import numpy as np


def resized(frame):
    return cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)


def _keycap(image, center_x):
    """Match the pale E/Q key cap, not the character-specific skill artwork."""
    crop = image[668:690, center_x - 9:center_x + 9]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    pale = (hsv[:, :, 1] < 130) & (hsv[:, :, 2] > 125)
    return np.count_nonzero(pale) >= crop.shape[0] * crop.shape[1] * .35


def skill_bar_visible(frame):
    """E/Q key caps stay stable across mixed skills, charges and cooldowns."""
    image = resized(frame)
    hp_hsv = cv2.cvtColor(image[681:699, 525:742], cv2.COLOR_BGR2HSV)
    hp = cv2.inRange(hp_hsv, (0, 0, 145), (179, 100, 255))
    contours, _ = cv2.findContours(hp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    parts = [cv2.boundingRect(contour) for contour in contours]
    hp_bar = (any(x < 20 and width >= 65 and 7 <= height <= 14
                  for x, y, width, height in parts)
              and any(x >= 120 and width >= 45 and 7 <= height <= 14
                      for x, y, width, height in parts))
    return (_keycap(image, 1145) and _keycap(image, 1210) and hp_bar)


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
