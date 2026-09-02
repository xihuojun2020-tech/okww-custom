# -*- coding: utf-8 -*-
"""Scan Adversity Tower floors without entering the team or combat screens."""
from pathlib import Path

import cv2

from qfluentwidgets import FluentIcon as Icon

from src.task.BaseWWTask import BaseWWTask
from src.task.WWOneTimeTask import WWOneTimeTask


TOWER_NAMES = ("残响之塔", "深境之塔", "回音之塔")
FLOOR_ROWS = (
    (0.145, 0.275),
    (0.285, 0.415),
    (0.425, 0.555),
    (0.565, 0.695),
)
COMPLETED = "已完成"
AVAILABLE = "未完成（可挑战）"
LOCKED = "未解锁"
PERIOD_ICON_EDGE_THRESHOLD = 0.24


def _center_y(box):
    return box.y + box.height / 2


def match_travel_button(title_box, travel_boxes, vertical_tolerance=None):
    """Return the 前往 button aligned with the target card, never another card."""
    title_y = _center_y(title_box)
    tolerance = vertical_tolerance if vertical_tolerance is not None else max(title_box.height * 4, 120)
    candidates = [
        box for box in travel_boxes
        if box.x > title_box.x + title_box.width
        and abs(_center_y(box) - title_y) <= tolerance
    ]
    return min(candidates, key=lambda box: abs(_center_y(box) - title_y), default=None)


def aggregate_floor_states(completed, locked):
    """Convert per-floor template hits into user-facing, mutually exclusive states."""
    return tuple(
        COMPLETED if completed_hit else LOCKED if locked_hit else AVAILABLE
        for completed_hit, locked_hit in zip(completed, locked)
    )


def tower_click_point(title_box, screen_width):
    """Click the lower centre of a tower's diamond area using its OCR title as anchor."""
    return (title_box.x + title_box.width / 2) / screen_width, 0.47


def best_template_match(matches):
    """Choose the strongest non-empty match while retaining a full navigation scan."""
    return max((match for match in matches if match is not None), key=lambda match: match[-1], default=None)


class AutoAbyssTask(WWOneTimeTask, BaseWWTask):
    """Enter the Adversity Tower and report its four floor states for each tower."""

    navigation_section = "tests"
    _ASSET_DIR = Path("assets/images")
    _TEMPLATES = {
        "period_selected": _ASSET_DIR / "abyss_period_challenge_selected.png",
        "period_unselected": _ASSET_DIR / "abyss_period_challenge_unselected.png",
        "completed": _ASSET_DIR / "abyss_completed_icon.png",
        "locked": _ASSET_DIR / "abyss_locked_icon.png",
    }
    _template_cache = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🧪 自动深渊：深塔关卡扫描"
        self.description = (
            "从大世界进入周期挑战和逆境深塔，逐座扫描四个关卡的完成状态。"
            "仅扫描：不会进入编队、不会选择角色、不会点击挑战开始或启动自动战斗。"
        )
        self.group_name = "🧪 测试功能"
        self.group_icon = Icon.DEVELOPER_TOOLS
        self.default_config = {}
        self.config_description = {}

    def run(self):
        WWOneTimeTask.run(self)
        self._assert_scan_only()
        self.info_set("状态", "打开 F2 周期挑战...")
        self.openF2Book()
        self._open_period_challenge()
        self._select_adversity_tower()
        self._open_adversity_tower()

        results = {}
        for tower_name in TOWER_NAMES:
            self.info_set("状态", f"扫描 {tower_name}...")
            self._open_tower(tower_name)
            results[tower_name] = self._scan_tower_floors()
            self._return_to_towers()

        summary = "；".join(f"{tower}: {', '.join(states)}" for tower, states in results.items())
        self.info_set("扫描结果", summary)
        self.info_set("状态", "扫描完成 ✓")
        self.log_info(f"深塔关卡扫描完成：{summary}", notify=True)

    def _assert_scan_only(self):
        self.log_info("扫描模式：不会进入编队或点击挑战开始")

    def _open_period_challenge(self):
        self.log_info("识别并打开周期挑战入口")
        if not self.wait_until(self._click_period_challenge_icon, time_out=8, raise_if_not_found=False):
            self.screenshot("abyss_period_challenge_not_found")
            raise Exception("未识别到周期挑战入口")
        self.wait_ocr(match="周期挑战", time_out=8, raise_if_not_found=True)

    def _open_adversity_tower(self):
        self.log_info("识别中间深境区并点击同卡片的前往")
        title = self._wait_content_deep_area()
        travel = self.wait_ocr(match="前往", time_out=5, raise_if_not_found=True)
        button = match_travel_button(title, travel)
        if button is None:
            self.screenshot("abyss_travel_button_not_found")
            raise Exception("未找到深境区同卡片的前往按钮")
        self.click_box(button, after_sleep=2)
        self._wait_for_tower_screen()

    def _select_adversity_tower(self):
        """Explicitly choose 逆境深塔 before using its 深境区 card."""
        self.log_info("选择逆境深塔")
        cards = self.wait_ocr(
            x=0.06, y=0.10, to_x=0.36, to_y=0.50,
            match="逆境深塔", time_out=8, raise_if_not_found=True,
        )
        card = next((box for box in cards if "逆境深塔" in str(box.name)), None)
        if card is None:
            raise Exception("未识别到逆境深塔卡片")
        self.click_box(card, after_sleep=1)
        self._wait_content_deep_area()

    def _wait_content_deep_area(self):
        """Only accept 深境区 from the middle content card, never the left activity card."""
        boxes = self.wait_ocr(
            x=0.35, y=0.15, to_x=0.65, to_y=0.45,
            match="深境区", time_out=8, raise_if_not_found=True,
        )
        title = next((box for box in boxes if "深境区" in str(box.name)), None)
        if title is None:
            raise Exception("未识别到中间深境区卡片")
        return title

    def _wait_for_tower_screen(self):
        for tower_name in TOWER_NAMES:
            self.wait_ocr(match=tower_name, time_out=8, raise_if_not_found=True)

    def _open_tower(self, tower_name):
        title_boxes = self.wait_ocr(match=tower_name, time_out=5, raise_if_not_found=True)
        title = next((box for box in title_boxes if tower_name in str(box.name)), None)
        if title is None:
            raise Exception(f"未识别到{tower_name}")
        x, y = tower_click_point(title, self.width)
        self.log_info(f"打开 {tower_name}")
        self.click_relative(x, y, after_sleep=2, name=tower_name)
        self.wait_ocr(match="挑战目标", time_out=8, raise_if_not_found=True)

    def _scan_tower_floors(self):
        frame = self.frame
        completed = [self._row_matches(frame, row, "completed", 0.70) for row in FLOOR_ROWS]
        locked = [not done and self._row_matches(frame, row, "locked", 0.68) for done, row in zip(completed, FLOOR_ROWS)]
        states = aggregate_floor_states(completed, locked)
        self.log_info(f"当前塔扫描结果：{', '.join(states)}")
        return states

    def _return_to_towers(self):
        self.send_key("esc", after_sleep=2)
        self._wait_for_tower_screen()

    def _click_period_challenge_icon(self):
        # The left navigation order changes with game content.  Scan its full height, but compare
        # only the background-free icon edges so a highlighted different category cannot win by color.
        match = self._find_period_challenge_icon(self.frame)
        if match is None:
            return False
        x, y, width, height, _score = match
        self.click_relative((x + width / 2) / self.width, (y + height / 2) / self.height, after_sleep=1)
        return True

    def _find_period_challenge_icon(self, frame):
        if frame is None:
            return None
        height, width = frame.shape[:2]
        left, top, right, bottom = 0, int(0.08 * height), int(0.12 * width), int(0.90 * height)
        navigation = frame[top:bottom, left:right]
        edges = cv2.Canny(cv2.cvtColor(navigation, cv2.COLOR_BGR2GRAY), 70, 160)
        matches = []
        for template_name in ("period_selected", "period_unselected"):
            template = self._template(template_name)
            scale = height / 1440
            if scale != 1:
                interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
                template = cv2.resize(template, None, fx=scale, fy=scale, interpolation=interpolation)
            template_edges = cv2.Canny(template, 70, 160)
            if edges.shape[0] < template_edges.shape[0] or edges.shape[1] < template_edges.shape[1]:
                continue
            _min_score, max_score, _min_loc, max_loc = cv2.minMaxLoc(
                cv2.matchTemplate(edges, template_edges, cv2.TM_CCOEFF_NORMED)
            )
            if max_score >= PERIOD_ICON_EDGE_THRESHOLD:
                matches.append((
                    left + max_loc[0], top + max_loc[1],
                    template_edges.shape[1], template_edges.shape[0], max_score,
                ))
        return best_template_match(matches)

    def _row_matches(self, frame, row, template_name, threshold):
        y1, y2 = row
        region = (0.340, y1, 0.390, min(y2, y1 + 0.08)) if template_name == "completed" else (0.015, y1, 0.075, y2)
        return self._find_template(frame, region, template_name, threshold) is not None

    @classmethod
    def _template(cls, name):
        if name not in cls._template_cache:
            image = cv2.imread(str(cls._TEMPLATES[name]), cv2.IMREAD_GRAYSCALE)
            if image is None:
                raise FileNotFoundError(f"深塔扫描模板不存在: {cls._TEMPLATES[name]}")
            cls._template_cache[name] = image
        return cls._template_cache[name]

    def _find_template(self, frame, region, template_name, threshold):
        if frame is None:
            return None
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = region
        left, top = int(x1 * width), int(y1 * height)
        right, bottom = int(x2 * width), int(y2 * height)
        crop = frame[top:bottom, left:right]
        template = self._template(template_name)
        scale = height / 1440
        if scale != 1:
            interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
            template = cv2.resize(template, None, fx=scale, fy=scale, interpolation=interpolation)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        if gray.shape[0] < template.shape[0] or gray.shape[1] < template.shape[1]:
            return None
        _min_score, max_score, _min_loc, max_loc = cv2.minMaxLoc(
            cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        )
        if max_score < threshold:
            return None
        return left + max_loc[0], top + max_loc[1], template.shape[1], template.shape[0], max_score
