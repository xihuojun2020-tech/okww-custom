import unittest

from src.task.BaseWWTask import LOGIN_TEXTS
from src.task.MultiAccountDailyTask import (
    MultiAccountDailyTask,
    account_pattern,
    normalize_account_name,
    profile_short_name,
)


class AccountBox:
    def __init__(self, name, x=10, y=20, width=100, height=20):
        self.name = name
        self.x = x
        self.y = y
        self.width = width
        self.height = height


def _fake_login_task(main_texts=None, dialog_texts=None):
    """构造可注入 OCR 文本的假任务（主窗口帧 + #32770 登录对话框帧两路）。

    find_boxes 按文本真实匹配：掩码账号匹配 account_pattern，登录文本匹配 LOGIN_TEXTS。
    """

    class FakeTask:
        def __init__(self):
            self._login_in_dialog = False

        _account_entry_count = MultiAccountDailyTask._account_entry_count

        def ocr(self):
            return [AccountBox(t) for t in (main_texts or [])]

        def find_boxes(self, texts, match):
            result = []
            for t in texts or []:
                name = (t.name or '').strip()
                if match == account_pattern and account_pattern.search(name):
                    result.append(t)
                elif match == LOGIN_TEXTS and name in ('登录', '登入', 'Log'):
                    result.append(t)
            return result

        def _ocr_login_dialog(self):
            if dialog_texts is None:
                return None
            return [AccountBox(t) for t in dialog_texts]

        def log_info(self, *args, **kwargs):
            pass

        def log_warning(self, *args, **kwargs):
            pass

        def log_error(self, *args, **kwargs):
            pass

        def screenshot(self, *args, **kwargs):
            pass

    return FakeTask()


class TestMultiAccountDailyTask(unittest.TestCase):

    def test_account_dropdown_accepts_multiple_login_text_matches(self):
        account_box = object()

        class FakeTask:
            def ocr(self):
                return []

            def find_boxes(self, texts, match):
                if match == account_pattern:
                    return [account_box]
                if match == LOGIN_TEXTS:
                    return [object(), object()]
                return []

        self.assertIs(MultiAccountDailyTask.do_find_account_drop_down(FakeTask()), account_box)

    def test_account_name_normalization_groups_common_ocr_variants(self):
        self.assertEqual(
            normalize_account_name("cc****33@demo.com.hk"),
            normalize_account_name("cc****33@dem0.com.hk"),
        )
        self.assertEqual(
            normalize_account_name("bb****02@example.com"),
            normalize_account_name("bb****02@example.con"),
        )

    def test_profile_short_name_is_exact_and_distinguishes_a1_from_a10(self):
        self.assertEqual(profile_short_name('【A1-测试-13000000001】'), 'A1')
        self.assertEqual(profile_short_name('【A10-测试-13000000010】'), 'A10')
        self.assertIsNone(profile_short_name('测试-A1-13000000001'))

    def test_resolve_profile_short_names_preserves_a1_a3_a4_order(self):
        profiles = [
            '【A4-测试-13000000004】',
            '【A10-测试-13000000010】',
            '【A1-测试-13000000001】',
            '【A3-测试-13000000003】',
        ]

        class FakeTask:
            def get_profile_names(self):
                return profiles

        resolved = MultiAccountDailyTask.resolve_profile_short_names(
            FakeTask(),
            ['A1', 'A3', 'A4'],
        )
        self.assertEqual(resolved, [profiles[2], profiles[3], profiles[0]])

    def test_login_identity_maps_alias_and_masked_phones_for_continuous_accounts(self):
        profiles = {
            '【A1-测试-13000000001】': {
                '备用识别名称内容': 'U123ABC，alias@example.com',
                'account_aliases': ['ULEGACY123'],
            },
            '【A3-测试-15300000003】': {},
            '【A4-测试-18000000004】': {},
        }

        class FakeTask:
            def _load_profiles(self):
                return profiles

            get_profile_names = MultiAccountDailyTask.get_profile_names
            _profile_identities = MultiAccountDailyTask._profile_identities

        task = FakeTask()
        self.assertEqual(
            MultiAccountDailyTask.match_profile_from_login(task, 'U123ABC'),
            '【A1-测试-13000000001】',
        )
        self.assertEqual(
            MultiAccountDailyTask.match_profile_from_login(task, 'alias@example.com'),
            '【A1-测试-13000000001】',
        )
        self.assertEqual(
            MultiAccountDailyTask.match_profile_from_login(task, 'ULEGACY123'),
            '【A1-测试-13000000001】',
        )
        self.assertEqual(
            MultiAccountDailyTask.match_profile_from_login(task, '153****0003'),
            '【A3-测试-15300000003】',
        )
        self.assertEqual(
            MultiAccountDailyTask.match_profile_from_login(task, '180****0004'),
            '【A4-测试-18000000004】',
        )

    def test_continuous_sequence_uses_formal_login_flow_and_logs_out_between_accounts(self):
        class FakeTask:
            def __init__(self):
                self.events = []

            def _select_and_login_specific(self, target):
                self.events.append(('login', target))
                return target

            def _switch_to_login(self):
                self.events.append(('logout', None))

            def sleep(self, _seconds):
                pass

            def log_info(self, *_args, **_kwargs):
                pass

        task = FakeTask()
        progress = []
        result = MultiAccountDailyTask._select_and_login_sequence(
            task,
            ['profile-a1', 'profile-a3', 'profile-a4'],
            progress_callback=lambda index, total, target: progress.append((index, total, target)),
        )
        self.assertEqual(result, ['profile-a1', 'profile-a3', 'profile-a4'])
        self.assertEqual(
            task.events,
            [
                ('login', 'profile-a1'),
                ('logout', None),
                ('login', 'profile-a3'),
                ('logout', None),
                ('login', 'profile-a4'),
            ],
        )
        self.assertEqual(progress, [
            (1, 3, 'profile-a1'),
            (2, 3, 'profile-a3'),
            (3, 3, 'profile-a4'),
        ])

    def test_click_account_list_selects_requested_visible_account(self):
        class FakeTask:
            def __init__(self):
                self._login_in_dialog = False
                self.clicked = []

            def ocr(self, match=None):
                return [
                    AccountBox("aa****01@example.com"),
                    AccountBox("aa****01@example.com"),
                    AccountBox("bb****02@example.com"),
                    AccountBox("cc****03@example.com.hk"),
                ]

            def match_profile_from_login(self, name):
                if name == "cc****03@example.com.hk":
                    return "profile-c"
                return None

            def click(self, account, after_sleep=0):
                self.clicked.append(account.name)

            def log_info(self, *args):
                pass

        task = FakeTask()

        selected = MultiAccountDailyTask._click_account_in_list(task, "profile-c")

        self.assertTrue(selected)
        self.assertEqual(task.clicked, ["cc****03@example.com.hk"])

    def test_click_account_list_uses_one_ocr_snapshot_for_mask_and_scan_alias(self):
        class FakeTask:
            def __init__(self):
                self._login_in_dialog = False
                self.ocr_calls = 0
                self.clicked = []

            def ocr(self):
                self.ocr_calls += 1
                return [AccountBox('U570994311A'), AccountBox('153****9621')]

            def match_profile_from_login(self, name):
                return {
                    'U570994311A': 'profile-a1',
                    '153****9621': 'profile-a3',
                }.get(name)

            def click(self, account, after_sleep=0):
                self.clicked.append(account.name)

            def log_info(self, *args, **kwargs):
                pass

            def log_warning(self, *args, **kwargs):
                pass

            def log_error(self, *args, **kwargs):
                pass

        task = FakeTask()
        selected = MultiAccountDailyTask._click_account_in_list(task, 'profile-a3')

        self.assertTrue(selected)
        self.assertEqual(task.ocr_calls, 1)
        self.assertEqual(task.clicked, ['153****9621'])

    def test_selection_refreshes_then_uses_verified_screen_fallback(self):
        class FakeHwndWindow:
            top_hwnd = 101
            hwnd = 101

            def __init__(self):
                self.refresh_count = 0
                self.front_count = 0

            def do_update_window_size(self):
                self.refresh_count += 1

            def bring_to_front(self):
                self.front_count += 1
                return True

            def get_capture_origin(self):
                return (100, 200)

        class FakeTask:
            _click_account_in_list = MultiAccountDailyTask._click_account_in_list
            _wait_for_account_selection_stable = MultiAccountDailyTask._wait_for_account_selection_stable
            _same_account = MultiAccountDailyTask._same_account
            _refresh_hwnd_window_snapshot = MultiAccountDailyTask._refresh_hwnd_window_snapshot
            _bring_account_window_to_front = MultiAccountDailyTask._bring_account_window_to_front
            _main_box_center_screen = MultiAccountDailyTask._main_box_center_screen
            _box_center_screen = MultiAccountDailyTask._box_center_screen
            _log_account_click_delivery = MultiAccountDailyTask._log_account_click_delivery

            def __init__(self):
                self._login_in_dialog = False
                self.hwnd = FakeHwndWindow()
                self.phase = 'first'
                self.open_count = 0
                self.post_clicks = 0
                self.screen_clicks = []
                self.logs = []

            def sleep(self, _seconds):
                pass

            def _open_account_list(self):
                self.open_count += 1
                if self.open_count == 1:
                    return False
                if self.post_clicks >= 2:
                    self.phase = 'fallback_list'
                return True

            def _account_list_expanded(self):
                return self.phase == 'fallback_list'

            def ocr(self):
                return [
                    AccountBox('U570994311A'),
                    AccountBox('153****9621'),
                ]

            def match_profile_from_login(self, name):
                return {
                    'U570994311A': 'profile-a1',
                    '153****9621': 'profile-a3',
                }.get(name)

            def click(self, _account, after_sleep=0):
                self.post_clicks += 1
                self.phase = 'post'

            def _screen_click(self, x, y, after_sleep=0):
                self.screen_clicks.append((x, y))
                self.phase = 'fallback_clicked'
                return True

            def wait_until(self, callback, **kwargs):
                if kwargs.get('time_out') == 10:
                    return callback()
                if kwargs.get('time_out') == 8:
                    for _ in range(2):
                        if callback():
                            return True
                    return None
                return callback()

            def _detect_current_account_from_login(self):
                return 'profile-a3' if self.phase == 'fallback_clicked' else 'profile-a1'

            def log_info(self, message, **kwargs):
                self.logs.append(str(message))

            def log_warning(self, message, **kwargs):
                self.logs.append(str(message))

            def log_error(self, message, **kwargs):
                self.logs.append(str(message))

            def screenshot(self, *args, **kwargs):
                pass

            def tr(self, message):
                return message

        task = FakeTask()
        self.assertTrue(
            MultiAccountDailyTask._select_account_with_retry(
                task, 'profile-a3', max_retries=4,
            )
        )
        self.assertEqual(task.open_count, 4)
        self.assertEqual(task.post_clicks, 2)
        self.assertEqual(len(task.screen_clicks), 1)
        self.assertEqual(task.hwnd.refresh_count, 1)
        self.assertEqual(task.hwnd.front_count, 1)
        self.assertTrue(any('方式=PostMessage' in message for message in task.logs))
        self.assertTrue(any('方式=系统屏幕' in message for message in task.logs))

    def test_screen_fallback_cancels_when_game_cannot_be_brought_to_front(self):
        class FakeTask:
            _login_in_dialog = False

            def __init__(self):
                self.ocr_calls = 0
                self.screen_clicks = []

            def _account_list_expanded(self):
                return True

            def _bring_account_window_to_front(self):
                return False

            def ocr(self):
                self.ocr_calls += 1
                return [AccountBox('153****9621')]

            def _screen_click(self, x, y, after_sleep=0):
                self.screen_clicks.append((x, y))
                return True

            def log_warning(self, *args, **kwargs):
                pass

        task = FakeTask()
        sent = MultiAccountDailyTask._click_account_in_list(
            task,
            'profile-a3',
            interaction_mode='screen',
            require_expanded=True,
        )

        self.assertFalse(sent)
        self.assertEqual(task.ocr_calls, 0)
        self.assertEqual(task.screen_clicks, [])

    def test_account_mismatch_reselects_target_instead_of_stopping(self):
        class FakeTask:
            def __init__(self):
                # 第一次看到旧账号；第二次点击后目标账号连续出现两帧。
                self.detected_batches = iter([
                    ["profile-a"],
                    ["profile-c", "profile-c"],
                ])
                self.current_batch = iter(())
                self.click_count = 0

            def sleep(self, _seconds):
                pass

            def _open_account_list(self):
                return True

            def _click_account_in_list(self, target):
                self.click_count += 1
                return target == "profile-c"

            def wait_until(self, callback, **_kwargs):
                # 生产逻辑的稳定检测需要连续采样；点击列表本身仍只采样一次。
                if _kwargs.get('time_out') == 8:
                    self.current_batch = iter(next(self.detected_batches))
                    for _ in range(3):
                        try:
                            if result := callback():
                                return result
                        except StopIteration:
                            return None
                    return None
                return callback()

            def _detect_current_account_from_login(self):
                return next(self.current_batch)

            _same_account = MultiAccountDailyTask._same_account
            _wait_for_account_selection_stable = MultiAccountDailyTask._wait_for_account_selection_stable

            def log_info(self, *_args, **_kwargs):
                pass

            def log_warning(self, *_args, **_kwargs):
                pass

            def log_error(self, *_args, **_kwargs):
                pass

            def screenshot(self, *_args, **_kwargs):
                pass

            def tr(self, message):
                return message

        task = FakeTask()
        selected = MultiAccountDailyTask._select_account_with_retry(
            task,
            "profile-c",
            max_retries=3,
        )
        self.assertTrue(selected)
        self.assertEqual(task.click_count, 2)

    def test_selection_waits_through_login_ui_flicker_before_confirming(self):
        class FakeTask:
            def __init__(self):
                self.expanded = iter([True, True, False, False, False])
                self.detected = iter(["profile-a", None, "profile-a", "profile-c", "profile-c"])
                self.click_count = 0
                self.wait_calls = []
                self.info_logs = []

            def sleep(self, _seconds):
                pass

            def _open_account_list(self):
                return True

            def _click_account_in_list(self, target):
                self.click_count += 1
                return target == "profile-c"

            def _account_list_expanded(self):
                return next(self.expanded)

            def wait_until(self, callback, **kwargs):
                self.wait_calls.append(kwargs)
                for _ in range(8):
                    try:
                        result = callback()
                    except StopIteration:
                        return None
                    if result:
                        return result
                return None

            def _detect_current_account_from_login(self):
                return next(self.detected)

            _same_account = MultiAccountDailyTask._same_account
            _wait_for_account_selection_stable = MultiAccountDailyTask._wait_for_account_selection_stable

            def log_info(self, *_args, **_kwargs):
                self.info_logs.append(str(_args[0]) if _args else '')

            def log_warning(self, *_args, **_kwargs):
                pass

            def log_error(self, *_args, **_kwargs):
                pass

            def screenshot(self, *_args, **_kwargs):
                pass

            def tr(self, message):
                return message

        task = FakeTask()
        selected = MultiAccountDailyTask._select_account_with_retry(
            task,
            "profile-c",
            max_retries=3,
        )

        self.assertTrue(selected)
        self.assertEqual(task.click_count, 1)
        self.assertTrue(any(call.get('time_out') == 8 for call in task.wait_calls))
        self.assertEqual(
            sum('列表已收起' in message for message in task.info_logs),
            1,
        )

    def test_selection_reselects_only_after_stable_wrong_account_timeout(self):
        class FakeTask:
            def __init__(self):
                self.detected = iter([
                    "profile-a", "profile-a", "profile-a",
                    "profile-c", "profile-c",
                ])
                self.click_count = 0
                self.info_logs = []

            def sleep(self, _seconds):
                pass

            def _open_account_list(self):
                return True

            def _click_account_in_list(self, target):
                self.click_count += 1
                return target == "profile-c"

            def _account_list_expanded(self):
                return False

            def wait_until(self, callback, **kwargs):
                if kwargs.get('time_out') == 8:
                    # 第一次选择持续显示错误账号，第二次选择目标连续两帧。
                    for _ in range(3 if self.click_count == 1 else 2):
                        if result := callback():
                            return result
                    return None
                return callback()

            def _detect_current_account_from_login(self):
                return next(self.detected)

            _same_account = MultiAccountDailyTask._same_account
            _wait_for_account_selection_stable = MultiAccountDailyTask._wait_for_account_selection_stable

            def log_info(self, *_args, **_kwargs):
                self.info_logs.append(str(_args[0]) if _args else '')

            def log_warning(self, *_args, **_kwargs):
                pass

            def log_error(self, *_args, **_kwargs):
                pass

            def screenshot(self, *_args, **_kwargs):
                pass

            def tr(self, message):
                return message

        task = FakeTask()
        selected = MultiAccountDailyTask._select_account_with_retry(
            task,
            "profile-c",
            max_retries=3,
        )

        self.assertTrue(selected)
        self.assertEqual(task.click_count, 2)
        self.assertEqual(
            sum('仍在闪烁或切换' in message for message in task.info_logs),
            1,
        )

    def test_login_precheck_reselects_when_displayed_account_changed(self):
        class FakeTask:
            def __init__(self):
                self.detected = iter(["profile-a", "profile-c"])
                self.reselect_count = 0

            def _detect_current_account_from_login(self):
                return next(self.detected)

            _same_account = MultiAccountDailyTask._same_account

            def _select_account_with_retry(self, target, max_retries):
                self.reselect_count += 1
                return target == "profile-c" and max_retries == 2

            def sleep(self, _seconds):
                pass

            def log_warning(self, *_args, **_kwargs):
                pass

            def log_error(self, *_args, **_kwargs):
                pass

            def screenshot(self, *_args, **_kwargs):
                pass

            def tr(self, message):
                return message

        task = FakeTask()
        confirmed = MultiAccountDailyTask._confirm_target_before_login(
            task,
            "profile-c",
            max_retries=3,
        )
        self.assertTrue(confirmed)
        self.assertEqual(task.reselect_count, 1)

    def test_visible_login_profiles_preserves_list_order_and_removes_duplicates(self):
        class FakeTask:
            _login_in_dialog = False

            def ocr(self):
                return [
                    AccountBox("153****0003"),
                    AccountBox("U123ABC"),
                    AccountBox("153****0003"),
                    AccountBox("登录"),
                ]

            def match_profile_from_login(self, name):
                return {
                    "153****0003": "profile-a",
                    "U123ABC": "profile-b",
                }.get(name)

        profiles = MultiAccountDailyTask._visible_login_profiles(FakeTask())
        self.assertEqual(profiles, ["profile-a", "profile-b"])

    # ============ v1.03.74：下拉框收起/展开状态判定 ============

    def test_dropdown_ready_collapsed_single_mask_account(self):
        task = _fake_login_task(main_texts=['180****0004', '登录'])
        box = MultiAccountDailyTask.do_find_account_drop_down(task)
        self.assertIsNotNone(box)
        self.assertFalse(task._login_in_dialog)

    def test_dropdown_ready_expanded_multiple_accounts(self):
        # 列表已展开：账号条目 ≥2（掩码 + U 账号），仍视为登录就绪（返回下拉框）
        task = _fake_login_task(main_texts=['153****0003', 'U123ABC', '180****0004', '登入'])
        self.assertIsNotNone(MultiAccountDailyTask.do_find_account_drop_down(task))

    def test_dropdown_not_ready_without_login_text(self):
        task = _fake_login_task(main_texts=['180****0004'])
        self.assertIsNone(MultiAccountDailyTask.do_find_account_drop_down(task))

    def test_dropdown_dialog_fallback_sets_login_in_dialog(self):
        # 主窗口无特征 → 回退 #32770 登录对话框帧（U 扫码账号 + 登录文本）
        task = _fake_login_task(main_texts=[], dialog_texts=['U123ABC', '登录'])
        box = MultiAccountDailyTask.do_find_account_drop_down(task)
        self.assertIsNotNone(box)
        self.assertTrue(task._login_in_dialog)

    def test_dropdown_dialog_not_ready_when_only_launcher_texts(self):
        # 启动器界面（KURO GAMES / 修复，无登录文本无账号）→ 不命中
        task = _fake_login_task(main_texts=['KURO GAMES', '公告', '修复'])
        self.assertIsNone(MultiAccountDailyTask.do_find_account_drop_down(task))

    def test_account_list_expanded_true_with_two_entries(self):
        task = _fake_login_task(main_texts=['153****0003', 'U123ABC', '登入'])
        self.assertTrue(MultiAccountDailyTask._account_list_expanded(task))

    def test_account_list_expanded_false_with_single_entry(self):
        task = _fake_login_task(main_texts=['153****0003', '登入'])
        self.assertFalse(MultiAccountDailyTask._account_list_expanded(task))


if __name__ == "__main__":
    unittest.main()
