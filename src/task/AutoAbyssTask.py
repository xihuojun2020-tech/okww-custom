# -*- coding: utf-8 -*-
"""Scan Adversity Tower floors and the available character list without combat."""
from dataclasses import dataclass
from pathlib import Path
import re

import cv2
import numpy as np

from qfluentwidgets import FluentIcon as Icon

from src.char.CharFactory import char_dict, char_names
from src.task.BaseWWTask import BaseWWTask
from src.task.WWOneTimeTask import WWOneTimeTask
from src.task_status import publish_task_status


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


@dataclass(frozen=True)
class CharacterScanRecord:
    character_id: str
    display_name: str
    energy: int | None
    level: int | None
    confidence: float
    screen_index: int
    slot_index: int

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


def first_available_floor(states):
    """Return the first unlocked unfinished floor index, or None."""
    return next((index for index, state in enumerate(states) if state == AVAILABLE), None)


def _normalized_ocr_text(value):
    return re.sub(r"\s+", "", str(value or "")).strip()


def exact_ocr_box(boxes, expected):
    """Match complete button text; similar challenge buttons must never alias."""
    expected = _normalized_ocr_text(expected)
    return next(
        (box for box in boxes or () if _normalized_ocr_text(getattr(box, "name", box)) == expected),
        None,
    )


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


def frame_change_score(before, after, region=CHARACTER_GRID):
    """Return normalized mean pixel change in the character grid."""
    first = _relative_crop(before, region)
    second = _relative_crop(after, region)
    if first is None or second is None or first.size == 0 or second.size == 0:
        return 0.0
    first = cv2.resize(cv2.cvtColor(first, cv2.COLOR_BGR2GRAY), (128, 96), interpolation=cv2.INTER_AREA)
    second = cv2.resize(cv2.cvtColor(second, cv2.COLOR_BGR2GRAY), (128, 96), interpolation=cv2.INTER_AREA)
    return float(np.mean(cv2.absdiff(first, second))) / 255.0


def scroll_thumb_center(frame):
    """Find the bright right-side character-list scrollbar and return normalized centre Y."""
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
    if len(rows) < max(6, int(height * 0.02)):
        return None
    return float(top + np.median(rows)) / height


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


def merge_character_records(records):
    """Deduplicate two screens and return both all recognized and strictly usable characters."""
    merged = {}
    for record in records:
        old = merged.get(record.character_id)
        quality = (record.energy is not None, record.level is not None, record.confidence)
        old_quality = (
            (old.energy is not None, old.level is not None, old.confidence)
            if old is not None else (False, False, -1)
        )
        if old is None or quality > old_quality:
            merged[record.character_id] = record
    available = sorted((record for record in merged.values() if record.available), key=lambda item: item.display_name)
    return merged, available


class AutoAbyssTask(WWOneTimeTask, BaseWWTask):
    """Scan the tower floors, then open quick formation and scan usable characters."""

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
        self.name = "🧪 自动深渊：关卡与角色扫描"
        self.description = (
            "扫描逆境深塔三座塔的关卡状态，然后进入残响之塔首个可挑战关卡的快速编队页，"
            "自动识别两屏角色、体力和等级。不会选择角色或点击开启挑战，不会进入战斗。"
        )
        self.group_name = "🧪 测试功能"
        self.group_icon = Icon.DEVELOPER_TOOLS
        self.default_config = {}
        self.config_type = {
            "清空当前账号识别结果": {
                "type": "button",
                "text": "清空识别结果",
                "callback": self.clear_current_character_scan,
            },
        }
        self.config_description = {
            "清空当前账号识别结果": "只清空本次运行内存中的角色结果，关闭程序后也会自动清除",
        }
        self._character_scan_results = {}
        self._avatar_orb = cv2.ORB_create(nfeatures=300, edgeThreshold=5, fastThreshold=5)
        self._avatar_matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        self._character_descriptors = None

    def run(self):
        WWOneTimeTask.run(self)
        self.log_info("安全边界：只进入角色列表，不选择角色、不点击开启挑战、不进入战斗")
        try:
            self._set_status("进入深塔", "打开 F2 周期挑战")
            self.openF2Book()
            self._open_period_challenge()
            self._select_adversity_tower()
            self._open_adversity_tower()

            results = {}
            for tower_name in TOWER_NAMES:
                self._set_status("扫描关卡", f"正在扫描 {tower_name}")
                self._open_tower(tower_name)
                results[tower_name] = self._scan_tower_floors()
                self._return_to_towers()

            summary = "；".join(f"{tower}: {', '.join(states)}" for tower, states in results.items())
            self.info_set("扫描结果", summary)
            self.log_info(f"深塔关卡扫描完成：{summary}", notify=True)
            records = self._enter_and_scan_characters(results[TOWER_NAMES[0]])
            merged, available = merge_character_records(records)
            self._character_scan_results[self._current_scan_key()] = {
                "all": merged,
                "available": available,
            }
            display = "；".join(
                f"{record.display_name}（体力{record.energy}，Lv.{record.level}）" for record in available
            ) or "无"
            self.info_set("可用角色", display)
            self._set_status("识别完成", f"已识别 {len(available)} 名体力大于0且等级大于60的角色")
            self.log_info(f"角色识别完成：{display}", notify=True)
        except Exception as exc:
            message = str(exc)
            self.info_set("Error", message)
            self._set_status("自动深渊失败", message)
            raise

    def _set_status(self, stage, detail):
        self.info_set("状态", detail)
        publish_task_status(self, stage=stage, detail=detail)

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
        states = aggregate_floor_states(completed, locked)
        self.log_info(f"当前塔扫描结果：{', '.join(states)}")
        return states

    def _return_to_towers(self):
        self.send_key("esc", after_sleep=2)
        self._wait_for_tower_screen()

    def _enter_and_scan_characters(self, resonance_states):
        floor_index = first_available_floor(resonance_states)
        if floor_index is None:
            raise Exception("残响之塔没有未完成且已解锁的可挑战关卡")

        self._set_status("选择残响之塔", "正在重新打开残响之塔")
        self._open_tower(TOWER_NAMES[0])
        row = FLOOR_ROWS[floor_index]
        self._set_status("选择未完成关卡", f"正在选择残响之塔第 {floor_index + 1} 层")
        self.click_relative(0.18, (row[0] + row[1]) / 2, after_sleep=1, name=f"残响之塔第{floor_index + 1}层")

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
        first_records = self._recognize_character_screen(first, 1)

        self._set_status("滚动角色列表", "正在向下滚动角色列表")
        second = self._scroll_to_second_character_page(first)
        self._set_status("截取角色", "正在截取角色列表第 2 屏")
        second_records = self._recognize_character_screen(second, 2)
        records = first_records + second_records
        if not records:
            self.screenshot("abyss_character_recognition_empty", frame=second)
            raise Exception("两屏角色列表均未识别到角色头像")
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

    def _character_template_descriptors(self):
        if self._character_descriptors is not None:
            return self._character_descriptors
        descriptors = []
        target_height = max(96, int(self.height * 0.105))
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
        enlarged = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
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
        prepared = cv2.resize(
            cv2.cvtColor(yellow, cv2.COLOR_GRAY2BGR),
            None,
            fx=3,
            fy=3,
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

    def _recognize_character_screen(self, frame, screen_index):
        self._set_status("识别角色", f"正在识别第 {screen_index}/2 屏角色、体力和等级")
        numbers = {
            row: self._read_complete_row_numbers(frame, row)
            for row in range(CHARACTER_COMPLETE_ROWS)
        }
        records = []
        unknown = 0
        for slot_index, slot in enumerate(character_card_slots()):
            row, column, _x, _y, _width, _height, complete = slot
            if not complete:
                continue
            avatar = self._slot_crop(frame, slot, (0.02, 0.01, 0.98, 0.78))
            identified = self._identify_character(avatar) if avatar is not None and avatar.size else None
            if identified is None:
                unknown += 1
                continue
            character_id, confidence = identified
            info = char_dict.get(character_id, {})
            display_name = getattr(info.get("cls"), "__name__", character_id)
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
            records.append(CharacterScanRecord(
                character_id=character_id,
                display_name=self.tr(display_name),
                energy=energy,
                level=level,
                confidence=confidence,
                screen_index=screen_index,
                slot_index=slot_index,
            ))
        self.log_info(f"第 {screen_index} 屏识别角色 {len(records)} 个，未知头像 {unknown} 个，底部不完整卡片 7 个")
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
