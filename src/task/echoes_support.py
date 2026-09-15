"""Event support-echo recognition and deterministic selection, no game input."""
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2] / 'assets/images/activities/echoes_remain/support'
KINDS = ('攻击型', '控制型', '生存型', '控制型', '支援型', '支援型', '生存型', '攻击型', '攻击型')
PREFERENCES = {'输出': (7, 8, 0), '治疗': (6, 2), '辅助': (1, 3, 4, 5)}
SLOTS = ((.1915, .755), (.484, .755), (.776, .755))


def normalized(frame):
    h, w = frame.shape[:2]
    if abs(w/h - 16/9) > .02:
        raise ValueError('若梦仍有回声需要16:9画面')
    return cv2.resize(frame, (2048, 1152))


@lru_cache(maxsize=10)
def reference(index):
    return cv2.imdecode(np.frombuffer((ROOT / f'{index}.png').read_bytes(), np.uint8), 1)


def card(frame, index):
    image = normalized(frame)
    x, y = 152 + 168*(index % 4), 138 + 168*(index // 4)
    return image[y:y+148, x:x+148]


def icon_score(image, index):
    # Exclude selection border and corner badges; compare the same inner artwork.
    a = cv2.resize(image, (80, 80))[10:70, 10:70]
    b = cv2.resize(reference(index), (80, 80))[10:70, 10:70]
    return float(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)[0, 0])


def unlocked(frame, index):
    image = card(frame, index)
    lock = reference('lock')
    score = cv2.matchTemplate(image[40:108, 40:108], lock, cv2.TM_CCOEFF_NORMED).max()
    return bool(score < .75 and icon_score(image, index) >= .70)


def choose_support(frame, role):
    if role not in PREFERENCES:
        raise RuntimeError('角色活动定位未知，不能选择声骸')
    return next((i for i in PREFERENCES[role] if unlocked(frame, i)), None)


def support_point(index):
    return ((226 + 168*(index % 4))/2048, (212 + 168*(index // 4))/1152)


def selected_support(frame, index):
    from src.task.AutoAbyssTask import selection_marker_present
    image = normalized(frame)
    x, y = 144 + 168*(index % 4), 128 + 168*(index // 4)
    return selection_marker_present(image[y:y+168, x:x+168])


def equipped(frame, slot, index):
    image = normalized(frame)
    x = (351, 950, 1548)[slot]
    icon = image[830:912, x:x+82]
    return icon_score(icon, index) >= .60


def enabled_start(frame):
    image = normalized(frame)[1040:1075, 1660:1850]
    # Both disabled and enabled contain text. Require the bright button fill.
    return float(np.mean(np.min(image, axis=2) > 200)) > .45
