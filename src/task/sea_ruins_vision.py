"""Screen geometry for sea ruins; coordinates normalized to 2048x1152."""
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np
from src.task.sea_ruins import compact

ROOT = Path(__file__).resolve().parents[2] / 'assets/images/sea_ruins'


def normalized(frame):
    h, w = frame.shape[:2]
    if abs(w / h - 16 / 9) > .02 or h < 720:
        raise ValueError('冥歌海墟需要至少1280×720的16:9画面')
    return cv2.resize(frame, (2048, 1152))


@lru_cache(maxsize=8)
def reference(name):
    return cv2.imdecode(np.frombuffer((ROOT / f'{name}.png').read_bytes(), np.uint8), 1)


def crop(frame, region):
    x1, y1, x2, y2 = region
    h, w = frame.shape[:2]
    return frame[round(y1*h):round(y2*h), round(x1*w):round(x2*w)]


def icon_similarity(a, b):
    if a.size == 0 or b.size == 0:
        return 0.
    a, b = [cv2.resize(im, (72, 72)) for im in (a, b)]
    return float(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)[0, 0])


def token_cards(frame):
    image = normalized(frame)
    gray = cv2.cvtColor(image[195:1000, 85:1300], cv2.COLOR_BGR2GRAY)
    contours, _ = cv2.findContours(cv2.Canny(gray, 35, 100), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    found = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if 140 <= w <= 181 and 176 <= h <= 220:
            rect = (x+85, y+195, w, h)
            if not any(abs(rect[0]-a[0]) < 15 and abs(rect[1]-a[1]) < 15 for a in found):
                found.append(rect)
    return sorted(found, key=lambda r: (round(r[1]/40), r[0]))


def token_locked(frame, rect):
    x, y, w, h = rect
    roi = normalized(frame)[y+round(h*.30):y+round(h*.65), x+round(w*.62):x+w]
    template = reference('lock')
    gray, needle = [cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) for im in (roi, template)]
    if gray.shape[0] < needle.shape[0] or gray.shape[1] < needle.shape[1]:
        return True
    return float(cv2.matchTemplate(gray, needle, cv2.TM_CCOEFF_NORMED).max()) >= .72


def token_art(frame, rect):
    x, y, w, h = rect
    return normalized(frame)[y+12:y+round(h*.65), x+12:x+round(w*.72)].copy()


def exit_marker(frame):
    image = normalized(frame)
    # HUD's identical quest icon at x≈35 must never be accepted as a target.
    roi = image[150:850, 400:1800]
    mask = cv2.GaussianBlur(cv2.inRange(roi, (200, 200, 200), (255, 255, 255)), (3, 3), 0)
    best = None
    for name in ('exit', 'exit_side', 'exit_close'):
        template = cv2.GaussianBlur(cv2.inRange(reference(name), (200, 200, 200), (255, 255, 255)), (3, 3), 0)
        for scale in (.8, 1., 1.2):
            needle = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
            _, score, _, pos = cv2.minMaxLoc(cv2.matchTemplate(mask, needle, cv2.TM_CCOEFF_NORMED))
            if score >= .62 and (best is None or score > best[2]):
                best = ((pos[0]+400+needle.shape[1]/2)/2048,
                        (pos[1]+150+needle.shape[0]/2)/1152, score)
    return best


def interaction_prompt(frame, boxes, text):
    label = next((b for b in boxes if compact(b.name) == text), None)
    if label is None:
        return False
    h, w = frame.shape[:2]
    cy = label.y + label.height/2
    for b in boxes:
        if (compact(b.name).upper() == 'F' and 0 < label.x-b.x < w*.12
                and abs(b.y+b.height/2-cy) < h*.018):
            return True
    x, y = round(label.x*2048/w), round(cy*1152/h)
    roi = normalized(frame)[max(0, y-30):y+30, max(0, x-160):max(0, x-25)]
    needle = reference('f')
    if roi.shape[0] < needle.shape[0] or roi.shape[1] < needle.shape[1]:
        return False
    return float(cv2.matchTemplate(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY),
        cv2.cvtColor(needle, cv2.COLOR_BGR2GRAY), cv2.TM_CCOEFF_NORMED).max()) >= .78


def preset_rows(boxes, frame):
    """Only fully visible cards; overlap during scrolling recovers clipped rows."""
    h, w = frame.shape[:2]
    rows = []
    for b in boxes:
        text = compact(b.name)
        if not text.isdigit() or not 1 <= int(text) <= 50 or not .035 < b.x/w < .065:
            continue
        top = (b.y+b.height)/h + .006
        if .18 < top < .85 and top+.157 < .86:
            rows.append((int(text), top))
    return sorted(set(rows))


def preset_card_tops(frame):
    image = cv2.resize(normalized(frame), (1280, 720))
    contours, _ = cv2.findContours(cv2.Canny(image[:620, :355], 35, 100),
                                  cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    tops = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if 280 < w < 310 and 120 < h < 150 and y > 120:
            top = y/720
            if not any(abs(top-other) < .01 for other in tops):
                tops.append(top)
    return sorted(tops)


def preset_portraits(frame, top):
    return [crop(frame, (x, top, x+.066, top+.12)) for x in (.047, .123, .198)]


def team_portraits(frame, half):
    y = (.345, .665)[half]
    return [crop(frame, (x, y, x+.046, y+.087)) for x in (.568, .625, .682)]
