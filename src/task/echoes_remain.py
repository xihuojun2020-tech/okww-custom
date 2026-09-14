"""Small, read-only checks for the event's fixed first-row trial formation."""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from src.task.AutoAbyssTask import character_card_slots, selection_marker_present, character_list_at_edge

ASSETS = Path(__file__).resolve().parents[2] / 'assets/images/activities/echoes_remain'
INITIAL = (1, 2, 3, 0, 0, 0, 0)
FINAL = (0, 0, 0, 1, 2, 3, 0)


def crop(frame, region):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = region
    return frame[max(0, round(y1*h)):min(h, round(y2*h)), max(0, round(x1*w)):min(w, round(x2*w))]


def card_region(index, region):
    _, _, x, y, w, h, _ = character_card_slots()[index]
    a, b, c, d = region
    return x+a*w, y+b*h, x+c*w, y+d*h


def tile(frame, index, region, size):
    part = crop(frame, card_region(index, region))
    return cv2.resize(cv2.cvtColor(part, cv2.COLOR_BGR2GRAY), size, interpolation=cv2.INTER_AREA)


@lru_cache(maxsize=4)
def template(name):
    value = cv2.imdecode(np.frombuffer((ASSETS / (name+'.png')).read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
    if value is None or not value.size:
        raise ValueError('活动识别素材不可用：' + name)
    return value


NUMBER_REGION = (.79, -.065, 1.10, .15)
CLOCK_REGION = (.62, .46, 1.02, .83)


def read_number(frame, index):
    image = tile(frame, index, NUMBER_REGION, (48, 48))
    scores = [float(cv2.matchTemplate(image, template(str(n)), cv2.TM_CCOEFF_NORMED).max()) for n in (1, 2, 3)]
    order = sorted(range(3), key=lambda n: scores[n], reverse=True)
    return order[0]+1 if scores[order[0]] >= .82 and scores[order[0]]-scores[order[1]] >= .04 else 0


def trial_clock(frame, index):
    image = tile(frame, index, CLOCK_REGION, (64, 80))
    return float(cv2.matchTemplate(image, template('clock'), cv2.TM_CCOEFF_NORMED).max()) >= .82


def inspect_roster(frame):
    h, w = frame.shape[:2]
    if abs(w/h-16/9) > .02:
        raise ValueError('本阶段需要16:9游戏画面')
    numbers = tuple(read_number(frame, index) for index in range(7))
    gold = tuple(selection_marker_present(crop(frame, card_region(index, (0, 0, 1, .70)))) for index in range(7))
    clocks = tuple(trial_clock(frame, index) for index in (3, 4, 5))
    # Also reject a visible selected lower-row card; never scan the full warehouse.
    lower_selected = any(selection_marker_present(crop(frame, card_region(index, (0, 0, 1, .70))))
                         for index in range(7, 21))
    valid = character_list_at_edge(frame) and all(clocks) and not lower_selected
    valid = valid and all(bool(number) == selected for number, selected in zip(numbers, gold))
    return {'numbers': numbers, 'gold': gold, 'clocks': clocks, 'valid': bool(valid)}


def correction(numbers):
    """Only one missing final selection can be appended without changing order."""
    return 5 if tuple(numbers) == (0, 0, 0, 1, 2, 0, 0) else None
