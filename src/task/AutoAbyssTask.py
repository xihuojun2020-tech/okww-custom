# -*- coding: utf-8 -*-
"""Scan, form teams for, and automatically challenge Adversity Tower floors."""
from dataclasses import dataclass
from pathlib import Path
import re

import cv2
import numpy as np

from qfluentwidgets import FluentIcon as Icon

from src.char.CharFactory import char_dict, char_names
from src.task.abyss_team_planner import (
    ROVER_AERO,
    ROVER_CHARACTER_IDS,
    ROVER_HAVOC,
    ROVER_SPECTRO,
    ROVER_UNKNOWN,
    effective_character_id,
    plan_team,
)
from src.task.BaseCombatTask import BaseCombatTask, CharDeadException
from src.task.WWOneTimeTask import WWOneTimeTask
from src.task_status import publish_task_status


TOWER_NAMES = ("残响之塔", "深境之塔", "回音之塔")
SIDE_TOWERS_FIRST = "两侧塔优先"
CENTER_TOWER_FIRST = "中间塔优先"
TOWER_PRIORITY = "Tower Priority"
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
CHARACTER_GRID = (0.070, 0.120, 0.930, 0.840)
CHARACTER_CARD_X = 0.0785
CHARACTER_CARD_Y = (0.1285, 0.3750, 0.6220)
CHARACTER_CARD_WIDTH = 0.1050
CHARACTER_CARD_HEIGHT = 0.2275
CHARACTER_CARD_X_STEP = 0.1221
CHARACTER_COLUMNS = 7
CHARACTER_COMPLETE_ROWS = 2
CHARACTER_MATCH_MINIMUM = 6
CHARACTER_MATCH_MARGIN = 2
SINGLE_PAGE_SCROLL_THUMB_COVERAGE = 0.80


class AbyssTeamUnavailable(Exception):
    """The current account cannot form a team that covers this tower's remaining cost."""


@dataclass(frozen=True)
class CharacterScanRecord:
    character_id: str
    display_name: str
    energy: int | None
    level: int | None
    confidence: float
    screen_index: int
    slot_index: int
    rover_form: str | None = None
    rover_confidence: float = 0.0
    selection_number: int | None = None

    @property
    def available(self):
        return self.energy is not None and self.level is not None and self.energy > 0 and self.level > 60


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


def aggregate_floor_states(completed, locked, present=None):
    """Convert per-floor template hits into user-facing, mutually exclusive states."""
    states = tuple(
        COMPLETED if completed_hit else LOCKED if locked_hit else AVAILABLE
        for completed_hit, locked_hit in zip(completed, locked)
    )
    if present is None:
        return states
    present = tuple(bool(value) for value in present)
    if not any(present):
        return ()
    last = max(index for index, value in enumerate(present) if value)
    if not all(present[:last + 1]):
        raise ValueError("深塔关卡存在性识别不连续")
    return states[:last + 1]


def tower_click_point(title_box, screen_width):
    """Click the lower centre of a tower's diamond area using its OCR title as anchor."""
    return (title_box.x + title_box.width / 2) / screen_width, 0.47


def best_template_match(matches):
    """Choose the strongest non-empty match while retaining a full navigation scan."""
    return max((match for match in matches if match is not None), key=lambda match: match[-1], default=None)


def first_available_floor(states):
    """Return the first unlocked unfinished floor index, or None."""
    return next((index for index, state in enumerate(states) if state == AVAILABLE), None)


def tower_order(priority):
    """Return the configured tower order; side-first is the safe default."""
    if priority == CENTER_TOWER_FIRST:
        return (TOWER_NAMES[1], TOWER_NAMES[0], TOWER_NAMES[2])
    return (TOWER_NAMES[0], TOWER_NAMES[2], TOWER_NAMES[1])


def tower_required_energy(tower_name, states):
    """Return per-character energy needed to clear every remaining floor in a tower."""
    start = first_available_floor(states)
    if start is None:
        return 0
    return sum(
        5 if tower_name == TOWER_NAMES[1] else index + 1
        for index, state in enumerate(states)
        if index >= start and state != COMPLETED
    )


def _normalized_ocr_text(value):
    return re.sub(r"\s+", "", str(value or "")).strip()


def exact_ocr_box(boxes, expected):
    """Match complete button text; similar challenge buttons must never alias."""
    expected = _normalized_ocr_text(expected)
    return next(
        (box for box in boxes or () if _normalized_ocr_text(getattr(box, "name", box)) == expected),
        None,
    )


def abyss_result_state(boxes):
    """Classify only complete, internally consistent abyss result text."""
    success = exact_ocr_box(boxes, "挑战成功") is not None
    failed = exact_ocr_box(boxes, "挑战失败") is not None
    back = exact_ocr_box(boxes, "返回深塔") is not None
    if success and back and exact_ocr_box(boxes, "继续挑战") is not None:
        return "continue"
    if success and back and exact_ocr_box(boxes, "再次挑战") is not None:
        return "tower_complete"
    if failed and back and exact_ocr_box(boxes, "再次挑战") is not None:
        return "failed"
    return None


def character_card_slots():
    """Return the 7x3 fixed character grid; only the first two rows are fully visible."""
    return tuple(
        (
            row,
            column,
            CHARACTER_CARD_X + column * CHARACTER_CARD_X_STEP,
            CHARACTER_CARD_Y[row],
            CHARACTER_CARD_WIDTH,
            CHARACTER_CARD_HEIGHT,
            row < CHARACTER_COMPLETE_ROWS,
        )
        for row in range(len(CHARACTER_CARD_Y))
        for column in range(CHARACTER_COLUMNS)
    )


def character_safe_click(slot):
    """Return a card-body click point away from element, selection, energy and level labels."""
    _row, _column, x, y, width, height, _complete = slot
    return x + width * 0.50, y + height * 0.35


def validate_selection_state(records):
    """Return number-to-identity mapping or reject contradictory selection markers."""
    number_to_identity = {}
    identity_to_number = {}
    for record in records:
        number = getattr(record, "selection_number", None)
        if number is None:
            continue
        if number not in (1, 2, 3):
            raise ValueError(f"非法角色选择编号：{number}")
        identity = effective_character_id(record)
        existing_identity = number_to_identity.get(number)
        if existing_identity is not None and existing_identity != identity:
            raise ValueError(f"选择编号 {number} 同时对应 {existing_identity} 和 {identity}")
        existing_number = identity_to_number.get(identity)
        if existing_number is not None and existing_number != number:
            raise ValueError(f"角色 {identity} 同时对应选择编号 {existing_number} 和 {number}")
        number_to_identity[number] = identity
        identity_to_number[identity] = number
    return number_to_identity


def character_column_at(x_norm):
    """Map an OCR result centre to its character-card column."""
    first_center = CHARACTER_CARD_X + CHARACTER_CARD_WIDTH / 2
    column = round((x_norm - first_center) / CHARACTER_CARD_X_STEP)
    if not 0 <= column < CHARACTER_COLUMNS:
        return None
    card_x = CHARACTER_CARD_X + column * CHARACTER_CARD_X_STEP
    return column if card_x <= x_norm <= card_x + CHARACTER_CARD_WIDTH else None


def _relative_crop(frame, region):
    if frame is None or frame.size == 0:
        return None
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = region
    return frame[int(y1 * height):int(y2 * height), int(x1 * width):int(x2 * width)]


def validate_abyss_resolution(frame, minimum=(1280, 720), tolerance=0.02):
    """Return frame size or reject unsupported input before any game action."""
    if frame is None or not hasattr(frame, "shape") or len(frame.shape) < 2 or frame.size == 0:
        raise ValueError("没有可用的游戏捕获帧")
    height, width = frame.shape[:2]
    minimum_width, minimum_height = minimum
    if width < minimum_width or height < minimum_height:
        raise ValueError(
            f"自动深渊最低分辨率为 {minimum_width}x{minimum_height}，当前为 {width}x{height}"
        )
    aspect = width / height
    if abs(aspect - 16 / 9) > tolerance:
        raise ValueError(f"自动深渊仅支持 16:9，当前分辨率为 {width}x{height}（{aspect:.3f}:1）")
    return width, height


def avatar_template_height(screen_height):
    """Scale character reference portraits with the captured 16:9 frame."""
    return max(64, round(screen_height * 0.105))


def ocr_resize_scale(image_height, target_height, maximum=4.0):
    """Enlarge small OCR crops without needlessly exploding high-resolution images."""
    if image_height <= 0 or target_height <= 0 or maximum < 1:
        raise ValueError("OCR 缩放参数必须为正数且最大倍数不能小于 1")
    return max(1.0, min(float(maximum), target_height / image_height))


def frame_change_score(before, after, region=CHARACTER_GRID):
    """Return normalized mean pixel change in the character grid."""
    first = _relative_crop(before, region)
    second = _relative_crop(after, region)
    if first is None or second is None or first.size == 0 or second.size == 0:
        return 0.0
    first = cv2.resize(cv2.cvtColor(first, cv2.COLOR_BGR2GRAY), (128, 96), interpolation=cv2.INTER_AREA)
    second = cv2.resize(cv2.cvtColor(second, cv2.COLOR_BGR2GRAY), (128, 96), interpolation=cv2.INTER_AREA)
    return float(np.mean(cv2.absdiff(first, second))) / 255.0


def _scroll_thumb_geometry(frame):
    """Return the normalized centre and track coverage of the bright scrollbar thumb."""
    if frame is None or frame.size == 0:
        return None
    height, width = frame.shape[:2]
    left, right = int(0.915 * width), int(0.935 * width)
    top, bottom = int(0.08 * height), int(0.86 * height)
    crop = frame[top:bottom, left:right]
    if crop.size == 0:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    row_counts = np.count_nonzero(gray >= 155, axis=1)
    rows = np.flatnonzero(row_counts >= max(2, int(crop.shape[1] * 0.15)))
    if not len(rows):
        return None
    runs = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
    thumb = max(runs, key=len)
    if len(thumb) < max(6, int(height * 0.02)):
        return None
    return float(top + np.median(thumb)) / height, len(thumb) / crop.shape[0]


def scroll_thumb_center(frame):
    """Find the bright right-side character-list scrollbar and return normalized centre Y."""
    geometry = _scroll_thumb_geometry(frame)
    return geometry[0] if geometry is not None else None


def is_single_page_character_list(frame):
    """Return whether the scrollbar thumb fills enough of its track to prove there is one page."""
    geometry = _scroll_thumb_geometry(frame)
    return geometry is not None and geometry[1] >= SINGLE_PAGE_SCROLL_THUMB_COVERAGE


def parse_ocr_number(text, minimum=0, maximum=999):
    """Extract the last valid integer from OCR text."""
    values = [int(value) for value in re.findall(r"\d+", str(text or "").replace(",", ""))]
    return next((value for value in reversed(values) if minimum <= value <= maximum), None)


def parse_energy_number(text):
    """Parse 0..10 energy and repair the lightning glyph when OCR reads it as a leading 1."""
    values = [int(value) for value in re.findall(r"\d+", str(text or "").replace(",", ""))]
    for value in reversed(values):
        if 0 <= value <= 10:
            return value
        if 10 < value < 20:
            return value - 10
        if 100 <= value <= 110:
            return value - 100
    return None


def parse_selection_number(text):
    """Only accept an isolated quick-formation selection number."""
    normalized = _normalized_ocr_text(text)
    return int(normalized) if normalized in {"1", "2", "3"} else None


def classify_rover_element_crop(crop):
    """Classify the Rover's element icon conservatively from its dominant HSV hue."""
    if crop is None or crop.size == 0:
        return ROVER_UNKNOWN, 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    valid = (hsv[:, :, 1] >= 70) & (hsv[:, :, 2] >= 70)
    valid_count = int(np.count_nonzero(valid))
    if valid_count < crop.shape[0] * crop.shape[1] * 0.035:
        return ROVER_UNKNOWN, 0.0
    hue = hsv[:, :, 0]
    counts = {
        ROVER_SPECTRO: int(np.count_nonzero(valid & (hue >= 15) & (hue <= 42))),
        ROVER_AERO: int(np.count_nonzero(valid & (hue >= 43) & (hue <= 95))),
        ROVER_HAVOC: int(np.count_nonzero(valid & (hue >= 125) & (hue <= 165))),
    }
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    form, count = ranked[0]
    confidence = count / valid_count
    runner_up = ranked[1][1] / valid_count
    if confidence < 0.55 or confidence - runner_up < 0.15:
        return ROVER_UNKNOWN, confidence
    return form, confidence


def merge_character_records(records):
    """Deduplicate two screens and return both all recognized and strictly usable characters."""
    merged = {}
    for record in records:
        identity = effective_character_id(record)
        old = merged.get(identity)
        quality = (record.energy is not None, record.level is not None, record.confidence)
        old_quality = (
            (old.energy is not None, old.level is not None, old.confidence)
            if old is not None else (False, False, -1)
        )
        if old is None or quality > old_quality:
            merged[identity] = record
    available = sorted((record for record in merged.values() if record.available), key=lambda item: item.display_name)
    return merged, available


class AutoAbyssTask(WWOneTimeTask, BaseCombatTask):
    """Scan and automatically challenge every available Adversity Tower floor."""

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
        self.name = "🧪 自动深渊"
        self.description = (
            "扫描逆境深塔三座塔的关卡状态，按设置的顺序逐塔重新识别角色体力、自动编队并战斗。"
            "成功后继续下一层，失败时跳过当前塔剩余关卡。"
        )
        self.group_name = "🧪 测试功能"
        self.group_icon = Icon.DEVELOPER_TOOLS
        self.default_config = {TOWER_PRIORITY: SIDE_TOWERS_FIRST}
        self.config_type = {
            TOWER_PRIORITY: {
                "type": "drop_down",
                "options": [SIDE_TOWERS_FIRST, CENTER_TOWER_FIRST],
            },
            "清空当前账号识别结果": {
                "type": "button",
                "text": "清空识别结果",
                "callback": self.clear_current_character_scan,
            },
        }
        self.config_description = {
            TOWER_PRIORITY: "两侧塔优先：残响→回音→深境；中间塔优先：深境→残响→回音",
            "清空当前账号识别结果": "只清空本次运行内存中的角色结果，关闭程序后也会自动清除",
        }
        self._character_scan_results = {}
        self._avatar_orb = cv2.ORB_create(nfeatures=300, edgeThreshold=5, fastThreshold=5)
        self._avatar_matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        self._character_descriptors = None

    def run(self):
        WWOneTimeTask.run(self)
        self.log_info("自动深渊开始：先扫描三塔，再按设置逐塔扫描体力、编队和挑战")
        try:
            self._validate_runtime_resolution()
            self._set_status("进入深塔", "打开 F2 周期挑战")
            self.openF2Book()
            self._open_period_challenge()
            self._select_adversity_tower()
            self._open_adversity_tower()

            results = self._scan_all_towers()
            summary = "；".join(f"{tower}: {', '.join(states)}" for tower, states in results.items())
            self.info_set("扫描结果", summary)
            self.log_info(f"深塔关卡扫描完成：{summary}", notify=True)
            outcomes = self._run_towers(results)
            outcome_text = "；".join(f"{tower}: {result}" for tower, result in outcomes.items())
            self.info_set("挑战结果", outcome_text)
            self._set_status("自动深渊完成", outcome_text)
            self.log_info(f"自动深渊三塔流程完成：{outcome_text}", notify=True)
        except Exception as exc:
            message = str(exc)
            self.info_set("Error", message)
            self._set_status("自动深渊失败", message)
            raise

    def _validate_runtime_resolution(self):
        frame = self.frame
        try:
            width, height = validate_abyss_resolution(frame)
        except ValueError:
            self.screenshot("abyss_unsupported_resolution", frame=frame)
            raise
        self.log_info(f"自动深渊捕获分辨率：{width}x{height}（16:9）")
        return width, height

    def _scan_all_towers(self):
        results = {}
        for tower_name in TOWER_NAMES:
            self._set_status("扫描关卡", f"正在扫描 {tower_name}")
            self._open_tower(tower_name)
            results[tower_name] = self._scan_tower_floors()
            self._return_to_towers()
        return results

    def _run_towers(self, scan_results):
        outcomes = {}
        priority = self.config.get(TOWER_PRIORITY, SIDE_TOWERS_FIRST)
        for tower_name in tower_order(priority):
            states = scan_results[tower_name]
            first_floor = first_available_floor(states)
            if first_floor is None:
                outcome = "已完成跳过" if states and all(state == COMPLETED for state in states) else "无可挑战关卡"
                outcomes[tower_name] = outcome
                self._set_status("跳过本塔", f"{tower_name}：{outcome}")
                continue

            required_energy = tower_required_energy(tower_name, states)
            self._set_status(
                "扫描角色体力",
                f"{tower_name}剩余关卡要求每名角色至少 {required_energy} 点体力",
            )
            records = self._enter_and_scan_characters(tower_name, states)
            try:
                self._plan_and_form_team(records, minimum_energy=required_energy)
            except AbyssTeamUnavailable as exc:
                outcomes[tower_name] = "体力或角色不足"
                self._set_status("跳过本塔", f"{tower_name}：{exc}")
                self._return_from_team_to_towers()
                continue

            result, cleared = self._fight_selected_tower(tower_name, first_floor)
            outcomes[tower_name] = f"{result}（{cleared}层）"
        return outcomes

    def _set_status(self, stage, detail):
        self.info_set("状态", detail)
        publish_task_status(self, stage=stage, detail=detail)

    @staticmethod
    def _identity_display_names(plan, records):
        names = {effective_character_id(record): record.display_name for record in records}
        names.update({
            ROVER_SPECTRO: "光主",
            ROVER_AERO: "风主",
            ROVER_HAVOC: "暗主",
            ROVER_UNKNOWN: "主角（形态未知）",
        })
        for identity, display_name in zip(plan.preset.members, plan.preset.display_names):
            names.setdefault(identity, display_name)
        return names

    def _format_team_plan(self, plan, records):
        names = self._identity_display_names(plan, records)
        members = " / ".join(names.get(identity, identity) for identity in plan.members) or "无"
        matched = "完整命中" if plan.complete else f"命中{len(plan.matched)}/3"
        parts = [f"第{plan.preset.queue}队列", matched, members]
        if plan.substitutions:
            parts.append("、".join(
                f"{names.get(replacement, replacement)}替补{names.get(missing, missing)}"
                for missing, replacement in plan.substitutions
            ))
        if plan.broke_two_member_core:
            parts.append("为补齐队伍拆用了另一两人核心")
        return "；".join(parts)

    def _plan_and_form_team(self, records, minimum_energy=1):
        merged, available = merge_character_records(records)
        self._character_scan_results[self._current_scan_key()] = {
            "all": merged,
            "available": available,
        }
        eligible = [record for record in available if record.energy >= minimum_energy]
        display = "；".join(
            f"{record.display_name}（体力{record.energy}，Lv.{record.level}）" for record in eligible
        ) or "无"
        self.info_set("可用角色", display)
        self._set_status(
            "识别完成",
            f"已识别 {len(eligible)} 名体力不少于{minimum_energy}且等级大于60的角色",
        )
        self.log_info(f"角色识别完成：{display}", notify=True)

        plan = plan_team(available, minimum_energy=minimum_energy)
        plan_text = self._format_team_plan(plan, merged.values())
        self.info_set("编队计划", plan_text)
        if not plan.executable:
            self._set_status("无法组成三人队", plan_text)
            raise AbyssTeamUnavailable(
                f"体力不少于{minimum_energy}且等级大于60的可用角色不足三人：{plan_text}"
            )
        self._set_status("清理已有编队", "正在检查并清除快速编队页已有的 1/2/3")
        self._clear_all_selection()
        self._set_status("选择编队", plan_text)
        self._select_planned_team(plan, records)
        self._set_status("确认编队", "三个选择编号验证成功，正在点击完成")
        self._finish_team_formation()
        self._set_status("编队完成", f"{plan_text}；准备开启挑战")
        self.log_info(f"自动深渊编队完成：{plan_text}", notify=True)
        return plan

    def _current_scan_key(self):
        return str(getattr(self, "_runtime_status_account", None) or "当前账号")

    def clear_current_character_scan(self):
        key = self._current_scan_key()
        self._character_scan_results.pop(key, None)
        self.info_set("可用角色", "")
        self.info_set("状态", f"已清空 {key} 的角色识别结果")
        return True

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
        present = [
            done or blocked or self._row_has_floor_number(frame, row, index)
            for index, (row, done, blocked) in enumerate(zip(FLOOR_ROWS, completed, locked))
        ]
        try:
            states = aggregate_floor_states(completed, locked, present)
        except ValueError:
            self.screenshot("abyss_floor_presence_discontinuous", frame=frame)
            raise
        if not states:
            self.screenshot("abyss_floor_presence_empty", frame=frame)
            raise Exception("未识别到当前塔的关卡行")
        self.log_info(f"当前塔扫描结果：{', '.join(states)}")
        return states

    def _row_has_floor_number(self, frame, row, index):
        """Use the large left-side floor number as conservative row-presence evidence."""
        boxes = self.ocr(
            x=0.045,
            y=row[0],
            to_x=0.145,
            to_y=row[1],
            match=str(index + 1),
            frame=frame,
        )
        return exact_ocr_box(boxes, str(index + 1)) is not None

    def revive_action(self):
        """Close a death popup but never teleport away from Adversity Tower."""
        self.close_revive_popup()
        return False

    def _click_start_challenge(self):
        button = self._wait_exact_text_or_fail(
            "开启挑战", (0.75, 0.82, 0.98, 0.98), 8, "未找到编辑队伍页右下角的开启挑战"
        )
        self.click_box(button, after_sleep=1)
        return True

    def _prepare_challenge_map(self, tower_name, floor_number):
        self._set_status("进入挑战地图", f"{tower_name}第 {floor_number} 层正在加载")
        self._wait_exact_text_or_fail(
            "环境特性", (0.02, 0.18, 0.34, 0.58), 120, "加载后未识别到环境特性提示"
        )
        self.send_key("esc", after_sleep=1)
        if not self.wait_in_team_and_world(time_out=120, raise_if_not_found=False):
            self.screenshot("abyss_challenge_world_not_ready")
            raise Exception("关闭环境特性提示后未进入挑战地图")

    def _run_floor_combat(self, tower_name, floor_number):
        self._set_status("准备战斗", f"{tower_name}第 {floor_number} 层正在寻找开启挑战装置")
        if not self.walk_until_f(time_out=12, target_text="开启挑战", raise_if_not_found=False):
            self.screenshot("abyss_start_device_not_found")
            raise Exception("挑战地图中未找到开启挑战装置")
        self.pick_f()
        self._set_status("自动战斗", f"正在挑战 {tower_name}第 {floor_number} 层")
        try:
            self.combat_once(target=True)
        except CharDeadException:
            self.log_warning(f"{tower_name}第 {floor_number} 层角色死亡，等待深塔失败结算")

    def _wait_abyss_result(self):
        result = {"value": None}

        def read_result():
            boxes = self.ocr(
                x=0.20,
                y=0.06,
                to_x=0.82,
                to_y=0.96,
                match=["挑战成功", "挑战失败", "返回深塔", "继续挑战", "再次挑战"],
            )
            state = abyss_result_state(boxes)
            if state is None:
                return False
            button_text = "继续挑战" if state == "continue" else "返回深塔"
            button = exact_ocr_box(boxes, button_text)
            if button is None:
                return False
            result["value"] = state, button
            return True

        if not self.wait_until(read_result, time_out=30, raise_if_not_found=False):
            self.screenshot("abyss_result_not_recognized")
            raise Exception("战斗结束后未能完整识别深塔结算页")
        return result["value"]

    def _fight_selected_tower(self, tower_name, first_floor_index):
        """Fight at most four floors; continuing reuses the already formed team."""
        self._click_start_challenge()
        cleared = 0
        for floor_index in range(first_floor_index, len(FLOOR_ROWS)):
            floor_number = floor_index + 1
            self._prepare_challenge_map(tower_name, floor_number)
            self._run_floor_combat(tower_name, floor_number)
            state, button = self._wait_abyss_result()
            if state == "continue":
                cleared += 1
                self._set_status("挑战成功", f"{tower_name}第 {floor_number} 层完成，继续下一层")
                self.click_box(button, after_sleep=1)
                continue
            if state == "tower_complete":
                cleared += 1
                self._set_status("本塔完成", f"{tower_name}已完成，返回三塔页面")
                self.click_box(button, after_sleep=2)
                self._wait_for_tower_screen()
                return "完成", cleared
            if state == "failed":
                self._set_status("挑战失败", f"{tower_name}第 {floor_number} 层失败，跳过本塔剩余关卡")
                self.click_box(button, after_sleep=2)
                self._wait_for_tower_screen()
                return "失败", cleared
            raise Exception(f"未知深塔结算状态：{state}")
        self.screenshot("abyss_continue_past_last_floor")
        raise Exception(f"{tower_name}在第四层后仍显示继续挑战")

    def _return_to_towers(self):
        self.send_key("esc", after_sleep=2)
        self._wait_for_tower_screen()

    def _tower_screen_visible(self):
        boxes = self.ocr(match=list(TOWER_NAMES))
        return all(exact_ocr_box(boxes, tower_name) is not None for tower_name in TOWER_NAMES)

    def _return_from_team_to_towers(self):
        """Back out of quick formation/edit/floor pages without guessing a click target."""
        for _attempt in range(4):
            if self._tower_screen_visible():
                return True
            self.send_key("esc", after_sleep=1)
            if self.wait_until(self._tower_screen_visible, time_out=2, raise_if_not_found=False):
                return True
        self.screenshot("abyss_return_to_towers_failed")
        raise Exception("体力或角色不足后未能安全返回三塔页面")

    def _enter_and_scan_characters(self, tower_name, tower_states):
        floor_index = first_available_floor(tower_states)
        if floor_index is None:
            raise Exception(f"{tower_name}没有未完成且已解锁的可挑战关卡")

        self._set_status("选择深塔", f"正在打开{tower_name}")
        self._open_tower(tower_name)
        row = FLOOR_ROWS[floor_index]
        self._set_status("选择未完成关卡", f"正在选择{tower_name}第 {floor_index + 1} 层")
        self.click_relative(
            0.18,
            (row[0] + row[1]) / 2,
            after_sleep=1,
            name=f"{tower_name}第{floor_index + 1}层",
        )

        self._set_status("进入编辑队伍", "正在确认并点击挑战开始")
        challenge_start = self._wait_exact_text("挑战开始", (0.70, 0.80, 0.96, 0.98), 8)
        if challenge_start is None:
            self.screenshot("abyss_challenge_start_not_found")
            raise Exception("未找到关卡详情页右下角的挑战开始")
        self.click_box(challenge_start, after_sleep=1)

        self._wait_exact_text_or_fail("编辑队伍", (0.01, 0.01, 0.22, 0.16), 8, "未进入编辑队伍页面")
        quick = self._wait_exact_text_or_fail(
            "快速编队", (0.55, 0.82, 0.77, 0.98), 6, "未找到快速编队按钮"
        )
        self._wait_exact_text_or_fail(
            "开启挑战", (0.75, 0.82, 0.98, 0.98), 4, "编辑队伍页面结构异常"
        )
        self._set_status("打开快速编队", "正在打开快速编队角色列表")
        self.click_box(quick, after_sleep=1)
        self._wait_character_list_page()

        self._set_status("截取角色", "正在截取角色列表第 1 屏")
        first = self._wait_stable_character_frame()
        return self._scan_character_pages(first)

    def _scan_character_pages(self, first):
        single_page = is_single_page_character_list(first)
        first_records = self._recognize_character_screen(first, 1, include_incomplete=single_page)
        last_frame = first
        if single_page:
            self._character_page_count = 1
            self._character_page_index = 1
            self._set_status("截取角色", "检测到角色列表仅一页，使用第 1 屏识别结果")
            self.log_info("角色列表仅一页，无需滚动；已尝试识别底部可见的不完整卡片")
            records = first_records
        else:
            self._set_status("滚动角色列表", "正在向下滚动角色列表")
            second = self._scroll_to_second_character_page(first)
            self._set_status("截取角色", "正在截取角色列表第 2 屏")
            second_records = self._recognize_character_screen(second, 2)
            self._character_page_count = 2
            self._character_page_index = 2
            records = first_records + second_records
            last_frame = second
        if not records:
            self.screenshot("abyss_character_recognition_empty", frame=last_frame)
            raise Exception("角色列表未识别到角色头像")
        return records

    def _wait_exact_text(self, text, region, time_out):
        x1, y1, x2, y2 = region
        return self.wait_until(
            lambda: exact_ocr_box(self.ocr(x=x1, y=y1, to_x=x2, to_y=y2, match=text), text),
            time_out=time_out,
            raise_if_not_found=False,
        )

    def _wait_exact_text_or_fail(self, text, region, time_out, message):
        box = self._wait_exact_text(text, region, time_out)
        if box is None:
            self.screenshot(f"abyss_{text}_not_found")
            raise Exception(message)
        return box

    def _wait_character_list_page(self):
        self._wait_exact_text_or_fail("详情", (0.01, 0.01, 0.18, 0.14), 8, "未进入快速编队角色列表")
        self._wait_exact_text_or_fail("完成", (0.76, 0.84, 0.97, 0.99), 6, "角色列表页面结构异常")

    def _wait_stable_character_frame(self):
        state = {"signature": None, "stable": 0, "frame": None}

        def stable():
            frame = self.frame
            crop = _relative_crop(frame, CHARACTER_GRID)
            if crop is None or crop.size == 0:
                return False
            signature = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (96, 64), interpolation=cv2.INTER_AREA)
            if state["signature"] is not None and float(np.mean(cv2.absdiff(signature, state["signature"]))) < 2.5:
                state["stable"] += 1
            else:
                state["stable"] = 0
            state["signature"] = signature
            state["frame"] = frame.copy()
            return state["stable"] >= 1

        if not self.wait_until(stable, time_out=6, raise_if_not_found=False):
            raise Exception("角色列表画面在超时时间内没有稳定")
        return state["frame"]

    def _scroll_to_second_character_page(self, first):
        first_thumb = scroll_thumb_center(first)
        for attempt, amount in enumerate((-6, -10), start=1):
            if attempt > 1:
                self.ensure_in_front()
            self.scroll_relative(0.50, 0.50, amount)
            self.sleep(0.6)
            second = self._wait_stable_character_frame()
            second_thumb = scroll_thumb_center(second)
            grid_changed = frame_change_score(first, second) >= 0.035
            thumb_changed = (
                first_thumb is not None and second_thumb is not None and abs(first_thumb - second_thumb) >= 0.015
            )
            if grid_changed or thumb_changed:
                return second
            self.log_warning(f"角色列表第 {attempt} 次滚动未检测到有效变化")
        self.screenshot("abyss_character_scroll_failed", frame=first)
        raise Exception("角色列表滚动未生效，已停止以避免重复识别第一屏")

    def _show_character_page(self, page_index):
        page_count = getattr(self, "_character_page_count", 1)
        if not 1 <= page_index <= page_count:
            raise ValueError(f"角色列表页码超出范围：{page_index}/{page_count}")
        if getattr(self, "_character_page_index", 1) == page_index:
            return self._wait_stable_character_frame()
        before = self._wait_stable_character_frame()
        before_thumb = scroll_thumb_center(before)
        amount = 10 if page_index == 1 else -10
        for attempt in range(2):
            if attempt:
                self.ensure_in_front()
            self.scroll_relative(0.50, 0.50, amount)
            self.sleep(0.6)
            after = self._wait_stable_character_frame()
            after_thumb = scroll_thumb_center(after)
            grid_changed = frame_change_score(before, after) >= 0.035
            thumb_changed = (
                before_thumb is not None
                and after_thumb is not None
                and abs(before_thumb - after_thumb) >= 0.015
            )
            if grid_changed or thumb_changed:
                self._character_page_index = page_index
                return after
            self.log_warning(f"角色列表切换到第 {page_index} 页第 {attempt + 1} 次未检测到变化")
        self.screenshot(f"abyss_character_page_{page_index}_failed", frame=before)
        raise Exception(f"角色列表无法切换到第 {page_index} 页")

    @staticmethod
    def _record_sort_key(record):
        slot = character_card_slots()[record.slot_index]
        return not slot[-1], -record.confidence, record.screen_index, record.slot_index

    def _best_record_for_identity(self, records, identity):
        candidates = [record for record in records if effective_character_id(record) == identity]
        return min(candidates, key=self._record_sort_key, default=None)

    def _verify_record_identity(self, frame, record):
        slot = character_card_slots()[record.slot_index]
        avatar = self._slot_crop(frame, slot, (0.02, 0.01, 0.98, 0.78))
        identified = self._identify_character(avatar) if avatar is not None and avatar.size else None
        if identified is None or identified[0] != record.character_id:
            return False
        if record.character_id not in ROVER_CHARACTER_IDS:
            return True
        element_crop = self._slot_crop(frame, slot, (0.02, 0.02, 0.28, 0.28))
        rover_form, _confidence = classify_rover_element_crop(element_crop)
        return rover_form == effective_character_id(record)

    def _wait_selection_number(self, record, expected):
        slot = character_card_slots()[record.slot_index]
        return bool(self.wait_until(
            lambda: self._read_selection_number(self.frame, slot) == expected,
            time_out=2,
            raise_if_not_found=False,
        ))

    def _selection_records_all_pages(self):
        records = []
        for page_index in range(1, getattr(self, "_character_page_count", 1) + 1):
            frame = self._show_character_page(page_index)
            records.extend(self._recognize_character_screen(
                frame,
                page_index,
                include_incomplete=getattr(self, "_character_page_count", 1) == 1,
            ))
        return records

    def _click_character_record(self, record, expected_number):
        frame = self._show_character_page(record.screen_index)
        if not self._verify_record_identity(frame, record):
            self.log_warning(
                f"点击前角色身份复核失败：第{record.screen_index}屏槽位{record.slot_index}"
            )
            return False
        x, y = character_safe_click(character_card_slots()[record.slot_index])
        self.click_relative(x, y, after_sleep=0.35, name=record.display_name)
        return self._wait_selection_number(record, expected_number)

    def _clear_all_selection(self):
        records = self._selection_records_all_pages()
        try:
            selected = validate_selection_state(records)
        except ValueError:
            self.screenshot("abyss_character_selection_conflict")
            raise
        for number, identity in sorted(selected.items()):
            candidates = [
                record for record in records
                if effective_character_id(record) == identity and record.selection_number == number
            ]
            record = min(candidates, key=self._record_sort_key, default=None)
            if record is None:
                continue
            frame = self._show_character_page(record.screen_index)
            if not self._verify_record_identity(frame, record):
                self.screenshot("abyss_character_selection_clear_failed", frame=frame)
                raise Exception(f"清理选择编号 {number} 前角色身份复核失败")
            x, y = character_safe_click(character_card_slots()[record.slot_index])
            self.click_relative(x, y, after_sleep=0.35, name=f"取消{record.display_name}")
            if not self._wait_selection_number(record, None):
                self.screenshot("abyss_character_selection_clear_failed")
                raise Exception(f"角色选择编号 {number} 未能清除")
        remaining = validate_selection_state(self._selection_records_all_pages())
        if remaining:
            self.screenshot("abyss_character_selection_clear_failed")
            raise Exception(f"快速编队仍有未清除选择编号：{sorted(remaining)}")
        return True

    def _select_planned_team(self, plan, records):
        if not plan.executable or len(plan.members) != 3:
            raise Exception("编队计划不足三人，禁止点击角色")
        expected = {}
        for expected_number, identity in enumerate(plan.members, start=1):
            expected[expected_number] = identity
            record = self._best_record_for_identity(records, identity)
            if record is not None and self._click_character_record(record, expected_number):
                continue
            try:
                observed = validate_selection_state(self._selection_records_all_pages())
            except Exception as exc:
                self.screenshot("abyss_character_selection_unknown")
                raise Exception("角色选择编号状态无法确认，已停止且未重复点击") from exc
            if observed == expected:
                continue
            self.log_warning(
                f"角色选择编号状态无法确认：期望{sorted(expected)}，实际{sorted(observed)}"
            )
            self.screenshot("abyss_character_selection_unknown")
            raise Exception("角色选择编号状态无法确认，已停止且未重复点击")
        final = validate_selection_state(self._selection_records_all_pages())
        if final == expected:
            return True
        self.log_warning(f"角色选择最终编号不一致：期望{sorted(expected)}，实际{sorted(final)}")
        self.screenshot("abyss_character_selection_unknown")
        raise Exception("角色选择编号状态无法确认，已停止且未重复点击")

    def _finish_team_formation(self):
        complete = self._wait_exact_text_or_fail(
            "完成", (0.76, 0.84, 0.97, 0.99), 6, "未找到快速编队页面右下角的完成按钮"
        )
        self.click_box(complete, after_sleep=1)
        self._wait_exact_text_or_fail(
            "编辑队伍", (0.01, 0.01, 0.22, 0.16), 8, "完成后未返回编辑队伍页"
        )
        self._wait_exact_text_or_fail(
            "开启挑战", (0.75, 0.82, 0.98, 0.98), 4, "编辑队伍页面结构异常"
        )
        return True

    def _character_template_descriptors(self):
        if self._character_descriptors is not None:
            return self._character_descriptors
        descriptors = []
        target_height = avatar_template_height(self.height)
        seen = set()
        for template_name in char_names:
            try:
                feature = self.get_feature_by_name(template_name)
            except (ValueError, FileNotFoundError):
                continue
            if feature is None or feature.mat is None or feature.mat.size == 0:
                continue
            canonical = char_dict[template_name]["canonical_name"]
            key = (canonical, template_name)
            if key in seen:
                continue
            seen.add(key)
            template = feature.mat
            scale = target_height / max(1, template.shape[0])
            enlarged = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            _points, descriptor = self._avatar_orb.detectAndCompute(enlarged, None)
            if descriptor is not None:
                descriptors.append((canonical, descriptor))
        self._character_descriptors = descriptors
        return descriptors

    def _identify_character(self, avatar):
        _points, descriptor = self._avatar_orb.detectAndCompute(avatar, None)
        if descriptor is None:
            return None
        scores = {}
        for canonical, template_descriptor in self._character_template_descriptors():
            pairs = self._avatar_matcher.knnMatch(template_descriptor, descriptor, k=2)
            good = sum(1 for pair in pairs if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance)
            scores[canonical] = max(scores.get(canonical, 0), good)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if not ranked:
            return None
        best_name, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0
        if best_score < CHARACTER_MATCH_MINIMUM:
            return None
        if best_score - second_score < CHARACTER_MATCH_MARGIN and best_score < 12:
            return None
        return best_name, min(1.0, best_score / 25.0)

    @staticmethod
    def _slot_crop(frame, slot, local_region):
        _row, _column, x, y, width, height, _complete = slot
        lx1, ly1, lx2, ly2 = local_region
        return _relative_crop(frame, (
            x + width * lx1,
            y + height * ly1,
            x + width * lx2,
            y + height * ly2,
        ))

    def _read_complete_row_numbers(self, frame, row):
        row_y = CHARACTER_CARD_Y[row]
        left = CHARACTER_CARD_X
        right = CHARACTER_CARD_X + (CHARACTER_COLUMNS - 1) * CHARACTER_CARD_X_STEP + CHARACTER_CARD_WIDTH
        top = row_y + CHARACTER_CARD_HEIGHT * 0.58
        bottom = row_y + CHARACTER_CARD_HEIGHT * 0.99
        crop = _relative_crop(frame, (left, top, right, bottom))
        if crop is None or crop.size == 0:
            return {}
        scale = 2
        enlarged = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        try:
            boxes = self.ocr(0, 0, 1, 1, frame=enlarged)
        except Exception as exc:
            self.log_warning(f"角色第 {row + 1} 行数字 OCR 失败：{exc}")
            return {}
        frame_height, frame_width = frame.shape[:2]
        values = {column: {"energy": None, "level": None} for column in range(CHARACTER_COLUMNS)}
        crop_left = int(left * frame_width)
        crop_top = int(top * frame_height)
        for box in boxes or ():
            text = str(getattr(box, "name", box))
            center_x = crop_left + (box.x + box.width / 2) / scale
            center_y = crop_top + (box.y + box.height / 2) / scale
            x_norm, y_norm = center_x / frame_width, center_y / frame_height
            column = character_column_at(x_norm)
            if column is None:
                continue
            local_y = (y_norm - row_y) / CHARACTER_CARD_HEIGHT
            if "lv" in text.lower() or local_y >= 0.79:
                number = parse_ocr_number(text, minimum=1, maximum=100)
                if number is None:
                    continue
                if 1 <= number <= 100:
                    values[column]["level"] = number
            elif 0.58 <= local_y < 0.82:
                number = parse_energy_number(text)
                if number is None:
                    continue
                values[column]["energy"] = number
        return values

    def _read_slot_number(self, frame, slot, local_region, parser):
        crop = self._slot_crop(frame, slot, local_region)
        if crop is None or crop.size == 0:
            return None
        scale = ocr_resize_scale(crop.shape[0], 160)
        enlarged = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        try:
            boxes = self.ocr(0, 0, 1, 1, frame=enlarged)
        except Exception as exc:
            self.log_warning(f"角色卡局部数字 OCR 失败：{exc}")
            return None
        return next(
            (value for box in boxes or () if (value := parser(str(getattr(box, "name", box)))) is not None),
            None,
        )

    def _read_slot_energy(self, frame, slot):
        value = self._read_slot_number(frame, slot, (0.58, 0.55, 1.00, 0.82), parse_energy_number)
        if value is not None:
            return value
        crop = self._slot_crop(frame, slot, (0.67, 0.52, 1.00, 0.84))
        if crop is None or crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        yellow = cv2.inRange(hsv, (15, 70, 100), (45, 255, 255))
        yellow = cv2.copyMakeBorder(yellow, 30, 30, 60, 60, cv2.BORDER_CONSTANT, value=0)
        scale = ocr_resize_scale(yellow.shape[0], 256)
        prepared = cv2.resize(
            cv2.cvtColor(yellow, cv2.COLOR_GRAY2BGR),
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )
        try:
            boxes = self.ocr(0, 0, 1, 1, frame=prepared)
        except Exception as exc:
            self.log_warning(f"角色体力颜色分离 OCR 失败：{exc}")
            return None
        return next(
            (
                value
                for box in boxes or ()
                if (value := parse_energy_number(str(getattr(box, "name", box)))) is not None
            ),
            None,
        )

    def _read_selection_number(self, frame, slot):
        crop = self._slot_crop(frame, slot, (0.76, -0.06, 1.06, 0.25))
        if crop is None or crop.size == 0:
            return None
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        mask = cv2.inRange(gray, 180, 255)
        if np.count_nonzero(mask) < max(8, int(mask.size * 0.002)):
            return None
        mask = cv2.copyMakeBorder(mask, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=0)
        scale = ocr_resize_scale(mask.shape[0], 256)
        prepared = cv2.resize(
            cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR),
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )
        try:
            boxes = self.ocr(0, 0, 1, 1, frame=prepared)
        except Exception as exc:
            self.log_warning(f"角色选择编号 OCR 失败：{exc}")
            return None
        return next(
            (
                value
                for box in boxes or ()
                if (value := parse_selection_number(str(getattr(box, "name", box)))) is not None
            ),
            None,
        )

    def _recognize_character_screen(self, frame, screen_index, include_incomplete=False):
        total_screens = 1 if include_incomplete else 2
        self._set_status("识别角色", f"正在识别第 {screen_index}/{total_screens} 屏角色、体力和等级")
        numbers = {
            row: self._read_complete_row_numbers(frame, row)
            for row in range(CHARACTER_COMPLETE_ROWS)
        }
        records = []
        unknown = 0
        selected = []
        for slot_index, slot in enumerate(character_card_slots()):
            row, column, _x, _y, _width, _height, complete = slot
            if not complete and not include_incomplete:
                continue
            selection_number = self._read_selection_number(frame, slot)
            avatar = self._slot_crop(frame, slot, (0.02, 0.01, 0.98, 0.78))
            identified = self._identify_character(avatar) if avatar is not None and avatar.size else None
            if identified is None:
                if selection_number is not None:
                    self.screenshot(
                        f"abyss_selected_character_unknown_p{screen_index}_s{slot_index}", frame=frame
                    )
                    raise Exception(
                        f"第{screen_index}屏槽位{slot_index}存在选择编号 {selection_number}，但角色身份无法确认"
                    )
                unknown += 1
                continue
            character_id, confidence = identified
            info = char_dict.get(character_id, {})
            display_name = getattr(info.get("cls"), "__name__", character_id)
            rover_form = None
            rover_confidence = 0.0
            if character_id in ROVER_CHARACTER_IDS:
                element_crop = self._slot_crop(frame, slot, (0.02, 0.02, 0.28, 0.28))
                rover_form, rover_confidence = classify_rover_element_crop(element_crop)
                self.log_info(
                    f"主角元素形态：第{screen_index}屏槽位{slot_index} "
                    f"{rover_form} 置信度{rover_confidence:.2f}"
                )
                if rover_form == ROVER_UNKNOWN:
                    self.log_warning(
                        f"主角元素形态不确定：第{screen_index}屏槽位{slot_index}，"
                        f"置信度{rover_confidence:.2f}"
                    )
                    self.screenshot(
                        f"abyss_rover_form_unknown_p{screen_index}_s{slot_index}", frame=frame
                    )
            value = numbers.get(row, {}).get(column, {})
            energy = value.get("energy")
            level = value.get("level")
            if energy is None:
                energy = self._read_slot_energy(frame, slot)
            if level is None:
                level = self._read_slot_number(
                    frame,
                    slot,
                    (0.22, 0.78, 1.00, 1.00),
                    lambda text: parse_ocr_number(text, minimum=1, maximum=100),
                )
            if selection_number is not None:
                selected.append(f"{selection_number}:{self.tr(display_name)}")
            records.append(CharacterScanRecord(
                character_id=character_id,
                display_name=self.tr(display_name),
                energy=energy,
                level=level,
                confidence=confidence,
                screen_index=screen_index,
                slot_index=slot_index,
                rover_form=rover_form,
                rover_confidence=rover_confidence,
                selection_number=selection_number,
            ))
        partial = "，已尝试底部不完整卡片" if include_incomplete else "，底部不完整卡片 7 个"
        selection_text = f"，选择标记 {', '.join(selected)}" if selected else "，无选择标记"
        self.log_info(
            f"第 {screen_index} 屏识别角色 {len(records)} 个，未知头像 {unknown} 个"
            f"{partial}{selection_text}"
        )
        return records

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
