"""Read-only observations shared by daily execution and result verification."""
import re

import cv2
import numpy as np

CHESTS = ((20, .392), (40, .526), (60, .660), (80, .794), (100, .927))


def activity_digits_image(image):
    """Isolate bright score digits from the textured guidebook background."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)[1], cv2.COLOR_GRAY2BGR)


def resource_values(boxes, width):
    current, reserve = set(), set()
    for box in boxes:
        text = re.sub(r'\s+', '', str(box.name)).replace('／', '/')
        x = (box.x + box.width / 2) / width
        fraction = re.fullmatch(r'(\d{1,3})/240', text)
        if .68 <= x <= .90 and fraction and int(fraction[1]) <= 240:
            current.add(int(fraction[1]))
        elif .50 <= x < .68 and re.fullmatch(r'\d{1,4}', text):
            reserve.add(int(text))
    if len(current) != 1 or len(reserve) != 1:
        return -1, -1, -1
    a, b = current.pop(), reserve.pop()
    return a, b, a + b


def claimable_tiers(frame):
    """Red notification diamonds above each fixed daily reward chest."""
    h, w = frame.shape[:2]
    result = []
    for tier, x in CHESTS:
        crop = frame[round(.835*h):round(.867*h), round((x+.010)*w):round((x+.029)*w)]
        if not crop.size:
            continue
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        red = ((hsv[:, :, 0] < 12) | (hsv[:, :, 0] > 168)) & (hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 130)
        if np.mean(red) >= .04:
            result.append(tier)
    return result


def objective_progress(boxes, pattern):
    """Pair one objective title with its row's progress, never a neighbouring row."""
    titles = [b for b in boxes if re.search(pattern, re.sub(r'\s+', '', str(b.name)), re.I)]
    values = set()
    for title in titles:
        for box in boxes:
            text = re.sub(r'\s+', '', str(box.name))
            match = re.fullmatch(r'(\d+)\s*/\s*(\d+)', text)
            if (match and title.y <= box.y <= title.y + max(title.height * 2.8, 1)
                    and abs(box.x - title.x) < max(title.width, title.height * 4)):
                a, b = map(int, match.groups())
                if b > 0 and 0 <= a <= b:
                    values.add((a, b))
    return next(iter(values)) if len(values) == 1 else None
