# -*- coding: utf-8 -*-
import unittest
from dataclasses import replace
from types import SimpleNamespace

import cv2
import numpy as np
from ok.feature.FeatureSet import FeatureSet

from src.Labels import Labels
from src.task.AutoAbyssTask import (
    AVAILABLE,
    AutoAbyssTask,
    CharacterScanRecord,
    best_template_match,
    COMPLETED,
    LOCKED,
    aggregate_floor_states,
    character_column_at,
    character_card_slots,
    character_safe_click,
    exact_ocr_box,
    first_available_floor,
    frame_change_score,
    match_travel_button,
    merge_character_records,
    classify_rover_element_crop,
    parse_energy_number,
    parse_ocr_number,
    parse_selection_number,
    is_single_page_character_list,
    scroll_thumb_center,
    tower_click_point,
    validate_selection_state,
)
from src.task.abyss_team_planner import ROVER_AERO, ROVER_HAVOC, ROVER_SPECTRO, ROVER_UNKNOWN


class TestAutoAbyssTask(unittest.TestCase):
    def test_qingxiao_character_scan_at_1440p_and_1080p(self):
        class OfflineAbyssTask(AutoAbyssTask):
            @property
            def height(self):
                return self._offline_height

            @property
            def width(self):
                return self._offline_width

        for width, height, selected in ((2560, 1440, False), (1920, 1080, True)):
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
                target_height = max(96, int(height * 0.105))
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
                        0.7,
                        (40, 190, 255),
                        2,
                    )

                records = task._recognize_character_screen(frame, 1)

                self.assertEqual(len(records), 1)
                self.assertEqual(records[0].character_id, Labels.char_qingxiao)
                self.assertEqual(records[0].energy, 10)
                self.assertEqual(records[0].level, 90)
                self.assertTrue(records[0].available)
                self.assertEqual(records[0].selection_number, 1 if selected else None)

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

    def test_multi_page_scroll_failure_remains_fatal(self):
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
        frame[180:620, 2355:2370] = 220
        warnings = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task.scroll_relative = lambda *args, **kwargs: None
        task.sleep = lambda *_args: None
        task.ensure_in_front = lambda: None
        task._wait_stable_character_frame = lambda: frame.copy()
        task.log_warning = warnings.append
        task.screenshot = lambda *args, **kwargs: None

        with self.assertRaisesRegex(Exception, "角色列表滚动未生效"):
            task._scroll_to_second_character_page(frame)
        self.assertEqual(len(warnings), 2)

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

    def test_clear_all_selection_clicks_existing_numbers_before_rescan(self):
        selected = [
            CharacterScanRecord("a", "A", 10, 90, .9, 1, 0, selection_number=1),
            CharacterScanRecord("b", "B", 10, 90, .9, 2, 1, selection_number=2),
        ]
        scans = [selected, [replace(item, selection_number=None) for item in selected]]
        clicks = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._selection_records_all_pages = lambda: scans.pop(0)
        task._show_character_page = lambda _page: np.zeros((100, 100, 3), dtype=np.uint8)
        task._verify_record_identity = lambda _frame, _record: True
        task.click_relative = lambda x, y, **kwargs: clicks.append((x, y, kwargs["name"]))
        task._wait_selection_number = lambda _record, expected: expected is None
        task.screenshot = lambda *_args, **_kwargs: None

        self.assertTrue(task._clear_all_selection())
        self.assertEqual([click[-1] for click in clicks], ["取消A", "取消B"])

    def test_select_planned_team_keeps_slot_order_across_pages(self):
        records = [
            CharacterScanRecord("a", "A", 10, 90, .9, 1, 0),
            CharacterScanRecord("b", "B", 10, 90, .9, 2, 1),
            CharacterScanRecord("c", "C", 10, 90, .9, 1, 2),
        ]
        final = [replace(record, selection_number=index) for index, record in enumerate(records, start=1)]
        events = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._show_character_page = lambda page: events.append(("show", page)) or np.zeros((100, 100, 3), dtype=np.uint8)
        task._verify_record_identity = lambda _frame, _record: True
        task.click_relative = lambda _x, _y, **kwargs: events.append(("click", kwargs["name"]))
        task._wait_selection_number = lambda record, expected: events.append(("expect", record.character_id, expected)) or True
        task._selection_records_all_pages = lambda: final
        task._clear_all_selection = lambda: events.append(("clear",))
        task.log_warning = lambda *_args: None
        task.screenshot = lambda *_args, **_kwargs: None
        plan = SimpleNamespace(executable=True, members=("a", "b", "c"))

        self.assertTrue(task._select_planned_team(plan, records))
        self.assertEqual([event for event in events if event[0] == "expect"], [
            ("expect", "a", 1), ("expect", "b", 2), ("expect", "c", 3),
        ])
        self.assertEqual([event for event in events if event[0] == "show"], [
            ("show", 1), ("show", 2), ("show", 1),
        ])

    def test_select_planned_team_retries_once_after_cleaning(self):
        records = [
            CharacterScanRecord("a", "A", 10, 90, .9, 1, 0),
            CharacterScanRecord("b", "B", 10, 90, .9, 1, 1),
            CharacterScanRecord("c", "C", 10, 90, .9, 1, 2),
        ]
        final = [replace(record, selection_number=index) for index, record in enumerate(records, start=1)]
        clicks = []
        clears = []
        task = AutoAbyssTask.__new__(AutoAbyssTask)

        def click_record(record, number):
            clicks.append((record.character_id, number))
            return len(clicks) > 1

        task._click_character_record = click_record
        task._selection_records_all_pages = lambda: final
        task._clear_all_selection = lambda: clears.append(True)
        task.log_warning = lambda *_args: None
        task.screenshot = lambda *_args, **_kwargs: None
        plan = SimpleNamespace(executable=True, members=("a", "b", "c"))

        self.assertTrue(task._select_planned_team(plan, records))
        self.assertEqual(len(clears), 1)
        self.assertEqual(clicks, [("a", 1), ("a", 1), ("b", 2), ("c", 3)])

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
        task._clear_all_selection = lambda: actions.append("clear")
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
        task._clear_all_selection = lambda: actions.append("clear")
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
