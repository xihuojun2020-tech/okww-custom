"""Recognition and account/season progress for the supplied Tiangong UI."""
import json
import re
from functools import lru_cache
from pathlib import Path
from uuid import UUID

import cv2
import numpy as np

from src.evidence.model import now_iso
from src.runtime.diagnostic_export import atomic_json
from src.runtime.diagnostic_storage import storage_path
from src.task.character_trial import compact

STAGES = ('Ⅰ', 'Ⅱ', 'Ⅲ', 'Ⅳ', 'Ⅴ', 'Ⅵ')
TARGET = 80000


def stage_state(boxes):
    text = ''.join(compact(b.name) for b in boxes)
    if '解锁该关卡' in text:
        return {'status': 'locked', 'score': None}
    match = re.search(r'最高款项[:：]?([0-9]+(?:[,，][0-9]{3})*)', text)
    if match is None:
        return None
    score = int(re.sub('[,，]', '', match[1]))
    return {'status': 'completed' if score >= TARGET else 'pending', 'score': score}


def hardest(boxes):
    return bool(re.fullmatch(r'推荐等级[:：]?90', ''.join(compact(b.name) for b in boxes)))


@lru_cache(maxsize=4)
def number_template(number):
    path = Path(__file__).resolve().parents[2] / 'assets/images/activities/tiangong_treasure' / f'{number}.png'
    return cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)


def trial_numbers(frame):
    # Three badge rectangles measured on the user's full formation screenshot.
    h, w = frame.shape[:2]
    numbers = []
    for index in range(3):
        x = .1325 + index * .0837
        crop = frame[round(.140*h):round(.179*h), round(x*w):round((x+.022)*w)]
        image = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (48, 48))
        image = (image > 200).astype(np.uint8) * 255
        # Keep the glyph's surrounding whitespace and only allow a three-pixel
        # offset: a portrait's white vertical border must not match the digit 1.
        scores = [(float(cv2.matchTemplate(image[3:45, 5:43], number_template(n),
                                          cv2.TM_CCOEFF_NORMED).max()), n) for n in (1, 2, 3)]
        scores.sort(reverse=True)
        numbers.append(scores[0][1] if scores[0][0] >= .82 and scores[0][0]-scores[1][0] >= .04 else 0)
    return tuple(numbers)


def zero_score(frame, index):
    # The real OCR omits an isolated gray 0. Require exactly one visible glyph
    # matching the supplied zero, so missing text or a multi-digit score is not 0.
    image = cv2.resize(frame, (2048, 1152))
    y = round((.188 + index*.108)*1152)
    gray = cv2.cvtColor(image[y:y+45, 328:475], cv2.COLOR_BGR2GRAY)
    mask = (gray < 100 if np.median(gray) > 128 else gray > 100).astype(np.uint8)*255
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    glyphs = [s for s in stats[1:] if s[2] >= 5 and s[3] >= 12]
    if len(glyphs) != 1:
        return False
    x, y, w, h, _ = glyphs[0]
    glyph = cv2.resize(mask[y:y+h, x:x+w], (32, 32))
    return float(cv2.matchTemplate(glyph, number_template(0), cv2.TM_CCOEFF_NORMED).max()) >= .9


class Progress:
    def __init__(self, profile_id, period, root=None):
        if profile_id is None:
            self.path = None
            self.data = {'profile_id': None, 'periods': {}}
            self.stages = self.data['periods'].setdefault(period, {})
            return
        identity = str(UUID(profile_id))
        root = storage_path('logs', Path('logs')) / 'tiangong_progress' if root is None else Path(root)
        self.path = root / f'{identity}.json'
        self.data = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'profile_id': identity, 'periods': {}}
        self.stages = self.data['periods'].setdefault(period, {})

    def update(self, index, state):
        key = str(index+1)
        self.stages[key] = {**self.stages.get(key, {}), **state, 'checked_at': now_iso()}
        if self.path is not None:
            atomic_json(self.path, self.data)
