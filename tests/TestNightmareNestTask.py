import unittest
import re
import json

import numpy as np

from src.task.BaseCombatTask import CombatStateUnknown, CharDeadException
from src.task.NightmareNestTask import NestTarget, NightmareNestTask


class FakeBox:

    def __init__(self, name, x=0, y=0, width=20, height=10):
        self.name = name
        self.x = x
        self.y = y
        self.width = width
        self.height = height


class TestNightmareNestTask(unittest.TestCase):

    def test_recheck_nest_combat_uses_live_target_and_matching_progress(self):
        nest = NestTarget(FakeBox('nest'), 'go_nest:41:10', current=35, total=41)
        for target, count, expected in (
                (True, [], 'combat'),
                (False, [FakeBox('35/41')], 'combat'),
                (False, [FakeBox('41/41')], 'complete')):
            with self.subTest(target=target, count=count):
                task = NightmareNestTask.__new__(NightmareNestTask)
                task.count_re = re.compile(r"(\d{1,2})/(\d{1,2})")
                task.require_game_frame = lambda: object()
                task.has_target = lambda: target
                task.check_health_bar = lambda: False
                task.ocr = lambda *args, **kwargs: count
                self.assertEqual(expected, task._recheck_nest_combat(nest, timeout=0))

    def test_recheck_nest_combat_unknown_is_not_completion(self):
        task = NightmareNestTask.__new__(NightmareNestTask)
        task.count_re = re.compile(r"(\d{1,2})/(\d{1,2})")
        task.require_game_frame = lambda: object()
        task.has_target = lambda: False
        task.check_health_bar = lambda: False
        task.ocr = lambda *args, **kwargs: []
        self.assertEqual('unknown', task._recheck_nest_combat(
            NestTarget(FakeBox('nest'), 'go_nest:41:10', current=35, total=41), timeout=0))

    def test_combat_unknown_retries_same_nest_only_once(self):
        task = NightmareNestTask.__new__(NightmareNestTask)
        task._capture_mode = False
        task._capture_success = False
        task.click = lambda *args, **kwargs: None
        task.wait_book_target_state = lambda *args, **kwargs: FakeBox('team_start_challenge')
        task.click_team_challenge = lambda: None
        task.wait_in_team_and_world = lambda *args, **kwargs: True
        task.sleep = lambda *args, **kwargs: None
        task.combat_once = lambda **kwargs: (_ for _ in ()).throw(CombatStateUnknown('transient'))
        task._recheck_nest_combat = lambda nest: 'combat'
        task.target_enemy = lambda **kwargs: True
        task.log_warning = lambda *args, **kwargs: None
        task.screenshot = lambda *args, **kwargs: None
        task.require_game_frame = lambda: object()

        with self.assertRaises(CombatStateUnknown):
            task.combat_nest(NestTarget(FakeBox('nest'), 'go_nest:41:10', current=35, total=41))

    def test_nest_target_keeps_display_name_and_ordinal(self):
        target = NestTarget(
            object(),
            'go_nest:41:10',
            display_name='落渊南丘残象聚落',
            ordinal=1,
        )
        self.assertEqual('落渊南丘残象聚落', target.display_name)
        self.assertEqual(1, target.ordinal)

    def test_nest_is_checked_before_nightmare_changes_book_scroll(self):
        task = NightmareNestTask.__new__(NightmareNestTask)
        task.config = {'Which to Farm': ['Nightmare Purification', 'Tacet Discord Nest']}
        task._init_queue()
        self.assertEqual(['go_nest', 'go_nest_scroll', 'go_nightmare', 'go_nightmare_scroll'],
                         [action.__name__ for action in task.queues])

    def test_capture_success_clears_combat_before_post_combat_waits(self):
        task = NightmareNestTask.__new__(NightmareNestTask)
        task._capture_mode = True
        task._in_combat = True
        picked = []

        task.pick_f = lambda handle_claim=True: picked.append(handle_claim)
        task.has_echo_notification = lambda: True

        def reset_to_false(reason=''):
            task._in_combat = False
            task.out_of_combat_reason = reason
            return False

        task.reset_to_false = reset_to_false

        self.assertFalse(task.on_combat_check())
        self.assertEqual([False], picked)
        self.assertFalse(task._in_combat)
        self.assertEqual('echo captured', task.out_of_combat_reason)

    def test_combat_nest_rechecks_after_pickup_in_team_and_open_world(self):
        for feature_name in ('team_start_challenge', 'fast_travel_custom'):
            with self.subTest(feature_name=feature_name):
                task = NightmareNestTask.__new__(NightmareNestTask)
                task._capture_mode = False
                task._capture_success = False
                combat_calls = []
                pickup_calls = []
                combat_results = iter([True, False])

                task.click = lambda *args, **kwargs: None
                task.wait_book_target_state = lambda *args, **kwargs: FakeBox(feature_name)
                task.click_team_challenge = lambda: None
                task.wait_in_team_and_world = lambda *args, **kwargs: True
                task._travel_to_nest_or_skip = lambda nest: True
                task.sleep = lambda *args, **kwargs: None
                task.find_f_with_text = lambda: False
                task.run_until = lambda *args, **kwargs: None
                task.combat_once = lambda **kwargs: combat_calls.append(kwargs) or True
                task.walk_find_echo = lambda **kwargs: pickup_calls.append(kwargs) or True
                task.wait_combat = lambda **kwargs: next(combat_results)
                task.log_info = lambda *args, **kwargs: None
                task.send_key = lambda *args, **kwargs: None
                task.esc_world_confirm = lambda *args, **kwargs: None

                task.combat_nest(FakeBox('nest'))

                self.assertEqual([10, 1], [call['wait_combat_time'] for call in combat_calls])
                self.assertEqual(2, len(pickup_calls))

    def test_capture_mode_does_not_check_combat_after_pickup(self):
        task = NightmareNestTask.__new__(NightmareNestTask)
        task._capture_mode = True
        task.wait_combat = lambda **kwargs: self.fail('capture mode should leave after obtaining an echo')

        self.assertFalse(task._should_continue_combat_after_pickup())

    def test_combat_nest_recovers_to_world_after_failed_revive(self):
        task = NightmareNestTask.__new__(NightmareNestTask)
        task._capture_mode = False
        task._capture_success = False
        recoveries = []

        task.click = lambda *args, **kwargs: None
        task.wait_book_target_state = lambda *args, **kwargs: FakeBox('fast_travel_custom')
        task._travel_to_nest_or_skip = lambda nest: True
        task.sleep = lambda *args, **kwargs: None
        task.find_f_with_text = lambda: False
        task.run_until = lambda *args, **kwargs: None
        task.combat_once = lambda **kwargs: (_ for _ in ()).throw(CharDeadException('dead'))
        task.ensure_main = lambda **kwargs: recoveries.append(kwargs)
        task.log_info = lambda *args, **kwargs: None
        task.log_warning = lambda *args, **kwargs: None

        task.combat_nest(NestTarget(FakeBox('nest'), 'go_nest:24:45',
                                    display_name='陷足流川残象聚落', current=20, total=24))

        self.assertEqual([{'time_out': 180}], recoveries)

    def test_unreachable_nest_is_cached_when_travel_does_not_enter_world(self):
        task = NightmareNestTask.__new__(NightmareNestTask)
        task._unreachable_nests = set()
        backs = []
        clicks = []
        wait_timeouts = []
        world_waits = []
        travel = FakeBox('fast_travel_custom')

        wait_results = iter([travel, False])
        task.wait_until = lambda *args, **kwargs: wait_timeouts.append(kwargs['time_out']) or next(wait_results)
        task.find_one = lambda name, **kwargs: travel if name == travel.name else None
        task.click = lambda box, **kwargs: clicks.append((box, kwargs))
        task.wait_in_team_and_world = lambda *args, **kwargs: world_waits.append(kwargs) or False
        task.back = lambda *args, **kwargs: backs.append(kwargs)
        task.log_info = lambda *args, **kwargs: None

        target = NestTarget(object(), 'go_nightmare:36:0.205')

        self.assertFalse(task._travel_to_nest_or_skip(target))
        self.assertIn(target.cache_key, task._unreachable_nests)
        self.assertEqual([3, 5], wait_timeouts)
        self.assertEqual([(travel, {'after_sleep': 1})], clicks)
        self.assertEqual([{'time_out': 10, 'raise_if_not_found': False}], world_waits)
        self.assertEqual([{'after_sleep': 1}], backs)

    def test_travel_allows_slow_button_disappearance_before_world_wait(self):
        task = NightmareNestTask.__new__(NightmareNestTask)
        task._unreachable_nests = set()
        travel = FakeBox('gray_teleport')
        feature_checks = iter([travel, travel, None])
        wait_calls = []
        world_waits = []

        def wait_until(callback, **kwargs):
            wait_calls.append(kwargs['time_out'])
            if len(wait_calls) == 1:
                return callback()
            callback()
            return callback()

        task.wait_until = wait_until
        task.find_one = lambda name, **kwargs: next(feature_checks) if name == travel.name else None
        task.click = lambda *args, **kwargs: None
        task.wait_in_team_and_world = lambda *args, **kwargs: world_waits.append(kwargs) or True

        self.assertTrue(task._travel_to_nest_or_skip(NestTarget(object(), 'go_nest:48:28')))
        self.assertNotIn('go_nest:48:28', task._unreachable_nests)
        self.assertEqual([3, 5], wait_calls)
        self.assertEqual([{'time_out': 120, 'raise_if_not_found': False}], world_waits)

    def test_travel_waits_up_to_120_seconds_for_loading(self):
        task = NightmareNestTask.__new__(NightmareNestTask)
        task._unreachable_nests = set()
        travel = FakeBox('fast_travel_custom')
        world_waits = []

        wait_results = iter([travel, True])
        task.wait_until = lambda *args, **kwargs: next(wait_results)
        task.find_one = lambda *args, **kwargs: None
        task.click = lambda *args, **kwargs: None
        task.wait_in_team_and_world = lambda *args, **kwargs: world_waits.append(kwargs) or True

        self.assertTrue(task._travel_to_nest_or_skip(NestTarget(object(), 'go_nest:36:10')))
        self.assertEqual([{'time_out': 120, 'raise_if_not_found': False}], world_waits)

    def test_open_book_delegates_one_budget_to_shared_navigation(self):
        from unittest.mock import Mock
        task = NightmareNestTask.__new__(NightmareNestTask)
        task.openF2Book = Mock(return_value=FakeBox('gray_book_boss'))
        self.assertEqual(task._open_book_with_retry('gray_book_boss').name, 'gray_book_boss')
        task.openF2Book.assert_called_once_with('gray_book_boss')

    def test_open_book_failure_does_not_restart_navigation_or_escape(self):
        from unittest.mock import Mock
        task = NightmareNestTask.__new__(NightmareNestTask)
        task.openF2Book = Mock(side_effect=RuntimeError('persistent book failure'))
        task.ensure_main = Mock()
        with self.assertRaisesRegex(RuntimeError, 'persistent'):
            task._open_book_with_retry('gray_book_boss')
        task.openF2Book.assert_called_once_with('gray_book_boss')
        task.ensure_main.assert_not_called()

    def test_find_nest_skips_cached_unreachable_row(self):
        task = NightmareNestTask.__new__(NightmareNestTask)
        task.config = {}
        task.count_re = re.compile(r"(\d{1,2})/(\d{1,2})")
        task.queues = [lambda: None]
        task._unreachable_nests = {'<lambda>:36:10'}
        task.log_info = lambda *args, **kwargs: None
        task.height_of_screen = lambda value: 1000 * value
        task.width_of_screen = lambda value: 2000 * value
        ocr_calls = []

        count_boxes = [
            FakeBox('0/36', y=200),
            FakeBox('0/36', y=300),
        ]

        def ocr(*args, **kwargs):
            ocr_calls.append((args, kwargs))
            return count_boxes

        task.ocr = ocr

        target = task.find_nest()

        self.assertIsInstance(target, NestTarget)
        self.assertIs(target.box, count_boxes[1])
        self.assertEqual('<lambda>:36:15', target.cache_key)
        self.assertEqual(1800, target.box.x)
        self.assertEqual(1, len(ocr_calls))

    def test_nightmare_settlements_are_empty_by_default_and_use_game_names(self):
        from src.nightmare_nests import NIGHTMARE_NAMES
        from src.task.NightmareNestTask import FARM_NIGHTMARE_SETTLEMENTS
        task = NightmareNestTask.__new__(NightmareNestTask)
        task.config = {FARM_NIGHTMARE_SETTLEMENTS: [NIGHTMARE_NAMES[1]]}
        task.count_re = re.compile(r"(\d{1,2})/(\d{1,2})")
        task.queues = [task.go_nightmare]
        task._unreachable_nests = set()
        task.log_info = lambda *args, **kwargs: None
        task.height_of_screen = lambda value: 1000 * value
        task.width_of_screen = lambda value: 2000 * value
        task.require_game_frame = lambda: np.zeros((2, 2, 3), dtype=np.uint8)
        task._reset_progress_tracking()
        boxes = [FakeBox('0/36', y=200), FakeBox('千殁沉岛梦魇聚落', y=260),
                 FakeBox('0/36', y=280), FakeBox('前往', x=1800, y=290),
                 FakeBox('三王峰梦魇聚落', y=400), FakeBox('0/36', y=420),
                 FakeBox('前往', x=1800, y=430)]
        task.ocr = lambda *args, **kwargs: boxes

        target = task.find_nest()

        self.assertEqual(target.display_name, '三王峰梦魇聚落')
        self.assertIs(target.box, boxes[-1])

    def test_nightmare_partial_and_duplicate_titles_are_not_entries(self):
        task = NightmareNestTask.__new__(NightmareNestTask)
        task.count_re = re.compile(r'(\d{1,2})/(\d{1,2})')
        task.height_of_screen = lambda value: 1000 * value
        task.width_of_screen = lambda value: 2000 * value
        task._nightmare_filter_open = lambda frame: False
        name = '三王峰梦魇聚落'
        for boxes in ([FakeBox('0/36', y=200), FakeBox('前往', x=1800, y=210)],
                      [FakeBox(name,y=300),FakeBox('0/36',y=320),FakeBox('前往',x=1800,y=330),
                       FakeBox(name,y=500),FakeBox('0/36',y=520),FakeBox('前往',x=1800,y=530)]):
            task.ocr = lambda *args, **kwargs: boxes
            self.assertEqual({}, task._nightmare_rows(object()))

    def test_game_mengmo_names_keep_legacy_selection_and_progress_keys(self):
        from src.nightmare_nests import NIGHTMARE_NAMES, normalize_nest_text
        from src.task.NightmareNestTask import FARM_NIGHTMARE_SETTLEMENTS
        for current in (0, 36):
            task = NightmareNestTask.__new__(NightmareNestTask)
            task.config = {FARM_NIGHTMARE_SETTLEMENTS: [NIGHTMARE_NAMES[1]]}
            task.queues = [task.go_nightmare]
            task.count_re = re.compile(r'(\d{1,2})/(\d{1,2})')
            task.height_of_screen = lambda value: 1080 * value
            task.width_of_screen = lambda value: 1920 * value
            task.require_game_frame = lambda: np.zeros((2, 2, 3), dtype=np.uint8)
            task._close_nightmare_filter = lambda frame: None
            task._nightmare_filter_open = lambda frame: False
            task._reset_progress_tracking()
            task._unreachable_nests = set()
            button = FakeBox('直接挑战', x=1680, y=520)
            task.ocr = lambda *a, **k: [FakeBox('三王峰梦魔聚落', x=690, y=468),
                                       FakeBox(f'已击败残象{current}/36', x=700, y=520), button]
            target = task._find_nightmare_nest()
            if current == 0:
                self.assertEqual('nightmare:三王峰梦魇聚落', target.cache_key)
                self.assertIs(button, target.box)
            else:
                self.assertIsNone(target)
                self.assertIn('三王峰梦魇聚落', task._nest_completed)
            self.assertEqual([NIGHTMARE_NAMES[1]], task.config[FARM_NIGHTMARE_SETTLEMENTS])
        for name in NIGHTMARE_NAMES:
            self.assertEqual(name, normalize_nest_text(name.replace('梦魇', '梦魔')))
        self.assertEqual('梦魔亚当·重锤', normalize_nest_text('梦魔亚当·重锤'))

    def nightmare_scan_task(self, boxes, frame=None):
        from unittest.mock import Mock
        task = NightmareNestTask.__new__(NightmareNestTask)
        task.config = {'Which to Farm': ['Nightmare Purification'],
                       'Nightmare Settlements to Farm': ['穗波市梦魇聚落']}
        task.count_re = re.compile(r'(\d{1,2})/(\d{1,2})')
        task.queues = [task.go_nightmare]
        task._unreachable_nests = set()
        task._reset_progress_tracking()
        task.height_of_screen = lambda value: 1080 * value
        task.width_of_screen = lambda value: 1920 * value
        task.require_game_frame = Mock(return_value=frame if frame is not None else
                                       np.zeros((2, 2, 3), dtype=np.uint8))
        task._close_nightmare_filter = Mock()
        task._nightmare_filter_open = Mock(return_value=False)
        task.ocr = Mock(return_value=boxes)
        task.screenshot = Mock()
        task.log_warning = Mock()
        return task

    def test_a3_stable_first_row_keeps_selection_and_writes_no_evidence_on_success(self):
        # OCR text/coordinates from the reviewed 10:44:19 stable frame.
        boxes = [FakeBox('穂波市梦魔聚落', 889, 304, 186, 29),
                 FakeBox('直接挑战', 1669, 335, 102, 39),
                 FakeBox('已击败残象：0/36', 890, 375, 196, 29)]
        task = self.nightmare_scan_task(boxes)
        target = task._find_nightmare_nest()
        self.assertEqual(('穗波市梦魇聚落', 0, 36),
                         (target.display_name, target.current, target.total))
        self.assertIs(boxes[1], target.box)
        boxes[-1].name = '已击败残象：36/36'
        self.assertIsNone(task._find_nightmare_nest())
        task._assert_selected_targets_complete()
        task.screenshot.assert_not_called()
        task.log_warning.assert_not_called()
        self.assertEqual(2, task.ocr.call_count)

    def test_missing_target_saves_only_latest_top_and_bottom_actual_scans(self):
        frames = [np.full((2, 2, 3), value, dtype=np.uint8) for value in (1, 2, 3)]
        boxes = [FakeBox('穂波市梦魔聚落', 889, 304, 186, 29),
                 FakeBox('直接挑战', 1669, 335, 102, 39),
                 FakeBox('已击败残象：0/41', 890, 375, 196, 29)]
        task = self.nightmare_scan_task(boxes)
        for action, frame in zip((task.go_nightmare, task.go_nightmare, task.go_nightmare_scroll), frames):
            task.queues = [action]
            task.require_game_frame.return_value = frame
            self.assertIsNone(task._find_nightmare_nest())
        frames[1][:] = 99
        task.queues = []
        task.screenshot.assert_not_called()
        task.log_warning.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, '穗波市'):
            task._assert_selected_targets_complete()
        self.assertEqual(3, task.ocr.call_count)
        self.assertEqual(2, task.screenshot.call_count)
        saved = [call.kwargs['frame'] for call in task.screenshot.call_args_list]
        self.assertTrue(np.all(saved[0] == 2))
        self.assertTrue(np.all(saved[1] == 3))
        metadata = json.loads(task.log_warning.call_args_list[0].args[0].split('unconfirmed ', 1)[1])
        self.assertEqual(['穗波市梦魇聚落'], metadata['missing'])
        self.assertTrue(metadata['task_source'].endswith('NightmareNestTask.py'))
        self.assertTrue(metadata['normalizer_source'].endswith('nightmare_nests.py'))
        detail = json.loads(task.log_warning.call_args_list[1].args[0].split('go_nightmare ', 1)[1])
        self.assertEqual('progress_total_not_36', detail['rows'][0]['result'])
        self.assertEqual('穗波市梦魇聚落', detail['rows'][0]['normalized'])
        self.assertEqual([890, 375, 196, 29], detail['ocr'][-1]['box'])
        self.assertEqual('已击败残象：0/41', detail['ocr'][-1]['text'])
        task._reset_progress_tracking()
        self.assertEqual({}, task._nightmare_scans)

    def test_rejected_nightmare_button_records_actual_text_and_position_reason(self):
        for button, reason in ((FakeBox('直接挑站', 1669, 335), 'button_text_not_matched'),
                               (FakeBox('直接挑战', 1500, 335), 'left_of_button_region')):
            with self.subTest(reason=reason):
                task = self.nightmare_scan_task([
                    FakeBox('穂波市梦魔聚落', 889, 304), button,
                    FakeBox('已击败残象：0/36', 890, 375)])
                with self.assertRaisesRegex(RuntimeError, '完整入口按钮未确认'):
                    task._find_nightmare_nest()
                task.screenshot.assert_called_once()
                self.assertEqual(1, task.ocr.call_count)
                detail = json.loads(task.log_warning.call_args_list[-1].args[0].split('go_nightmare ', 1)[1])
                self.assertEqual('button_not_unique', detail['rows'][0]['result'])
                self.assertEqual(reason, detail['rows'][0]['buttons'][0]['result'])
                self.assertEqual(button.name, detail['rows'][0]['buttons'][0]['text'])

    def test_find_nest_keeps_partially_completed_row(self):
        task = NightmareNestTask.__new__(NightmareNestTask)
        task.config = {'Tacet Discord Nests to Farm': ['落渊南丘残象聚落']}
        task.count_re = re.compile(r"(\d{1,2})/(\d{1,2})")
        task.queues = [task.go_nest]
        task._unreachable_nests = set()
        task.log_info = lambda *args, **kwargs: None
        task.height_of_screen = lambda value: 1000 * value
        task.width_of_screen = lambda value: 2000 * value
        task._reset_progress_tracking()
        task.require_game_frame = lambda: object()
        task.ocr = lambda *args, **kwargs: [FakeBox('梦枢天罗残象聚落', y=100),
                                           FakeBox('落渊南丘残象聚落', y=200),
                                           FakeBox('3/41', y=260),
                                           FakeBox('前往', x=1800, y=230)]

        target = task.find_nest()

        self.assertIsInstance(target, NestTarget)
        self.assertEqual((3, 41), (target.current, target.total))

    def test_incomplete_selected_target_prevents_success(self):
        task = NightmareNestTask.__new__(NightmareNestTask)
        task.config = {'Which to Farm': ['Nightmare Purification']}
        task._incomplete_targets = {'go_nest:41:10': ('落渊南丘残象聚落', 3, 41)}

        with self.assertRaisesRegex(RuntimeError, '3/41'):
            task._assert_selected_targets_complete()

    def test_unchanged_progress_three_times_stops_retry_loop(self):
        task = NightmareNestTask.__new__(NightmareNestTask)
        task._reset_progress_tracking()
        for _ in range(3):
            task._record_target_progress('go_nest:41:10', '落渊南丘残象聚落', 3, 41)

        with self.assertRaisesRegex(RuntimeError, '连续 3 次'):
            task._record_target_progress('go_nest:41:10', '落渊南丘残象聚落', 3, 41)

    def test_cache_key_ignores_small_ocr_position_jitter(self):
        task = NightmareNestTask.__new__(NightmareNestTask)
        task.queues = [lambda: None]
        task.height_of_screen = lambda value: 1000 * value

        first = task._make_nest_cache_key(FakeBox('0/36', y=200), '36')
        shifted = task._make_nest_cache_key(FakeBox('0/36', y=202), '36')

        self.assertEqual(first, shifted)

    def residual_task(self, selected, boxes, bottom=False):
        from unittest.mock import Mock
        task = NightmareNestTask.__new__(NightmareNestTask)
        task.config = {'Which to Farm': ['Tacet Discord Nest'],
                       'Tacet Discord Nests to Farm': selected}
        task.count_re = re.compile(r'(\d{1,2})/(\d{1,2})')
        task._reset_progress_tracking()
        task._unreachable_nests = set()
        task.queues = [task.go_nest_scroll if bottom else task.go_nest]
        task.require_game_frame = Mock(return_value=object())
        task.ocr = Mock(return_value=boxes)
        task.height_of_screen = lambda value: 1000 * value
        task.scroll_relative = Mock()
        task.sleep = Mock()
        task.click = Mock()
        task.open_boss_book = Mock()
        task.screenshot = Mock()
        task.log_info = Mock()
        return task

    def residual_boxes(self, names, current=0, start=150):
        from src.nightmare_nests import NEST_TOTALS_BY_NAME
        boxes = []
        for index, name in enumerate(names):
            y = start + index * 170
            boxes.extend([FakeBox(name, y=y),
                          FakeBox(f'{current}/{NEST_TOTALS_BY_NAME[name]}', y=y+60),
                          FakeBox('前往', x=1800, y=y+30)])
        return boxes

    def test_only_bottom_selection_adds_bottom_action(self):
        from src.nightmare_nests import NEST_NAMES
        for selected in ([], NEST_NAMES[:4], [NEST_NAMES[-1]], NEST_NAMES):
            with self.subTest(selected=selected):
                task = self.residual_task(selected, [])
                task._init_queue()
                self.assertEqual((["go_nest"] if selected else []) +
                                 (["go_nest_scroll"] if NEST_NAMES[-1] in selected else []),
                                 [action.__name__ for action in task.queues])

    def test_three_identical_totals_are_selected_by_name(self):
        from src.nightmare_nests import NEST_NAMES
        boxes = self.residual_boxes(NEST_NAMES[:4])
        task = self.residual_task([NEST_NAMES[3]], boxes)
        target = task.find_nest()
        self.assertEqual(NEST_NAMES[3], target.display_name)
        self.assertIs(boxes[-1], target.box)
        self.assertEqual('residual:' + NEST_NAMES[3], target.cache_key)
        task.scroll_relative.assert_not_called()

    def test_fifth_target_is_named_after_scroll_and_overlap_ignored(self):
        from src.nightmare_nests import NEST_NAMES
        task = self.residual_task([NEST_NAMES[-1]], self.residual_boxes(NEST_NAMES[2:]), bottom=True)
        target = task.find_nest()
        self.assertEqual(NEST_NAMES[-1], target.display_name)
        self.assertEqual(5, target.ordinal)

    def test_missing_top_target_retries_upwards_and_cannot_report_success(self):
        from src.nightmare_nests import NEST_NAMES
        task = self.residual_task([NEST_NAMES[1]], self.residual_boxes([NEST_NAMES[0]]))
        with self.assertRaisesRegex(RuntimeError, '未找到所选地点'):
            task.find_nest()
        self.assertEqual(2, task.scroll_relative.call_count)
        self.assertTrue(all(call.args[-1] > 0 for call in task.scroll_relative.call_args_list))
        task.screenshot.assert_called_once()
        with self.assertRaisesRegex(RuntimeError, '未确认完成'):
            task._assert_selected_targets_complete()

    def test_wrong_total_or_missing_button_never_clicks(self):
        from src.nightmare_nests import NEST_NAMES
        for broken in ('count', 'button'):
            boxes = self.residual_boxes([NEST_NAMES[0]])
            if broken == 'count':
                boxes[1].name = '0/41'
            else:
                boxes.pop()
            task = self.residual_task([NEST_NAMES[0]], boxes)
            with self.assertRaises(RuntimeError):
                task.find_nest()
            task.click.assert_not_called()

    def test_completed_selection_needs_no_bottom_or_unselected_counts(self):
        from src.nightmare_nests import NEST_NAMES
        boxes = self.residual_boxes([NEST_NAMES[0]], current=48)
        task = self.residual_task([NEST_NAMES[0]], boxes)
        self.assertIsNone(task.find_nest())
        task._assert_selected_targets_complete()
        task.scroll_relative.assert_not_called()

    def test_missing_fifth_blocks_all_selected_completion(self):
        from src.nightmare_nests import NEST_NAMES
        task = self.residual_task(NEST_NAMES, [])
        task._nest_completed.update(NEST_NAMES[:-1])
        with self.assertRaisesRegex(RuntimeError, '陷足流川'):
            task._assert_selected_targets_complete()

    def test_refresh_is_not_a_combat_attempt_and_identity_survives_scroll(self):
        from src.nightmare_nests import NEST_NAMES
        task = self.residual_task([NEST_NAMES[3]], self.residual_boxes(NEST_NAMES[:4]))
        first = task.find_nest()
        for _ in range(5):
            self.assertEqual(first.cache_key, task.find_nest().cache_key)
        self.assertEqual(0, task._nest_stagnation[first.cache_key])
        for index in range(3):
            task._nest_attempted.add(first.cache_key)
            if index < 2:
                task.find_nest()
            else:
                with self.assertRaisesRegex(RuntimeError, '连续 3 次'):
                    task.find_nest()

    def test_stale_bottom_view_must_not_be_treated_as_top(self):
        from src.nightmare_nests import NEST_NAMES
        task = self.residual_task([NEST_NAMES[3]], self.residual_boxes(NEST_NAMES[1:]))
        with self.assertRaisesRegex(RuntimeError, '列表顶部'):
            task.find_nest()

    def test_saved_old_names_are_not_reinterpreted_by_new_order(self):
        old = ['落渊南丘残象聚落', '陷足流川残象聚落']
        task = self.residual_task(old, [])
        self.assertEqual(set(old), task._selected_residual_names())
        self.assertNotIn('梦枢天罗残象聚落', task._selected_residual_names())
        task.config['Tacet Discord Nests to Farm'] = ['落渊南丘残像聚落']
        self.assertEqual({'落渊南丘残象聚落'}, task._selected_residual_names())

    def test_missing_legacy_selection_and_explicit_empty_keep_new_target_disabled(self):
        from src.nightmare_nests import DEFAULT_NEST_NAMES
        task = self.residual_task([], [])
        del task.config['Tacet Discord Nests to Farm']
        self.assertEqual(set(DEFAULT_NEST_NAMES), task._selected_residual_names())
        task.config['Which to Farm'] = []
        task._init_queue()
        self.assertEqual([], task.queues)

    def test_bottom_scroll_failure_is_bounded_and_has_evidence(self):
        from src.nightmare_nests import NEST_NAMES
        task = self.residual_task([NEST_NAMES[-1]],
                                  self.residual_boxes(NEST_NAMES[:4]), bottom=True)
        with self.assertRaisesRegex(RuntimeError, '陷足流川'):
            task.find_nest()
        self.assertEqual(2, task.scroll_relative.call_count)
        task.screenshot.assert_called_once()

    def test_top_entry_restores_upwards_and_bottom_reuses_scrollbar(self):
        task = self.residual_task([], [])
        task.go_nest()
        task.scroll_relative.assert_called_once_with(.75, .5, 20)
        task.click.assert_not_called()
        task.go_nest_scroll()
        task.click.assert_called_once_with(.9730, .8806, after_sleep=.3)

    def test_stop_during_identification_is_not_swallowed(self):
        from ok import TaskDisabledException
        from src.nightmare_nests import NEST_NAMES
        task = self.residual_task([NEST_NAMES[0]], [])
        task.require_game_frame.side_effect = TaskDisabledException('stop')
        with self.assertRaises(TaskDisabledException):
            task.find_nest()
        task.screenshot.assert_not_called()

    def test_full_run_covers_selected_targets_once_and_scrolls_only_for_fifth(self):
        from unittest.mock import Mock, patch
        from src.nightmare_nests import NEST_NAMES, NEST_TOTALS_BY_NAME
        for selected in (NEST_NAMES[:4], [NEST_NAMES[-1]], NEST_NAMES):
            with self.subTest(selected=selected):
                task = self.residual_task(selected, [])
                page = {'bottom': False}
                complete = set()
                visited = []
                task.ensure_main = Mock()
                task._open_book_with_retry = Mock()

                def scroll(x, y, count):
                    page['bottom'] = count < 0

                def click(x, y, **kwargs):
                    self.assertEqual((.9730, .8806), (x, y))
                    page['bottom'] = True

                def ocr(*args, **kwargs):
                    names = NEST_NAMES[2:] if page['bottom'] else NEST_NAMES[:4]
                    boxes = self.residual_boxes(names)
                    for box in boxes:
                        for name in complete:
                            # Counts are identified by the adjacent title in this fixture.
                            if box.name == name:
                                count = boxes[boxes.index(box) + 1]
                                total = NEST_TOTALS_BY_NAME[name]
                                count.name = f'{total}/{total}'
                    return boxes

                def combat(target):
                    visited.append(target.display_name)
                    complete.add(target.display_name)

                task.scroll_relative.side_effect = scroll
                task.click.side_effect = click
                task.ocr.side_effect = ocr
                task.combat_nest = combat
                with patch('src.task.NightmareNestTask.WWOneTimeTask.run'):
                    task.run()
                self.assertEqual(selected, visited)
                # The second bottom positioning confirms progress after returning from combat.
                self.assertEqual(2 if NEST_NAMES[-1] in selected else 0, task.click.call_count)


if __name__ == '__main__':
    unittest.main()
