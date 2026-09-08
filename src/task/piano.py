"""Pure image detection and per-key debouncing for the piano teaching UI."""
from dataclasses import dataclass

import cv2
import numpy as np


KEY_ROWS = ("QWERTYU", "ASDFGHJ", "ZXCVBNM")
KEY_ORDER = "".join(KEY_ROWS)

# Measured from the user's 2560x1440 reference capture.  The game UI scales
# these positions uniformly at supported 16:9 resolutions.
X_CENTERS = (747 / 2560, 925 / 2560, 1102 / 2560, 1279 / 2560,
             1456 / 2560, 1633 / 2560, 1810 / 2560)
Y_CENTERS = (988 / 1440, 1142 / 1440, 1296 / 1440)


@dataclass(frozen=True)
class KeyReading:
    key: str
    row: int
    column: int
    score: float
    dot_luma: float


@dataclass(frozen=True)
class DetectionResult:
    status: str
    on_keys: tuple[str, ...]
    uncertain_keys: tuple[str, ...]
    readings: tuple[KeyReading, ...]
    reason: str = ""


@dataclass(frozen=True)
class ChordEvent:
    keys: tuple[str, ...]


def key_for(row, column):
    if not (0 <= row < 3 and 0 <= column < 7):
        raise ValueError("invalid piano key position")
    return KEY_ROWS[row][column]


class PianoDetector:
    """Detect golden highlight rings around the fixed 3x7 note grid."""

    def __init__(self, on_threshold=0.075, off_threshold=0.060):
        if not 0 <= off_threshold < on_threshold:
            raise ValueError("piano thresholds must satisfy 0 <= off < on")
        self.on_threshold = float(on_threshold)
        self.off_threshold = float(off_threshold)

    @staticmethod
    def _circle_masks(radius_scale):
        outer = max(4, round(70 * radius_scale))
        axis = np.arange(-outer, outer + 1)
        yy, xx = np.meshgrid(axis, axis, indexing="ij")
        distance = np.sqrt(xx * xx + yy * yy)
        return outer, distance <= 9 * radius_scale, (
            (distance >= 28 * radius_scale) & (distance <= 50 * radius_scale)
        ), ((distance >= 56 * radius_scale) & (distance <= 70 * radius_scale))

    def analyze(self, frame_bgr):
        if not isinstance(frame_bgr, np.ndarray) or frame_bgr.dtype != np.uint8 \
                or frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3:
            return DetectionResult("invalid_roi", (), (), (), "frame must be uint8 BGR")
        height, width = frame_bgr.shape[:2]
        if height <= 0 or abs((width / height) / (16 / 9) - 1) > 0.03:
            return DetectionResult("invalid_roi", (), (), (), "piano requires a 16:9 frame")

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        scale = height / 1440
        outer, dot_mask, ring_mask, background_mask = self._circle_masks(scale)
        readings = []
        valid_dots = 0
        for row, y_ratio in enumerate(Y_CENTERS):
            for column, x_ratio in enumerate(X_CENTERS):
                x, y = round(x_ratio * width), round(y_ratio * height)
                crop = gray[y - outer:y + outer + 1, x - outer:x + outer + 1]
                if crop.shape != dot_mask.shape:
                    return DetectionResult("invalid_roi", (), (), tuple(readings), "piano grid is outside frame")
                dot_luma = float(crop[dot_mask].mean())
                valid_dots += dot_luma >= 0.55
                score = max(0.0, float(crop[ring_mask].mean() - crop[background_mask].mean()))
                readings.append(KeyReading(key_for(row, column), row, column, score, dot_luma))

        if valid_dots < 18:
            return DetectionResult("invalid_roi", (), (), tuple(readings),
                                   f"piano dot grid not found ({valid_dots}/21)")
        on = tuple(item.key for item in readings if item.score >= self.on_threshold)
        uncertain = tuple(item.key for item in readings
                          if self.off_threshold < item.score < self.on_threshold)
        if uncertain:
            return DetectionResult("ambiguous", on, uncertain, tuple(readings), "highlight transition")
        return DetectionResult("candidate" if on else "no_highlight", on, (), tuple(readings))


class PianoStateMachine:
    """Confirm and de-duplicate each note independently, including chords."""

    def __init__(self, confirm_frames=2, release_frames=2, max_sample_gap=0.20):
        if confirm_frames < 2 or release_frames < 2:
            raise ValueError("piano confirmation requires at least two frames")
        self.confirm_frames = confirm_frames
        self.release_frames = release_frames
        self.max_sample_gap = max_sample_gap
        self.on_counts = dict.fromkeys(KEY_ORDER, 0)
        self.off_counts = dict.fromkeys(KEY_ORDER, 0)
        self.latched = set()
        self.last_sample_at = None

    def step(self, result, now=None):
        if now is not None:
            if self.last_sample_at is not None and (
                    now <= self.last_sample_at or now - self.last_sample_at > self.max_sample_gap):
                self.on_counts = dict.fromkeys(KEY_ORDER, 0)
                self.off_counts = dict.fromkeys(KEY_ORDER, 0)
            self.last_sample_at = now
        if result.status == "invalid_roi":
            self.on_counts = dict.fromkeys(KEY_ORDER, 0)
            self.off_counts = dict.fromkeys(KEY_ORDER, 0)
            return None

        on = set(result.on_keys)
        uncertain = set(result.uncertain_keys)
        for key in KEY_ORDER:
            if key in uncertain:
                self.on_counts[key] = self.off_counts[key] = 0
            elif key in on:
                self.on_counts[key] += 1
                self.off_counts[key] = 0
            else:
                self.off_counts[key] += 1
                self.on_counts[key] = 0
                if self.off_counts[key] >= self.release_frames:
                    self.latched.discard(key)

        if uncertain:
            return None
        pending = [key for key in KEY_ORDER if key in on and key not in self.latched]
        if not pending or any(self.on_counts[key] < self.confirm_frames for key in pending):
            return None
        self.latched.update(pending)
        return ChordEvent(tuple(pending))
