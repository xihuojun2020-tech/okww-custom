# -*- coding: utf-8 -*-
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from ok.feature.FeatureSet import FeatureSet

from src.Labels import Labels
from src.task.AutoAbyssTask import (
    AVAILABLE,
    AbyssTeamUnavailable,
    AutoAbyssTask,
    CENTER_TOWER_FIRST,
    CharacterScanRecord,
    best_template_match,
    COMPLETED,
    LOCKED,
    aggregate_floor_states,
    abyss_result_state,
    avatar_template_height,
    classify_floor_evidence,
    character_column_at,
    character_card_slots,
    character_safe_click,
    count_occupied_tower_slots,
    energy_digit_count,
    exact_ocr_box,
    first_available_floor,
    floor_energy_cost,
    FLOOR_ROWS,
    floor_state_sequence_valid,
    frame_change_score,
    match_travel_button,
    merge_character_records,
    classify_rover_element_crop,
    parse_energy_number,
    parse_ocr_number,
    parse_selection_number,
    parse_tower_star_total,
    ocr_resize_scale,
    SELECTION_MARKER_REGION,
    selection_marker_present,
    is_single_page_character_list,
    scroll_thumb_center,
    selected_floor_index,
    tower_click_point,
    tower_order,
    tower_required_energy,
    UNKNOWN,
    validate_abyss_resolution,
    validate_selection_state,
)
from src.task.abyss_team_planner import ROVER_AERO, ROVER_HAVOC, ROVER_SPECTRO, ROVER_UNKNOWN
from src.task.BaseCombatTask import CharDeadException


class TestAutoAbyssTask(unittest.TestCase):
    def test_qingxiao_character_scan_from_720p_through_4k(self):
        class OfflineAbyssTask(AutoAbyssTask):
            @property
            def height(self):
                return self._offline_height

            @property
            def width(self):
                return self._offline_width

        resolutions = ((1280, 720), (1600, 900), (1920, 1080), (2560, 1440), (3840, 2160))
        for index, (width, height) in enumerate(resolutions):
            selected = index % 2 == 0
            with self.subTest(width=width, height=height, selected=selected):
                frame = np.zeros((height, width, 3), dtype=np.uint8)
                feature_set = FeatureSet(
                    False,
                    'assets/coco_annotations.json',
                    0.002,
                    0.002,
                    default_threshold=0.7,
                )
                feature = feature_set.get_feature_by_name(frame, Labels.char_qingxiao)
                self.assertIsNotNone(feature)

                task = OfflineAbyssTask.__new__(OfflineAbyssTask)
                task._offline_height = height
                task._offline_width = width
                task._avatar_orb = cv2.ORB_create(nfeatures=300, edgeThreshold=5, fastThreshold=5)
                task._avatar_matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
                task._character_descriptors = None
                task.get_feature_by_name = lambda name: feature if name == Labels.char_qingxiao else None
                task._set_status = lambda *_args: None
                task.log_info = lambda *_args: None
                task.log_warning = lambda *_args: None
                task.screenshot = lambda *_args, **_kwargs: None
                task.tr = lambda value: value
                task.ocr = lambda *_args, **_kwargs: [SimpleNamespace(name="1")] if selected else []
                task._read_complete_row_numbers = lambda _frame, row: (
                    {0: {'energy': 10, 'level': 90}} if row == 0 else {}
                )

                slot = character_card_slots()[0]
                _row, _column, x, y, card_width, card_height, _complete = slot
                avatar_left = int((x + card_width * 0.02) * width)
                avatar_top = int((y + card_height * 0.01) * height)
                avatar_right = int((x + card_width * 0.98) * width)
                avatar_bottom = int((y + card_height * 0.78) * height)
                target_height = avatar_template_height(height)
                scale = target_height / feature.mat.shape[0]
                avatar = cv2.resize(feature.mat, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                paste_x = avatar_left + (avatar_right - avatar_left - avatar.shape[1]) // 2
                paste_y = avatar_top + (avatar_bottom - avatar_top - avatar.shape[0]) // 2
                frame[paste_y:paste_y + avatar.shape[0], paste_x:paste_x + avatar.shape[1]] = avatar
                if selected:
                    cv2.rectangle(
                        frame,
                        (avatar_left, avatar_top),
                        (avatar_right - 1, avatar_bottom - 1),
                        (40, 190, 255),
                        max(2, height // 540),
                    )
                    cv2.putText(
                        frame,
                        '1',
                        (int((x + card_width * 0.78) * width), int((y + card_height * 0.18) * height)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        height / 1200,
                        (40, 190, 255),
                        2,
                    )

                records = task._recognize_character_screen(frame, 1)

                self.assertEqual(len(records), 1)
                self.assertEqual(records[0].character_id, Labels.char_qingxiao)
                self.assertEqual(records[0].energy, 10)
                self.assertEqual(records[0].level, 90)
                self.assertTrue(records[0].available)

    def test_rover_element_colour_classifier_is_strict(self):
        def solid_hsv(hue, saturation=220, value=220):
            hsv = np.full((80, 80, 3), (hue, saturation, value), dtype=np.uint8)
            return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

        self.assertEqual(classify_rover_element_crop(solid_hsv(28))[0], ROVER_SPECTRO)
        self.assertEqual(classify_rover_element_crop(solid_hsv(65))[0], ROVER_AERO)
        self.assertEqual(classify_rover_element_crop(solid_hsv(145))[0], ROVER_HAVOC)
        self.assertEqual(classify_rover_element_crop(solid_hsv(0, saturation=0))[0], ROVER_UNKNOWN)

    def test_selection_number_accepts_only_one_two_three(self):
        self.assertEqual(parse_selection_number("1"), 1)
        self.assertEqual(parse_selection_number(" 3 "), 3)
        self.assertIsNone(parse_selection_number("10"))
        self.assertIsNone(parse_selection_number("Lv.90"))

    def test_selection_number_reads_white_badge_from_720p_through_4k(self):
        resolutions = ((1280, 720), (1600, 900), (1920, 1080), (2560, 1440), (3840, 2160))
        for index, (width, height) in enumerate(resolutions):
            expected = (1, 2, 3)[index % 3]
            with self.subTest(width=width, height=height, expected=expected):
                frame = np.zeros((height, width, 3), dtype=np.uint8)
                slot = character_card_slots()[0]
                _row, _column, x, y, card_width, card_height, _complete = slot
                badge_left = int((x + card_width * 0.76) * width)
                badge_top = int((y - card_height * 0.04) * height)
                badge_right = int((x + card_width * 1.05) * width)
                badge_bottom = int((y + card_height * 0.23) * height)
                cv2.rectangle(
                    frame,
                    (badge_left, badge_top),
                    (badge_right, badge_bottom),
                    (42, 42, 42),
                    -1,
                )
                cv2.putText(
                    frame,
                    str(expected),
                    (int((x + card_width * 0.84) * width), int((y + card_height * 0.17) * height)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    height / 1200,
                    (245, 245, 245),
                    max(2, height // 540),
                )

                task = AutoAbyssTask.__new__(AutoAbyssTask)
                task.log_warning = lambda *_args: None
                task.ocr = lambda *_args, **_kwargs: [SimpleNamespace(name=str(expected))]

                self.assertEqual(task._read_selection_number(frame, slot), expected)

    def test_selection_marker_detects_gold_card_edges_from_720p_through_4k(self):
        for width, height in ((1280, 720), (1600, 900), (1920, 1080), (2560, 1440), (3840, 2160)):
            with self.subTest(width=width, height=height):
                frame = np.zeros((height, width, 3), dtype=np.uint8)
                slot = character_card_slots()[7]
                _row, _column, x, y, card_width, card_height, _complete = slot
                cv2.rectangle(
                    frame,
                    (int(x * width), int(y * height)),
                    (int((x + card_width) * width), int((y + card_height * 0.70) * height)),
                    (40, 190, 255),
                    max(2, height // 540),
                )
                crop = AutoAbyssTask._slot_crop(frame, slot, SELECTION_MARKER_REGION)
                self.assertTrue(selection_marker_present(crop))

    def test_selection_marker_rejects_empty_local_crop(self):
        self.assertFalse(selection_marker_present(np.zeros((80, 80, 3), dtype=np.uint8)))

    def test_selection_marker_roi_matches_real_2560x1440_failure_frame(self):
        frame = cv2.imread("tests/images/abyss_selection_markers_123.png")
        detected = [
            index
            for index, slot in enumerate(character_card_slots())
            if selection_marker_present(AutoAbyssTask._slot_crop(frame, slot, SELECTION_MARKER_REGION))
        ]
        self.assertEqual(detected, [9, 10, 12])

    def test_supported_16_by_9_resolutions_and_minimum_are_enforced(self):
        for width, height in (
            (1280, 720),
            (1600, 900),
            (1920, 1080),
            (2560, 1440),
            (3840, 2160),
        ):
            with self.subTest(width=width, height=height):
                frame = np.zeros((height, width, 3), dtype=np.uint8)
                self.assertEqual(validate_abyss_resolution(frame), (width, height))

        with self.assertRaisesRegex(ValueError, "最低分辨率"):
            validate_abyss_resolution(np.zeros((576, 1024, 3), dtype=np.uint8))
        with self.assertRaisesRegex(ValueError, "16:9"):
            validate_abyss_resolution(np.zeros((1200, 1920, 3), dtype=np.uint8))
        with self.assertRaisesRegex(ValueError, "捕获帧"):
            validate_abyss_resolution(None)

    def test_avatar_and_local_ocr_scaling_cover_720p_through_4k(self):
        heights = (720, 900, 1080, 1440, 2160)
        self.assertEqual([avatar_template_height(height) for height in heights], [76, 94, 113, 151, 227])

        crop_heights = [round(height * 0.07) for height in heights]
        scales = [ocr_resize_scale(crop_height, 160) for crop_height in crop_heights]
        self.assertTrue(all(1.0 <= scale <= 4.0 for scale in scales))
        self.assertEqual(scales, sorted(scales, reverse=True))
        self.assertAlmostEqual(scales[-1], 160 / crop_heights[-1])

    def test_match_travel_button_uses_the_same_card_row(self):
        title = SimpleNamespace(x=100, y=400, width=180, height=40)
        same_card = SimpleNamespace(x=1200, y=405, width=80, height=30)
        other_card = SimpleNamespace(x=1200, y=700, width=80, height=30)
        self.assertIs(match_travel_button(title, [other_card, same_card]), same_card)

    def test_match_travel_button_rejects_buttons_left_of_target_card(self):
        title = SimpleNamespace(x=500, y=400, width=180, height=40)
        wrong = SimpleNamespace(x=100, y=400, width=80, height=30)
        self.assertIsNone(match_travel_button(title, [wrong]))

    def test_match_travel_button_accepts_the_button_below_the_content_title(self):
        title = SimpleNamespace(x=960, y=385, width=120, height=40)
        same_card = SimpleNamespace(x=1720, y=465, width=100, height=40)
        other_card = SimpleNamespace(x=1720, y=850, width=100, height=40)
        self.assertIs(match_travel_button(title, [other_card, same_card]), same_card)

    def test_aggregate_floor_states_prefers_completed_then_locked_then_available(self):
        self.assertEqual(
            aggregate_floor_states([True, False, False, False], [False, True, False, False]),
            (COMPLETED, LOCKED, AVAILABLE, AVAILABLE),
        )

    def test_aggregate_floor_states_trims_only_trailing_missing_rows(self):
        self.assertEqual(
            aggregate_floor_states(
                [True, False, False, False],
                [False, False, False, False],
                [True, True, False, False],
            ),
            (COMPLETED, AVAILABLE),
        )
        self.assertEqual(
            aggregate_floor_states(
                [False, False, False, False],
                [False, True, True, True],
                [False, True, True, True],
            ),
            (AVAILABLE, LOCKED, LOCKED, LOCKED),
        )

    def test_tower_star_total_is_reference_only_and_parses_common_slashes(self):
        self.assertEqual(parse_tower_star_total("12/12"), 12)
        self.assertEqual(parse_tower_star_total(" 0 ／ 12 "), 0)
        self.assertIsNone(parse_tower_star_total("11/18"))
        self.assertIsNone(parse_tower_star_total("20/12"))

    def test_floor_evidence_prefers_reset_and_portraits_without_treating_numbers_as_completion(self):
        self.assertEqual(classify_floor_evidence(False, 0, True, True, True), COMPLETED)
        self.assertEqual(classify_floor_evidence(False, 2, False, True, True), COMPLETED)
        self.assertEqual(classify_floor_evidence(False, 0, False, True, True), AVAILABLE)
        self.assertEqual(classify_floor_evidence(True, 0, False, False, False), LOCKED)
        self.assertEqual(classify_floor_evidence(True, 1, False, False, False), "状态未知")
        self.assertEqual(classify_floor_evidence(False, 0, False, False, False), "状态未知")

    def test_avatar_occupancy_and_selected_border_are_resolution_independent(self):
        rng = np.random.default_rng(7)
        for width, height in ((1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)):
            with self.subTest(width=width, height=height):
                frame = np.full((height, width, 3), 64, dtype=np.uint8)
                row_index = 2
                row = FLOOR_ROWS[row_index]
                center_x = int(0.225 * width)
                center_y = int(((row[0] + row[1]) / 2 + 0.006) * height)
                radius = max(12, round(0.022 * width))
                noise = rng.integers(0, 256, (radius * 2, radius * 2, 3), dtype=np.uint8)
                frame[center_y - radius:center_y + radius, center_x - radius:center_x + radius] = noise

                top = int((row[0] + 0.009) * height)
                bottom = int((row[1] - 0.004) * height)
                left = int(0.043 * width)
                right = int(0.305 * width)
                thickness = max(2, round(height / 288))
                cv2.rectangle(frame, (left, top), (right, bottom), (230, 230, 230), thickness)

                self.assertEqual(count_occupied_tower_slots(frame, row_index), 1)
                self.assertEqual(selected_floor_index(frame), row_index)

    def test_selected_border_accepts_realistic_partial_highlight(self):
        frame = np.full((1440, 2560, 3), 48, dtype=np.uint8)
        row_index = 2
        row = FLOOR_ROWS[row_index]
        top = int((row[0] + 0.009) * 1440)
        bottom = int((row[1] - 0.004) * 1440)
        left = int(0.043 * 2560)
        right = int(0.305 * 2560)
        segment = int((right - left) * 0.16)
        thickness = max(2, round(1440 / 288))
        cv2.line(frame, (left, top), (left + segment, top), (210, 210, 210), thickness)
        cv2.line(frame, (right - segment, bottom), (right, bottom), (210, 210, 210), thickness)

        self.assertEqual(selected_floor_index(frame), row_index)

    def test_tower_scan_logs_and_recovers_missing_earlier_presence(self):
        class OfflineAbyssTask(AutoAbyssTask):
            @property
            def frame(self):
                return np.zeros((1440, 2560, 3), dtype=np.uint8)

        task = OfflineAbyssTask.__new__(OfflineAbyssTask)
        warnings = []
        task._row_matches = lambda _frame, row, name, _threshold: name == "locked" and row != FLOOR_ROWS[0]
        task._row_has_floor_number = lambda *_args: False
        task._verify_floor_state = lambda *_args: AVAILABLE
        task.log_warning = warnings.append
        task.log_info = lambda *_args: None
        task.screenshot = lambda *_args, **_kwargs: None

        self.assertEqual(task._scan_tower_floors(), (AVAILABLE, LOCKED, LOCKED, LOCKED))
        self.assertTrue(any("第 1 层存在性漏识别" in warning for warning in warnings))

    def test_floor_state_sequence_rejects_conflicts_and_unknowns(self):
        self.assertTrue(floor_state_sequence_valid((COMPLETED, AVAILABLE, LOCKED, LOCKED)))
        self.assertTrue(floor_state_sequence_valid((COMPLETED, COMPLETED, COMPLETED, COMPLETED)))
        self.assertFalse(floor_state_sequence_valid((AVAILABLE, COMPLETED, LOCKED)))
        self.assertFalse(floor_state_sequence_valid((COMPLETED, AVAILABLE, AVAILABLE)))
        self.assertFalse(floor_state_sequence_valid((COMPLETED, UNKNOWN)))

    def test_floor_verification_clicks_only_the_floor_row_when_reset_is_visible(self):
        class OfflineAbyssTask(AutoAbyssTask):
            @property
            def frame(self):
                return np.zeros((720, 1280, 3), dtype=np.uint8)

        clicks = []
        task = OfflineAbyssTask.__new__(OfflineAbyssTask)
        task.click_relative = lambda *args, **kwargs: clicks.append((args, kwargs))
        task.wait_until = lambda *_args, **_kwargs: True
        task.log_info = lambda *_args: None
        task.log_warning = lambda *_args: None
        task._read_floor_action_buttons = lambda _frame: (True, False)

        with patch("src.task.AutoAbyssTask.selected_floor_index", return_value=0), patch(
            "src.task.AutoAbyssTask.count_occupied_tower_slots", return_value=3
        ):
            self.assertEqual(task._verify_floor_state("残响之塔", 0, 3, 12), COMPLETED)

        self.assertEqual(len(clicks), 1)
        self.assertAlmostEqual(clicks[0][0][0], 0.18)
        self.assertIn("扫描残响之塔第1层", clicks[0][1]["name"])

    def test_floor_verification_falls_back_to_portraits_after_reset_ocr_retries(self):
        class OfflineAbyssTask(AutoAbyssTask):
            @property
            def frame(self):
                return np.zeros((720, 1280, 3), dtype=np.uint8)

        warnings = []
        task = OfflineAbyssTask.__new__(OfflineAbyssTask)
        task.click_relative = lambda *_args, **_kwargs: None
        task.wait_until = lambda *_args, **_kwargs: True
        task.log_info = lambda *_args: None
        task.log_warning = warnings.append
        task._read_floor_action_buttons = lambda _frame: (False, False)

        with patch("src.task.AutoAbyssTask.selected_floor_index", return_value=0), patch(
            "src.task.AutoAbyssTask.count_occupied_tower_slots", return_value=3
        ):
            self.assertEqual(task._verify_floor_state("残响之塔", 0, 3, 12), COMPLETED)

        self.assertTrue(any("按已通关处理" in warning for warning in warnings))

    def test_floor_verification_uses_challenge_button_when_border_detection_misses(self):
        class OfflineAbyssTask(AutoAbyssTask):
            @property
            def frame(self):
                return np.zeros((1440, 2560, 3), dtype=np.uint8)

        task = OfflineAbyssTask.__new__(OfflineAbyssTask)
        task.click_relative = lambda *_args, **_kwargs: None
        task.wait_until = lambda *_args, **_kwargs: False
        task.log_info = lambda *_args: None
        task.log_warning = lambda *_args: None
        task._read_floor_action_buttons = lambda _frame: (False, True)

        with patch("src.task.AutoAbyssTask.selected_floor_index", return_value=None), patch(
            "src.task.AutoAbyssTask.count_occupied_tower_slots", return_value=0
        ):
            self.assertEqual(task._verify_floor_state("残响之塔", 2, 0, 6), AVAILABLE)

    def test_twelve_star_conflict_retries_then_marks_the_whole_tower_unknown(self):
        class OfflineAbyssTask(AutoAbyssTask):
            @property
            def frame(self):
                return np.zeros((720, 1280, 3), dtype=np.uint8)

        task = OfflineAbyssTask.__new__(OfflineAbyssTask)
        task._row_matches = lambda *_args: False
        task._row_has_floor_number = lambda *_args: True
        task._verify_floor_state = lambda *_args: AVAILABLE
        task.log_info = lambda *_args: None
        task.log_warning = lambda *_args: None
        task.screenshot = lambda *_args, **_kwargs: None
        task.sleep = lambda *_args: None

        self.assertEqual(
            task._scan_tower_floors("残响之塔", star_total=12),
            (UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN),
        )

    def test_tower_star_totals_map_left_center_and_right(self):
        class OfflineAbyssTask(AutoAbyssTask):
            @property
            def frame(self):
                return np.zeros((1440, 2560, 3), dtype=np.uint8)

            @property
            def width(self):
                return 2560

        task = OfflineAbyssTask.__new__(OfflineAbyssTask)
        task.ocr = lambda **_kwargs: [
            SimpleNamespace(name="12/12", x=620, width=40),
            SimpleNamespace(name="0 / 12", x=1380, width=40),
            SimpleNamespace(name="6／12", x=2070, width=40),
        ]
        task.log_info = lambda *_args: None

        self.assertEqual(
            task._read_tower_star_totals(),
            {"残响之塔": 12, "深境之塔": 0, "回音之塔": 6},
        )

    def test_tower_click_uses_title_x_and_diamond_height(self):
        title = SimpleNamespace(x=1000, y=100, width=200, height=40)
        self.assertEqual(tower_click_point(title, 2560), (1100 / 2560, 0.47))

    def test_best_template_match_uses_score_without_requiring_a_fixed_navigation_y(self):
        upper = (30, 220, 80, 80, 0.31)
        lower = (30, 760, 80, 80, 0.28)
        self.assertIs(best_template_match([lower, None, upper]), upper)

    def test_first_available_floor_skips_completed_and_locked(self):
        self.assertEqual(first_available_floor((COMPLETED, LOCKED, AVAILABLE, AVAILABLE)), 2)
        self.assertIsNone(first_available_floor((COMPLETED, LOCKED, COMPLETED, LOCKED)))

    def test_tower_order_and_remaining_energy_follow_priority_and_floor_costs(self):
        self.assertEqual(tower_order("两侧塔优先"), ("残响之塔", "回音之塔", "深境之塔"))
        self.assertEqual(tower_order("中间塔优先"), ("深境之塔", "残响之塔", "回音之塔"))
        self.assertEqual(
            tower_required_energy("残响之塔", (COMPLETED, AVAILABLE, LOCKED, LOCKED)),
            2,
        )
        self.assertEqual(
            tower_required_energy("深境之塔", (AVAILABLE, LOCKED, LOCKED, LOCKED)),
            5,
        )
        self.assertEqual(floor_energy_cost("残响之塔", 2), 3)
        self.assertEqual(floor_energy_cost("深境之塔", 2), 5)

    def test_tower_scan_uses_large_floor_numbers_to_trim_missing_rows(self):
        class OfflineAbyssTask(AutoAbyssTask):
            @property
            def frame(self):
                return np.zeros((1440, 2560, 3), dtype=np.uint8)

        task = OfflineAbyssTask.__new__(OfflineAbyssTask)
        task._row_matches = lambda *_args: False
        task._row_has_floor_number = lambda _frame, _row, index: index < 2
        task._verify_floor_state = lambda _tower, index, *_args: COMPLETED if index == 0 else AVAILABLE
        task.log_info = lambda *_args: None
        task.screenshot = lambda *_args, **_kwargs: None

        self.assertEqual(task._scan_tower_floors(), (COMPLETED, AVAILABLE))

    def test_abyss_result_state_requires_exact_title_and_button_pair(self):
        box = lambda name: SimpleNamespace(name=name)
        self.assertEqual(
            abyss_result_state([box("挑战成功"), box("继续挑战"), box("返回深塔")]),
            "continue",
        )
        self.assertEqual(
            abyss_result_state([box("挑战成功"), box("再次挑战"), box("返回深塔")]),
            "tower_complete",
        )
        self.assertEqual(
            abyss_result_state([box("挑战失败"), box("再次挑战"), box("返回深塔")]),
            "failed",
        )
        self.assertIsNone(abyss_result_state([box("再次挑战"), box("返回深塔")]))

    def test_fight_selected_tower_continues_without_reforming_then_returns(self):
        events = []
        results = [
            ("continue", SimpleNamespace(name="继续挑战")),
            ("tower_complete", SimpleNamespace(name="返回深塔")),
        ]
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._click_start_challenge = lambda: events.append("start")
        task._prepare_challenge_map = lambda tower, floor: events.append(("map", tower, floor))
        task._run_floor_combat = lambda tower, floor: events.append(("combat", tower, floor))
        task._wait_abyss_result = lambda: results.pop(0)
        task.click_box = lambda box, **_kwargs: events.append(("click", box.name))
        task._wait_for_tower_screen = lambda: events.append("tower_screen")
        task._set_status = lambda *_args: None

        self.assertEqual(task._fight_selected_tower("残响之塔", 1), ("完成", 2))
        self.assertEqual(events.count("start"), 2)
        self.assertLess(events.index("start"), events.index(("map", "残响之塔", 2)))
        second_start = events.index("start", events.index("start") + 1)
        self.assertLess(second_start, events.index(("map", "残响之塔", 3)))
        self.assertEqual(
            [event for event in events if isinstance(event, tuple) and event[0] == "combat"],
            [("combat", "残响之塔", 2), ("combat", "残响之塔", 3)],
        )
        self.assertIn(("click", "继续挑战"), events)
        self.assertEqual(events[-2:], [("click", "返回深塔"), "tower_screen"])

    def test_click_start_challenge_skips_click_when_floor_is_already_loading(self):
        frame = object()
        events = []

        class OfflineAbyssTask(AutoAbyssTask):
            @property
            def frame(self):
                return frame

        task = OfflineAbyssTask.__new__(OfflineAbyssTask)

        def ocr(**kwargs):
            self.assertIs(kwargs.get("frame"), frame)
            if kwargs.get("match") == "环境特性":
                self.assertEqual(
                    (kwargs["x"], kwargs["y"], kwargs["to_x"], kwargs["to_y"]),
                    (0.02, 0.18, 0.34, 0.58),
                )
                return [SimpleNamespace(name="环境特性")]
            return []

        task.ocr = ocr
        task.wait_until = lambda condition, **_kwargs: condition()
        task.click_box = lambda *_args, **_kwargs: events.append("click")
        task.log_info = lambda message, **_kwargs: events.append(message)
        task.screenshot = lambda *_args, **_kwargs: events.append("screenshot")

        self.assertFalse(task._click_start_challenge())
        self.assertNotIn("click", events)
        self.assertNotIn("screenshot", events)

    def test_click_start_challenge_requires_team_page_and_clicks_its_button(self):
        frame = object()
        events = []
        calls = []
        button = SimpleNamespace(name="开启挑战")

        class OfflineAbyssTask(AutoAbyssTask):
            @property
            def frame(self):
                return frame

        task = OfflineAbyssTask.__new__(OfflineAbyssTask)

        def ocr(**kwargs):
            self.assertIs(kwargs.get("frame"), frame)
            calls.append((kwargs.get("match"), kwargs["x"], kwargs["y"], kwargs["to_x"], kwargs["to_y"]))
            if kwargs.get("match") == "编辑队伍":
                return [SimpleNamespace(name="编辑队伍")]
            if kwargs.get("match") == "开启挑战":
                return [button]
            return []

        task.ocr = ocr
        task.wait_until = lambda condition, **_kwargs: condition()
        task.click_box = lambda box, **_kwargs: events.append(box)
        task.screenshot = lambda *_args, **_kwargs: events.append("screenshot")

        self.assertTrue(task._click_start_challenge())
        self.assertEqual(events, [button])
        self.assertEqual(
            calls,
            [
                ("环境特性", 0.02, 0.18, 0.34, 0.58),
                ("编辑队伍", 0.01, 0.01, 0.22, 0.16),
                ("开启挑战", 0.75, 0.82, 0.98, 0.98),
            ],
        )

    def test_fight_selected_tower_failure_returns_and_skips_remaining_floors(self):
        events = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._click_start_challenge = lambda: events.append("start")
        task._prepare_challenge_map = lambda tower, floor: events.append(("map", tower, floor))
        task._run_floor_combat = lambda tower, floor: events.append(("combat", tower, floor))
        task._wait_abyss_result = lambda: ("failed", SimpleNamespace(name="返回深塔"))
        task.click_box = lambda box, **_kwargs: events.append(("click", box.name))
        task._wait_for_tower_screen = lambda: events.append("tower_screen")
        task._set_status = lambda *_args: None

        self.assertEqual(task._fight_selected_tower("深境之塔", 0), ("失败", 0))
        self.assertEqual(events.count(("combat", "深境之塔", 1)), 1)
        self.assertEqual(events[-2:], [("click", "返回深塔"), "tower_screen"])

    def test_fight_selected_tower_returns_to_reform_when_next_floor_exceeds_team_energy(self):
        events = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._click_start_challenge = lambda: events.append("start")
        task._prepare_challenge_map = lambda tower, floor: events.append(("map", tower, floor))
        task._run_floor_combat = lambda tower, floor: events.append(("combat", tower, floor))
        task._wait_abyss_result = lambda: ("continue", SimpleNamespace(name="继续挑战"))
        task._wait_exact_text = lambda *_args: SimpleNamespace(name="返回深塔")
        task.click_box = lambda box, **_kwargs: events.append(("click", box.name))
        task._wait_for_tower_screen = lambda: events.append("tower_screen")
        task._set_status = lambda *args: events.append(("status",) + args)

        self.assertEqual(task._fight_selected_tower("深境之塔", 0, 5), ("需要重新编队", 1))
        self.assertNotIn(("click", "继续挑战"), events)
        self.assertEqual(events[-2:], [("click", "返回深塔"), "tower_screen"])

    def test_floor_combat_treats_character_death_as_a_result_page_path(self):
        events = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._set_status = lambda *args: events.append(("status",) + args)
        task.walk_until_f = lambda **kwargs: events.append(("walk", kwargs["target_text"])) or True
        task.pick_f = lambda: events.append(("pick",))
        task.combat_once = lambda **kwargs: (_ for _ in ()).throw(CharDeadException("dead"))
        task.log_warning = lambda message: events.append(("warning", message))

        task._run_floor_combat("深境之塔", 2)

        self.assertIn(("walk", "开启挑战"), events)
        self.assertIn(("pick",), events)
        self.assertTrue(any(event[0] == "warning" for event in events))

    def test_abyss_death_handler_closes_popup_without_teleporting(self):
        events = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task.close_revive_popup = lambda: events.append("close")

        self.assertFalse(task.revive_action())
        self.assertEqual(events, ["close"])

    def test_exact_ocr_box_never_confuses_challenge_buttons(self):
        start = SimpleNamespace(name="挑战开始")
        enter = SimpleNamespace(name="开启挑战")
        quick = SimpleNamespace(name="快速 编队")
        self.assertIs(exact_ocr_box([enter, start], "挑战开始"), start)
        self.assertIs(exact_ocr_box([start, enter], "开启挑战"), enter)
        self.assertIs(exact_ocr_box([quick], "快速编队"), quick)
        self.assertIsNone(exact_ocr_box([enter], "挑战开始"))

    def test_character_grid_marks_bottom_row_incomplete(self):
        slots = character_card_slots()
        self.assertEqual(len(slots), 21)
        self.assertEqual(sum(1 for slot in slots if slot[-1]), 14)
        self.assertTrue(all(slot[-1] for slot in slots[:14]))
        self.assertTrue(all(not slot[-1] for slot in slots[14:]))

    def test_character_column_uses_card_centres(self):
        self.assertEqual(character_column_at(0.1527), 0)
        self.assertEqual(character_column_at(0.4081), 2)
        self.assertEqual(character_column_at(0.8842), 6)
        self.assertIsNone(character_column_at(0.99))

    def test_scroll_detection_uses_grid_or_scrollbar_change(self):
        before = np.zeros((144, 256, 3), dtype=np.uint8)
        after = before.copy()
        after[20:90, 30:180] = 255
        self.assertGreater(frame_change_score(before, after), 0.03)

        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
        frame[180:620, 2355:2370] = 220
        center = scroll_thumb_center(frame)
        self.assertIsNotNone(center)
        self.assertAlmostEqual(center, 400 / 1440, places=2)

    def test_scrollbar_geometry_scales_from_720p_through_4k(self):
        for width, height in (
            (1280, 720),
            (1600, 900),
            (1920, 1080),
            (2560, 1440),
            (3840, 2160),
        ):
            with self.subTest(width=width, height=height):
                frame = np.zeros((height, width, 3), dtype=np.uint8)
                left, right = int(0.920 * width), int(0.925 * width)
                top, bottom = int(0.20 * height), int(0.55 * height)
                frame[top:bottom, left:right] = 220
                self.assertAlmostEqual(scroll_thumb_center(frame), (top + bottom - 1) / 2 / height, places=2)
                self.assertFalse(is_single_page_character_list(frame))

    def test_floor_templates_scale_from_720p_through_4k(self):
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        template = task._template("completed")
        region = (0.340, FLOOR_ROWS[0][0], 0.390, FLOOR_ROWS[0][0] + 0.08)
        for width, height in (
            (1280, 720),
            (1600, 900),
            (1920, 1080),
            (2560, 1440),
            (3840, 2160),
        ):
            with self.subTest(width=width, height=height):
                frame = np.zeros((height, width, 3), dtype=np.uint8)
                scale = height / 1440
                interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
                scaled = cv2.resize(template, None, fx=scale, fy=scale, interpolation=interpolation)
                left = int(region[0] * width)
                top = int(region[1] * height)
                frame[top:top + scaled.shape[0], left:left + scaled.shape[1]] = cv2.cvtColor(
                    scaled, cv2.COLOR_GRAY2BGR
                )
                self.assertIsNotNone(task._find_template(frame, region, "completed", 0.99))

    def test_full_height_scroll_thumb_marks_a_single_page(self):
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
        frame[180:1170, 2355:2370] = 220

        self.assertTrue(is_single_page_character_list(frame))

        frame[620:1170, 2355:2370] = 0
        self.assertFalse(is_single_page_character_list(frame))

    def test_single_page_scan_skips_scroll_and_attempts_bottom_row(self):
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
        frame[180:1170, 2355:2370] = 220
        expected = [CharacterScanRecord("char_a", "A", 10, 90, 0.9, 1, 0)]
        calls = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._set_status = lambda *args: calls.append(("status", args))
        task.log_info = lambda message: calls.append(("log", message))
        task.screenshot = lambda *args, **kwargs: calls.append(("screenshot", args))
        task._recognize_character_screen = (
            lambda current, index, include_incomplete=False:
            calls.append(("recognize", current is frame, index, include_incomplete)) or expected
        )
        task._scroll_to_second_character_page = lambda _first: self.fail("single page must not scroll")

        self.assertEqual(task._scan_character_pages(frame), expected)
        self.assertIn(("recognize", True, 1, True), calls)

    def test_multi_page_scan_keeps_the_existing_second_screen_flow(self):
        first = np.zeros((1440, 2560, 3), dtype=np.uint8)
        first[180:620, 2355:2370] = 220
        second = first.copy()
        second[200:500, 300:800] = 255
        first_record = CharacterScanRecord("char_a", "A", 10, 90, 0.9, 1, 0)
        second_record = CharacterScanRecord("char_b", "B", 10, 80, 0.9, 2, 0)
        calls = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._set_status = lambda *args: calls.append(("status", args))
        task.log_info = lambda message: calls.append(("log", message))
        task.screenshot = lambda *args, **kwargs: calls.append(("screenshot", args))
        task._scroll_to_second_character_page = lambda current: second if current is first else None
        task._recognize_character_screen = (
            lambda current, index, include_incomplete=False:
            calls.append(("recognize", current is first, index, include_incomplete))
            or ([first_record] if current is first else [second_record])
        )

        self.assertEqual(task._scan_character_pages(first), [first_record, second_record])
        self.assertIn(("recognize", True, 1, False), calls)
        self.assertIn(("recognize", False, 2, False), calls)

    def test_multi_page_scroll_uses_scrollbar_drag_after_wheel_failures(self):
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
        frame[180:620, 2355:2370] = 220
        changed = frame.copy()
        changed[250:900, 300:1800] = 180
        frames = iter((frame.copy(), frame.copy(), changed))
        events = []
        warnings = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task.scroll_relative = lambda *args, **kwargs: events.append(("wheel", args))
        task.swipe_relative = lambda *args, **kwargs: events.append(("drag", args, kwargs))
        task.sleep = lambda *_args: None
        task.ensure_in_front = lambda: events.append(("front",))
        task._wait_stable_character_frame = lambda: next(frames)
        task.log_info = lambda message: events.append(("log", message))
        task.log_warning = warnings.append
        task.screenshot = lambda name, **kwargs: events.append(("screenshot", name, kwargs.get("frame")))

        self.assertIs(task._scroll_to_second_character_page(frame), changed)
        self.assertEqual(sum(event[0] == "front" for event in events), 3)
        self.assertEqual(sum(event[0] == "wheel" for event in events), 2)
        self.assertEqual(sum(event[0] == "drag" for event in events), 1)
        self.assertEqual(len(warnings), 2)
        self.assertEqual(sum(event[0] == "screenshot" for event in events), 4)

    def test_multi_page_scroll_failure_uses_sufficient_first_screen_records(self):
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
        frame[180:620, 2355:2370] = 220
        records = [
            CharacterScanRecord(f"char_{index}", str(index), energy, 90, 0.9, 1, index)
            for index, energy in enumerate((5, 6, 10))
        ]
        warnings = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._set_status = lambda *_args: None
        task.log_info = lambda *_args: None
        task.log_warning = warnings.append
        task.screenshot = lambda *_args, **_kwargs: None
        task._recognize_character_screen = lambda *_args, **_kwargs: records
        task._scroll_to_second_character_page = lambda _first: None

        self.assertEqual(task._scan_character_pages(frame, minimum_energy=5), records)
        self.assertEqual(task._character_page_count, 1)
        self.assertTrue(any("第一屏" in warning for warning in warnings))

    def test_multi_page_scroll_failure_stops_when_first_screen_cannot_form_team(self):
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
        frame[180:620, 2355:2370] = 220
        records = [
            CharacterScanRecord("char_a", "A", 5, 90, 0.9, 1, 0),
            CharacterScanRecord("char_b", "B", 4, 90, 0.9, 1, 1),
            CharacterScanRecord("char_c", "C", 10, 60, 0.9, 1, 2),
        ]
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._set_status = lambda *_args: None
        task.log_info = lambda *_args: None
        task.log_warning = lambda *_args: None
        task.screenshot = lambda *_args, **_kwargs: None
        task._recognize_character_screen = lambda *_args, **_kwargs: records
        task._scroll_to_second_character_page = lambda _first: None

        with self.assertRaisesRegex(Exception, "第一屏不足三名"):
            task._scan_character_pages(frame, minimum_energy=5)

    def test_parse_ocr_number_accepts_level_and_rejects_out_of_range(self):
        self.assertEqual(parse_ocr_number("Lv. 90", minimum=1, maximum=100), 90)
        self.assertEqual(parse_ocr_number("⚡10", minimum=0, maximum=99), 10)
        self.assertIsNone(parse_ocr_number("Lv. 900", minimum=1, maximum=100))
        self.assertIsNone(parse_ocr_number("unknown", minimum=0, maximum=99))

    def test_parse_energy_number_repairs_lightning_as_leading_one(self):
        self.assertEqual(parse_energy_number("10"), 10)
        self.assertEqual(parse_energy_number("18"), 8)
        self.assertEqual(parse_energy_number("19"), 9)
        self.assertEqual(parse_energy_number("110"), 10)
        self.assertIsNone(parse_energy_number("90"))

    def test_energy_digit_shape_disambiguates_zero_and_ten(self):
        zero = cv2.imread("tests/images/abyss_energy_0.png")
        ten = cv2.imread("tests/images/abyss_energy_10.png")

        for scale in (0.5, 0.75, 1.0, 1.5):
            interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
            with self.subTest(scale=scale):
                scaled_zero = cv2.resize(zero, None, fx=scale, fy=scale, interpolation=interpolation)
                scaled_ten = cv2.resize(ten, None, fx=scale, fy=scale, interpolation=interpolation)
                self.assertEqual(energy_digit_count(scaled_zero), 1)
                self.assertEqual(energy_digit_count(scaled_ten), 2)
        self.assertEqual(parse_energy_number("10", digit_count=1), 0)
        self.assertEqual(parse_energy_number("10", digit_count=2), 10)
        self.assertIsNone(parse_energy_number("10", digit_count=0))

    def test_slot_energy_ocr_uses_visual_digit_count(self):
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task.ocr = lambda *_args, **_kwargs: [SimpleNamespace(name="10")]
        corrections = []
        task.log_info = corrections.append
        task.log_warning = lambda *_args: None
        slot = character_card_slots()[0]
        _row, _column, x, y, width, height, _complete = slot

        for image_name, expected in (("abyss_energy_0.png", 0), ("abyss_energy_10.png", 10)):
            with self.subTest(image=image_name):
                frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
                crop = cv2.imread(f"tests/images/{image_name}")
                left = int((x + width * 0.50) * frame.shape[1])
                top = int((y + height * 0.52) * frame.shape[0])
                frame[top:top + crop.shape[0], left:left + crop.shape[1]] = crop

                self.assertEqual(task._read_slot_energy(frame, slot), expected)
        self.assertTrue(any("结果=0" in message for message in corrections))

    def test_slot_energy_unknown_shape_is_unavailable_and_saved(self):
        saved = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task.ocr = lambda *_args, **_kwargs: self.fail("ambiguous shape must not reach OCR")
        task.log_warning = lambda *_args: None
        task.screenshot = lambda name, **kwargs: saved.append((name, kwargs.get("frame")))

        self.assertIsNone(
            task._read_slot_energy(np.zeros((1440, 2560, 3), dtype=np.uint8), character_card_slots()[0])
        )
        self.assertEqual(saved[0][0], "abyss_energy_ambiguous")

    def test_merge_character_records_deduplicates_and_filters_strictly(self):
        records = [
            CharacterScanRecord("char_a", "A", 10, 90, 0.70, 1, 0),
            CharacterScanRecord("char_a", "A", 9, 90, 0.90, 2, 0),
            CharacterScanRecord("char_zero", "Zero", 0, 90, 0.95, 1, 1),
            CharacterScanRecord("char_60", "Sixty", 10, 60, 0.95, 1, 2),
            CharacterScanRecord("char_unknown", "Unknown", None, 90, 0.95, 1, 3),
        ]
        merged, available = merge_character_records(records)
        self.assertEqual(merged["char_a"].energy, 9)
        self.assertEqual([record.character_id for record in available], ["char_a"])

    def test_selection_state_allows_overlap_but_rejects_conflicts(self):
        same = [
            CharacterScanRecord("a", "A", 10, 90, .9, 1, 0, selection_number=1),
            CharacterScanRecord("a", "A", 10, 90, .8, 2, 7, selection_number=1),
        ]
        self.assertEqual(validate_selection_state(same), {1: "a"})
        with self.assertRaisesRegex(ValueError, "编号 1"):
            validate_selection_state(same + [
                CharacterScanRecord("b", "B", 10, 90, .9, 1, 1, selection_number=1),
            ])
        with self.assertRaisesRegex(ValueError, "角色 a"):
            validate_selection_state(same + [replace(same[0], selection_number=2)])

    def test_character_safe_click_avoids_card_labels(self):
        slot = character_card_slots()[0]
        _row, _column, x0, y0, width, height, _complete = slot
        x, y = character_safe_click(slot)
        self.assertAlmostEqual(x, x0 + width * 0.50)
        self.assertAlmostEqual(y, y0 + height * 0.35)

    def test_clear_all_selection_reuses_scan_and_checks_only_marker_regions(self):
        selected = [
            CharacterScanRecord("a", "A", 10, 90, .9, 1, 0),
            CharacterScanRecord("b", "B", 10, 90, .9, 2, 1),
        ]
        clicks = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._character_page_count = 2
        task._selection_records_all_pages = lambda: (_ for _ in ()).throw(
            AssertionError("the existing character scan must be reused")
        )
        task._selection_marker_locations_all_pages = lambda: []
        task._show_character_page = lambda _page: np.zeros((100, 100, 3), dtype=np.uint8)
        task._selection_marker_present = lambda _frame, _record: True
        task._verify_record_identity = lambda _frame, _record: True
        task.click_relative = lambda x, y, **kwargs: clicks.append((x, y, kwargs["name"]))
        task._wait_selection_marker = lambda _record, expected: expected is False
        task.screenshot = lambda *_args, **_kwargs: None

        self.assertTrue(task._clear_all_selection(selected))
        self.assertEqual([click[-1] for click in clicks], ["取消A", "取消B"])

    def test_select_planned_team_keeps_slot_order_across_pages(self):
        records = [
            CharacterScanRecord("a", "A", 10, 90, .9, 1, 0),
            CharacterScanRecord("b", "B", 10, 90, .9, 2, 1),
            CharacterScanRecord("c", "C", 10, 90, .9, 1, 2),
        ]
        events = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._show_character_page = lambda page: events.append(("show", page)) or np.zeros((100, 100, 3), dtype=np.uint8)
        task._verify_record_identity = lambda _frame, _record: True
        task.click_relative = lambda _x, _y, **kwargs: events.append(("click", kwargs["name"]))
        task._wait_selection_marker = lambda record, expected: events.append(("expect", record.character_id, expected)) or True
        task._verify_planned_selection_markers = lambda *_args: events.append(("final-local",)) or True
        task._clear_all_selection = lambda _records=None: events.append(("clear",))
        task.log_warning = lambda *_args: None
        task.log_info = lambda *_args: None
        task.screenshot = lambda *_args, **_kwargs: None
        plan = SimpleNamespace(executable=True, members=("a", "b", "c"))

        self.assertTrue(task._select_planned_team(plan, records))
        self.assertEqual([event for event in events if event[0] == "expect"], [
            ("expect", "a", True), ("expect", "b", True), ("expect", "c", True),
        ])
        self.assertEqual([event for event in events if event[0] == "show"], [
            ("show", 1), ("show", 2), ("show", 1),
        ])

    def test_select_planned_team_does_not_rescan_all_pages_after_local_success(self):
        records = [
            CharacterScanRecord("a", "A", 10, 90, .9, 1, 0),
            CharacterScanRecord("b", "B", 10, 90, .9, 1, 1),
            CharacterScanRecord("c", "C", 10, 90, .9, 1, 2),
        ]
        clicks = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._click_character_record = lambda record, number: clicks.append((record.character_id, number)) or True
        task._verify_planned_selection_markers = lambda *_args: True
        task._selection_records_all_pages = lambda: (_ for _ in ()).throw(
            AssertionError("successful local validation must not rescan all pages")
        )
        task.log_warning = lambda *_args: None
        task.log_info = lambda *_args: None
        task.screenshot = lambda *_args, **_kwargs: None
        plan = SimpleNamespace(executable=True, members=("a", "b", "c"))

        self.assertTrue(task._select_planned_team(plan, records))
        self.assertEqual(clicks, [("a", 1), ("b", 2), ("c", 3)])

    def test_final_selection_validation_checks_only_three_local_markers(self):
        records = [
            CharacterScanRecord("a", "A", 10, 90, .9, 1, 0),
            CharacterScanRecord("b", "B", 10, 90, .9, 2, 1),
            CharacterScanRecord("c", "C", 10, 90, .9, 1, 2),
        ]
        seen = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._show_character_page = lambda page: np.full((10, 10, 3), page, dtype=np.uint8)
        task._verify_record_identity = lambda _frame, _record: True
        task._selection_marker_present = lambda _frame, record: seen.append(record.character_id) or True
        task.log_info = lambda *_args: None
        plan = SimpleNamespace(members=("a", "b", "c"))

        self.assertTrue(task._verify_planned_selection_markers(plan, records))
        self.assertEqual(seen, ["a", "b", "c"])

    def test_select_planned_team_stops_when_number_state_is_unknown(self):
        records = [
            CharacterScanRecord("a", "A", 10, 90, .9, 1, 0),
            CharacterScanRecord("b", "B", 10, 90, .9, 1, 1),
            CharacterScanRecord("c", "C", 10, 90, .9, 1, 2),
        ]
        clicks = []
        clears = []
        screenshots = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._click_character_record = lambda record, number: clicks.append((record.character_id, number)) or False
        task._selection_marker_locations_all_pages = lambda: []
        task._clear_all_selection = lambda _records=None: clears.append(True)
        task.log_warning = lambda *_args: None
        task.screenshot = lambda name, **_kwargs: screenshots.append(name)
        plan = SimpleNamespace(executable=True, members=("a", "b", "c"))

        with self.assertRaisesRegex(Exception, "状态无法确认"):
            task._select_planned_team(plan, records)

        self.assertEqual(clicks, [("a", 1)])
        self.assertEqual(clears, [])
        self.assertEqual(screenshots, ["abyss_character_selection_unknown"])

    def test_plan_and_form_team_uses_qingxiao_core_then_verina(self):
        records = [
            CharacterScanRecord(Labels.char_qingxiao, "清宵", 10, 90, .9, 1, 0),
            CharacterScanRecord(Labels.char_denia, "达妮娅", 10, 90, .9, 1, 1),
            CharacterScanRecord(Labels.char_verina, "维里奈", 8, 90, .9, 1, 2),
        ]
        info = {}
        statuses = []
        actions = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._character_scan_results = {}
        task._runtime_status_account = "A3"
        task.info_set = lambda key, value: info.__setitem__(key, value)
        task._set_status = lambda stage, detail: statuses.append((stage, detail))
        task.log_info = lambda *_args, **_kwargs: None
        task._clear_all_selection = lambda _records=None: actions.append("clear")
        task._select_planned_team = lambda plan, source: actions.append(("select", plan.members, source))
        task._finish_team_formation = lambda: actions.append("finish")

        plan = task._plan_and_form_team(records)

        self.assertEqual(plan.members, (Labels.char_qingxiao, Labels.char_denia, Labels.char_verina))
        self.assertIn("清宵", info["编队计划"])
        self.assertIn("达妮娅", info["编队计划"])
        self.assertIn("维里奈替补千咲", info["编队计划"])
        self.assertEqual(actions[0], "clear")
        self.assertEqual(actions[1][0], "select")
        self.assertEqual(actions[2], "finish")
        self.assertEqual(statuses[-1][0], "编队完成")

    def test_plan_and_form_team_applies_remaining_tower_energy_to_every_member(self):
        records = [
            CharacterScanRecord(Labels.char_qingxiao, "清宵", 9, 90, .9, 1, 0),
            CharacterScanRecord(Labels.char_denia, "达妮娅", 10, 90, .9, 1, 1),
            CharacterScanRecord(Labels.char_chisa, "千咲", 10, 90, .9, 1, 2),
            CharacterScanRecord(Labels.char_galbrena, "嘉贝莉娜", 10, 90, .9, 1, 3),
            CharacterScanRecord(Labels.char_chouyuan, "仇远", 10, 90, .9, 1, 4),
            CharacterScanRecord(Labels.char_shorekeeper, "守岸人", 10, 90, .9, 1, 5),
        ]
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._character_scan_results = {}
        task.info_set = lambda *_args: None
        task._set_status = lambda *_args: None
        task.log_info = lambda *_args, **_kwargs: None
        task._clear_all_selection = lambda _records=None: None
        task._select_planned_team = lambda *_args: None
        task._finish_team_formation = lambda: None

        plan = task._plan_and_form_team(records, minimum_energy=10)

        self.assertEqual(
            plan.members,
            (Labels.char_galbrena, Labels.char_chouyuan, Labels.char_shorekeeper),
        )

    def test_run_towers_rescans_characters_once_per_new_tower_and_skips_completed(self):
        scans = {
            "残响之塔": (AVAILABLE, LOCKED),
            "深境之塔": (COMPLETED,),
            "回音之塔": (COMPLETED, AVAILABLE),
        }
        events = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task.config = {"Tower Priority": CENTER_TOWER_FIRST}
        task._set_status = lambda *args: events.append(("status",) + args)
        task._enter_and_scan_characters = (
            lambda tower, states: events.append(("scan_characters", tower, states)) or [tower]
        )
        task._plan_and_form_team = (
            lambda records, minimum_energy: events.append(("form", records[0], minimum_energy))
        )
        task._fight_selected_tower = (
            lambda tower, floor, energy: events.append(("fight", tower, floor, energy)) or ("完成", 1)
        )
        task._planned_team_energy = lambda *_args: 10

        outcomes = task._run_towers(scans)

        self.assertEqual(list(outcomes), ["深境之塔", "残响之塔", "回音之塔"])
        self.assertEqual(outcomes["深境之塔"], "已完成跳过")
        self.assertEqual(
            [event for event in events if event[0] == "scan_characters"],
            [
                ("scan_characters", "残响之塔", (AVAILABLE, LOCKED)),
                ("scan_characters", "回音之塔", (COMPLETED, AVAILABLE)),
            ],
        )
        self.assertIn(("form", "残响之塔", 1), events)
        self.assertIn(("form", "回音之塔", 2), events)

    def test_run_towers_reforms_center_team_after_two_floors(self):
        scans = {
            "残响之塔": (COMPLETED,),
            "深境之塔": (AVAILABLE, LOCKED, LOCKED, LOCKED),
            "回音之塔": (COMPLETED,),
        }
        events = []
        fights = iter((("需要重新编队", 2), ("完成", 2)))
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task.config = {"Tower Priority": CENTER_TOWER_FIRST}
        task._set_status = lambda *_args: None
        task._enter_and_scan_characters = (
            lambda tower, states: events.append(("scan", tower, states)) or [tower]
        )
        task._plan_and_form_team = (
            lambda records, minimum_energy: events.append(("form", minimum_energy))
            or SimpleNamespace(members=("a", "b", "c"))
        )
        task._planned_team_energy = lambda *_args: 10
        task._fight_selected_tower = (
            lambda tower, floor, energy: events.append(("fight", floor, energy)) or next(fights)
        )

        outcomes = task._run_towers(scans)

        self.assertEqual(outcomes["深境之塔"], "完成（4层）")
        self.assertEqual([event for event in events if event[0] == "form"], [("form", 5), ("form", 5)])
        self.assertEqual([event for event in events if event[0] == "fight"], [("fight", 0, 10), ("fight", 2, 10)])

    def test_run_towers_returns_safely_and_continues_after_team_shortage(self):
        scans = {
            "残响之塔": (AVAILABLE,),
            "深境之塔": (COMPLETED,),
            "回音之塔": (AVAILABLE,),
        }
        events = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task.config = {"Tower Priority": "两侧塔优先"}
        task._set_status = lambda *_args: None
        task._enter_and_scan_characters = lambda tower, _states: [tower]

        def form(records, minimum_energy):
            if records[0] == "残响之塔":
                raise AbyssTeamUnavailable("体力不足")
            events.append(("form", records[0]))

        task._plan_and_form_team = form
        task._return_from_team_to_towers = lambda: events.append(("return",))
        task._planned_team_energy = lambda *_args: 10
        task._fight_selected_tower = lambda tower, _floor, _energy: ("完成", 1)

        outcomes = task._run_towers(scans)

        self.assertEqual(outcomes["残响之塔"], "体力或角色不足")
        self.assertEqual(outcomes["回音之塔"], "完成（1层）")
        self.assertEqual(events, [("return",), ("form", "回音之塔")])

    def test_run_towers_never_scans_forms_or_fights_an_unknown_tower(self):
        scans = {
            "残响之塔": (UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN),
            "深境之塔": (COMPLETED,),
            "回音之塔": (COMPLETED,),
        }
        events = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task.config = {"Tower Priority": "两侧塔优先"}
        task._set_status = lambda *args: events.append(("status",) + args)
        task._enter_and_scan_characters = lambda *_args: events.append("scan")
        task._plan_and_form_team = lambda *_args, **_kwargs: events.append("form")
        task._fight_selected_tower = lambda *_args: events.append("fight")

        outcomes = task._run_towers(scans)

        self.assertEqual(outcomes["残响之塔"], "状态不确定，安全跳过")
        self.assertNotIn("scan", events)
        self.assertNotIn("form", events)
        self.assertNotIn("fight", events)

    def test_plan_and_form_team_stops_before_clicking_when_under_three(self):
        records = [
            CharacterScanRecord(Labels.char_qingxiao, "清宵", 10, 90, .9, 1, 0),
            CharacterScanRecord(Labels.char_denia, "达妮娅", 10, 90, .9, 1, 1),
        ]
        statuses = []
        actions = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._character_scan_results = {}
        task.info_set = lambda *_args: None
        task._set_status = lambda stage, detail: statuses.append((stage, detail))
        task.log_info = lambda *_args, **_kwargs: None
        task._clear_all_selection = lambda _records=None: actions.append("clear")
        task._select_planned_team = lambda *_args: actions.append("select")
        task._finish_team_formation = lambda: actions.append("finish")

        with self.assertRaisesRegex(Exception, "可用角色不足三人"):
            task._plan_and_form_team(records)

        self.assertEqual(actions, [])
        self.assertEqual(statuses[-1][0], "无法组成三人队")

    def test_finish_team_formation_clicks_only_complete(self):
        requested = []
        clicked = []
        boxes = {text: SimpleNamespace(name=text) for text in ("完成", "编辑队伍", "开启挑战")}
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._wait_exact_text_or_fail = lambda text, *_args: requested.append(text) or boxes[text]
        task.click_box = lambda box, **_kwargs: clicked.append(box.name)

        self.assertTrue(task._finish_team_formation())
        self.assertEqual(requested, ["完成", "编辑队伍", "开启挑战"])
        self.assertEqual(clicked, ["完成"])

    def test_clear_character_scan_only_removes_current_account(self):
        from src.task.AutoAbyssTask import AutoAbyssTask

        task = object.__new__(AutoAbyssTask)
        task._runtime_status_account = "A3"
        task._character_scan_results = {"A3": {"available": []}, "A4": {"available": []}}
        task.info_set = lambda *_args: None
        self.assertTrue(task.clear_current_character_scan())
        self.assertNotIn("A3", task._character_scan_results)
        self.assertIn("A4", task._character_scan_results)


if __name__ == "__main__":
    unittest.main()
