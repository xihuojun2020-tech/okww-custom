"""Locate right-aligned energy digits without treating the lightning as a digit."""
import cv2
import re


def energy_digits(crop):
    if crop is None or not crop.size:
        return None
    mask = cv2.inRange(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV),
                       (8, 65, 100), (45, 255, 255))
    h, w = mask.shape
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    glyphs = sorted((s for s in stats[1:]
                     if h * .20 <= s[1] <= h * .65
                     and h * .20 <= s[3] <= h * .60
                     and s[4] >= h * w * .002
                     and s[0] >= w * .30), key=lambda s: s[0])
    if not glyphs:
        return None
    last = glyphs[-1]
    selected = [last]
    if len(glyphs) >= 2:
        previous = glyphs[-2]
        # Only a narrow, aligned "1" can precede the final digit in 0..10.
        if (previous[2] < previous[3] * .52
                and abs(previous[1] - last[1]) <= h * .08
                and abs(previous[3] - last[3]) <= h * .10
                and 0 <= last[0] - previous[0] - previous[2] <= last[3] * .5):
            selected.insert(0, previous)
    x = selected[0][0]
    y = min(s[1] for s in selected)
    right = max(s[0] + s[2] for s in selected)
    bottom = max(s[1] + s[3] for s in selected)
    digits = mask[y:bottom, x:right]
    return cv2.copyMakeBorder(digits, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=0), len(selected)


def confirmed_energy(texts, count):
    """No suffix truncation, and conflicting numeric candidates stay unknown."""
    values = []
    for text in texts:
        digits = re.sub(r'\s+', '', str(text))
        if not re.fullmatch(r'\d+', digits):
            if re.search(r'\d', digits):
                return None
            continue
        if len(digits) != count or not 0 <= int(digits) <= 10 or digits != str(int(digits)):
            return None
        values.append(int(digits))
    return values[0] if values and len(set(values)) == 1 else None
