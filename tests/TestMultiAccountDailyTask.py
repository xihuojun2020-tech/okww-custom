import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ok import TaskDisabledException
from src.config_integrity import ConfigIntegrityBlocked
from src.runtime.task_run_coordinator import TaskRunCoordinator, TaskRunState
from src.task.BaseWWTask import LOGIN_TEXTS
from src.task.MultiAccountDailyTask import (
    CURRENT_ACCOUNT,
    MultiAccountDailyTask,
    account_pattern,
    normalize_account_name,
    profile_short_name,
)
from src.task.WWOneTimeTask import WWOneTimeTask


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
        self.assertEqual(profile_short_name('【A1-测试-19910000010】'), 'A1')
        self.assertEqual(profile_short_name('【A10-测试-19910000011】'), 'A10')
        self.assertIsNone(profile_short_name('测试-A1-19910000010'))

    def test_resolve_profile_short_names_preserves_a1_a3_a4_order(self):
        profiles = [
            '【A4-测试-19910000012】',
            '【A10-测试-19910000011】',
            '【A1-测试-19910000010】',
            '【A3-测试-19910000013】',
        ]

        class FakeTask:
            def get_profile_names(self):
                return profiles

        resolved = MultiAccountDailyTask.resolve_profile_short_names(
            FakeTask(),
            ['A1', 'A3', 'A4'],
        )
        self.assertEqual(resolved, [profiles[2], profiles[3], profiles[0]])

    @staticmethod
    def _switch_task(*, account_box, in_team, events):
        task = MultiAccountDailyTask.__new__(MultiAccountDailyTask)
        task.integrity_service = None
        task._executor = None
        task.do_find_account_drop_down = lambda: account_box
        task.in_team = lambda: in_team
        task._switch_to_login = lambda: events.append('logout') or True
        task._wait_login_screen_stable = lambda **_kwargs: events.append('wait_login')
        task._select_account_with_retry = lambda *_args, **_kwargs: None
        task._click_login_for_target = lambda *_args, **_kwargs: None
        task.ensure_main = lambda **_kwargs: None
        task.sleep = lambda *_args: None
        task._begin_account_switch_evidence = lambda *_args: None
        task._evidence_stage = lambda *_args, **_kwargs: None
        task._finish_account_switch_evidence = lambda *_args, **_kwargs: None
        task.log_info = lambda *_args, **_kwargs: None
        return task

    def test_switch_to_account_logs_out_when_world_team_is_visible(self):
        events = []
        task = self._switch_task(account_box=None, in_team=(True, 0, 3), events=events)

        with patch('src.task.BaseWWTask.og.my_app', SimpleNamespace(logged_in=True)):
            self.assertEqual(task.switch_to_account('A3'), 'A3')
        self.assertEqual(events[:2], ['logout', 'wait_login'])

    def test_switch_to_account_does_not_logout_from_login_screen(self):
        events = []
        task = self._switch_task(account_box=object(), in_team=(True, 0, 3), events=events)

        with patch('src.task.BaseWWTask.og.my_app', SimpleNamespace(logged_in=True)):
            self.assertEqual(task.switch_to_account('A3'), 'A3')
        self.assertEqual(events, ['wait_login'])

    @staticmethod
    def _run_task(outcome, state=TaskRunState.IDLE):
        task = MultiAccountDailyTask.__new__(MultiAccountDailyTask)
        task.run_coordinator = TaskRunCoordinator()
        if state == TaskRunState.RUNNING:
            snapshot = SimpleNamespace(profile_ids=('a3',), sequence_id='序列1', revision='r', run_id='run')
            task.run_coordinator.start(snapshot)
        task._account_refresh_pending = False
        task.integrity_service = None
        task.done_set = set()
        task.all_accounts = set()
        task._sync_local_to_sequences = lambda: None
        task.get_task_by_class = lambda *_args: None
        task.log_error = task.log_info = lambda *_args, **_kwargs: None
        task._run_inner = outcome
        return task

    def test_run_marks_coordinator_failed_and_allows_retry(self):
        def fail_run():
            raise RuntimeError('login timeout')

        task = self._run_task(fail_run)
        with patch.object(WWOneTimeTask, 'run', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'login timeout'):
                task.run()
        self.assertEqual(task.run_coordinator.state, TaskRunState.FAILED)

        snapshot = SimpleNamespace(profile_ids=('a3',), sequence_id='序列1', revision='r', run_id='retry')
        task.run_coordinator.start(snapshot)
        self.assertEqual(task.run_coordinator.state, TaskRunState.RUNNING)

    def test_run_marks_coordinator_stopped_on_disable(self):
        def stop_run():
            raise TaskDisabledException()

        task = self._run_task(stop_run, TaskRunState.RUNNING)
        with patch.object(WWOneTimeTask, 'run', return_value=None):
            with self.assertRaises(TaskDisabledException):
                task.run()
        self.assertEqual(task.run_coordinator.state, TaskRunState.STOPPED)

    def test_run_marks_coordinator_stopped_after_success(self):
        task = self._run_task(lambda: None, TaskRunState.RUNNING)
        with patch.object(WWOneTimeTask, 'run', return_value=None):
            task.run()
        self.assertEqual(task.run_coordinator.state, TaskRunState.STOPPED)

    def test_current_account_rotates_a4_a3_sequence_to_a3_then_a4(self):
        task = MultiAccountDailyTask.__new__(MultiAccountDailyTask)
        task.config = {CURRENT_ACCOUNT: 'A3'}
        task.get_sequence_accounts = lambda: ['A4', 'A3']
        task.done_set = set()
        task._same_account = lambda left, right: left == right
        task._is_done = lambda account: account in task.done_set

        self.assertEqual(task._next_target_account(), 'A3')
        task.done_set.add('A3')
        self.assertEqual(task._next_target_account(), 'A4')

    def test_login_identity_maps_alias_and_masked_phones_for_continuous_accounts(self):
        profiles = {
            '【A1-测试-19910000010】': {
                '备用识别名称内容': 'UTEST1002A，alias@example.com',
                'account_aliases': ['UTEST1003A'],
            },
            '【A3-测试-19910000014】': {},
            '【A4-测试-19910000015】': {},
        }

        class FakeTask:
            def _load_profiles(self):
                return profiles

            get_profile_names = MultiAccountDailyTask.get_profile_names
            _profile_identities = MultiAccountDailyTask._profile_identities

        task = FakeTask()
        self.assertEqual(
            MultiAccountDailyTask.match_profile_from_login(task, 'UTEST1002A'),
            '【A1-测试-19910000010】',
        )
        self.assertEqual(
            MultiAccountDailyTask.match_profile_from_login(task, 'alias@example.com'),
            '【A1-测试-19910000010】',
        )
        self.assertEqual(
            MultiAccountDailyTask.match_profile_from_login(task, 'UTEST1003A'),
            '【A1-测试-19910000010】',
        )
        self.assertEqual(
            MultiAccountDailyTask.match_profile_from_login(task, '199****0014'),
            '【A3-测试-19910000014】',
        )
        self.assertEqual(
            MultiAccountDailyTask.match_profile_from_login(task, '199****0015'),
            '【A4-测试-19910000015】',
        )

    def test_explicit_masked_phone_and_u_name_are_used_when_display_name_has_no_phone(self):
        profiles = {
            'A1': {
                'masked_phone': '199****0002',
                'alternate_login_name': 'UTEST0001A',
                'nickname': '夜归',
            }
        }

        class FakeTask:
            def _load_profiles(self):
                return profiles

            get_profile_names = MultiAccountDailyTask.get_profile_names
            _profile_identities = MultiAccountDailyTask._profile_identities

        task = FakeTask()
        self.assertEqual(MultiAccountDailyTask.match_profile_from_login(task, '199****0002'), 'A1')
        self.assertEqual(MultiAccountDailyTask.match_profile_from_login(task, 'UTEST0001A'), 'A1')

    def test_login_identity_supports_legacy_account_name_and_rejects_ambiguity(self):
        profiles = {
            '【A1-测试-19910000010】': {'Account Name': 'LEGACY-A1'},
            '【A3-测试-19910000014】': {'备用识别名称内容': 'SHARED-ID'},
            '【A4-测试-19910000015】': {'account_aliases': ['SHARED-ID']},
        }

        class FakeTask:
            def _load_profiles(self):
                return profiles

            get_profile_names = MultiAccountDailyTask.get_profile_names
            _profile_identities = MultiAccountDailyTask._profile_identities

        task = FakeTask()
        self.assertEqual(
            MultiAccountDailyTask.match_profile_from_login(task, 'LEGACY-A1'),
            '【A1-测试-19910000010】',
        )
        with self.assertRaisesRegex(ValueError, '多个账号方案'):
            MultiAccountDailyTask.match_profile_from_login(task, 'SHARED-ID')

    def test_transition_guard_blocks_logout_before_state_detection(self):
        class FakeService:
            def __init__(self):
                self.checks = 0

            def check(self):
                self.checks += 1
                return type('Result', (), {'ok': False})()

            def describe(self, _result):
                return 'integrity mismatch'

        class FakeTask:
            _switch_to_login = MultiAccountDailyTask._switch_to_login
            _guard_account_transition = MultiAccountDailyTask._guard_account_transition

            def __init__(self):
                self.integrity_service = FakeService()
                self.state_checks = 0

            def _logout_state(self):
                self.state_checks += 1
                raise AssertionError('logout state must not be inspected while blocked')

            def log_info(self, *_args, **_kwargs):
                raise AssertionError('logging after the guard is not expected')

        task = FakeTask()
        with self.assertRaises(ConfigIntegrityBlocked):
            task._switch_to_login()
        self.assertEqual(task.integrity_service.checks, 1)
        self.assertEqual(task.state_checks, 0)

    def test_transition_guard_blocks_selection_before_any_ui_action(self):
        class FakeService:
            def __init__(self):
                self.checks = 0

            def check(self):
                self.checks += 1
                return type('Result', (), {'ok': False})()

            def describe(self, _result):
                return 'integrity mismatch'

        class FakeTask:
            _select_and_login_specific = MultiAccountDailyTask._select_and_login_specific
            _guard_account_transition = MultiAccountDailyTask._guard_account_transition

            def __init__(self):
                self.integrity_service = FakeService()
                self.ui_actions = 0

            @property
            def executor(self):
                self.ui_actions += 1
                raise AssertionError('executor must not be touched while blocked')

        task = FakeTask()
        with self.assertRaises(ConfigIntegrityBlocked):
            task._select_and_login_specific('A1')
        self.assertEqual(task.integrity_service.checks, 1)
        self.assertEqual(task.ui_actions, 0)

    def test_logout_retries_when_confirm_button_was_not_delivered(self):
        class FakeTask:
            _switch_to_login = MultiAccountDailyTask._switch_to_login
            _logout_state = MultiAccountDailyTask._logout_state

            def __init__(self):
                self.confirm_calls = 0
                self.logs = []
                self.states = iter(('confirm', 'confirm', 'login'))

            def do_find_account_drop_down(self):
                return None

            def _logout_state(self):
                return next(self.states)

            def send_key(self, *_args, **_kwargs):
                self.logs.append('ESC')

            def click_relative(self, *_args, **_kwargs):
                pass

            def click_confirm(self, **_kwargs):
                self.confirm_calls += 1
                return self.confirm_calls >= 2

            def is_main(self, **_kwargs):
                return True

            def sleep(self, _seconds):
                pass

            def screenshot(self, *_args):
                pass

            def log_info(self, message, **_kwargs):
                self.logs.append(str(message))

            def log_warning(self, message, **_kwargs):
                self.logs.append(str(message))

            def tr(self, message):
                return message

        task = FakeTask()
        self.assertTrue(task._switch_to_login())
        self.assertEqual(task.confirm_calls, 2)
        self.assertTrue(any('确认退登按钮本次未成功投递' in message for message in task.logs))
        self.assertNotIn('ESC', task.logs)

    def test_logout_confirm_dialog_is_reclicked_without_esc(self):
        class FakeTask:
            _switch_to_login = MultiAccountDailyTask._switch_to_login

            def __init__(self):
                self.states = iter(('confirm', 'login'))
                self.esc_count = 0
                self.confirm_count = 0

            def _logout_state(self):
                return next(self.states)

            def click_confirm(self, **_kwargs):
                self.confirm_count += 1
                return True

            def send_key(self, *_args, **_kwargs):
                self.esc_count += 1

            def sleep(self, _seconds):
                pass

            def log_info(self, *_args, **_kwargs):
                pass

            def log_warning(self, *_args, **_kwargs):
                pass

            def screenshot(self, *_args):
                pass

            def tr(self, message):
                return message

        task = FakeTask()
        self.assertTrue(task._switch_to_login())
        self.assertEqual(task.confirm_count, 1)
        self.assertEqual(task.esc_count, 0)

    def test_logout_setting_page_clicks_logout_without_esc(self):
        class FakeTask:
            _switch_to_login = MultiAccountDailyTask._switch_to_login

            def __init__(self):
                self.states = iter(('setting', 'login'))
                self.esc_count = 0
                self.logout_clicks = 0

            def _logout_state(self):
                return next(self.states)

            def click_relative(self, *_args, **_kwargs):
                self.logout_clicks += 1

            def send_key(self, *_args, **_kwargs):
                self.esc_count += 1

            def sleep(self, _seconds):
                pass

            def log_info(self, *_args, **_kwargs):
                pass

            def log_warning(self, *_args, **_kwargs):
                pass

            def screenshot(self, *_args):
                pass

            def tr(self, message):
                return message

        task = FakeTask()
        self.assertTrue(task._switch_to_login())
        self.assertEqual(task.logout_clicks, 1)
        self.assertEqual(task.esc_count, 0)

    def test_logout_stop_exception_propagates_from_state_detection(self):
        class FakeTask:
            _switch_to_login = MultiAccountDailyTask._switch_to_login

            def _logout_state(self):
                raise TaskDisabledException()

            def log_info(self, *_args, **_kwargs):
                pass

            def tr(self, message):
                return message

        with self.assertRaises(TaskDisabledException):
            FakeTask()._switch_to_login()

    def test_logout_loading_unknown_state_does_not_exhaust_poll_count(self):
        class FakeTask:
            _switch_to_login = MultiAccountDailyTask._switch_to_login

            def __init__(self):
                # 旧的 12 轮上限会在正常的长加载过程中提前失败。
                self.states = iter(('confirm',) + ('unknown',) * 20 + ('login',))
                self.confirm_count = 0

            def _logout_state(self):
                return next(self.states)

            def click_confirm(self, **_kwargs):
                self.confirm_count += 1
                return True

            def sleep(self, _seconds):
                pass

            def log_info(self, *_args, **_kwargs):
                pass

            def log_warning(self, *_args, **_kwargs):
                pass

            def screenshot(self, *_args):
                pass

            def tr(self, message):
                return message

        task = FakeTask()
        self.assertTrue(task._switch_to_login())
        self.assertEqual(task.confirm_count, 1)

    def test_logout_none_input_counts_and_unknown_does_not_reset_budget(self):
        class FakeTask:
            _switch_to_login = MultiAccountDailyTask._switch_to_login

            def __init__(self):
                # Unknown OCR frames must not give the confirm action a fresh
                # budget; a None return still means input was delivered.
                self.states = iter(('confirm', 'unknown', 'confirm', 'unknown',
                                    'confirm', 'confirm'))
                self.confirm_count = 0

            def _logout_state(self):
                return next(self.states)

            def click_confirm(self, **_kwargs):
                self.confirm_count += 1
                return None

            def sleep(self, _seconds):
                pass

            def log_info(self, *_args, **_kwargs):
                pass

            def log_warning(self, *_args, **_kwargs):
                pass

            def screenshot(self, *_args):
                pass

            def tr(self, message):
                return message

        task = FakeTask()
        with self.assertRaises(Exception):
            task._switch_to_login()
        self.assertEqual(task.confirm_count, 3)

    def test_login_back_failure_does_not_send_success_notification(self):
        class FakeTask:
            _login_back_to = MultiAccountDailyTask._login_back_to

            def __init__(self):
                self.notifications = []

            def _select_and_login_specific(self, _profile):
                raise RuntimeError('login failed')

            def _notify_user(self, title, message):
                self.notifications.append((title, message))

            def log_info(self, *_args, **_kwargs):
                pass

            def log_error(self, *_args, **_kwargs):
                pass

        task = FakeTask()
        task._login_back_to('profile-a1')
        self.assertEqual(len(task.notifications), 1)
        self.assertIn('需手动处理', task.notifications[0][0])
        self.assertNotIn('已登录回 profile-a1', task.notifications[0][1])

    def test_daily_task_requires_verified_profile_link(self):
        class FakeTask:
            _require_daily_profile = MultiAccountDailyTask._require_daily_profile

            def __init__(self, profiles, linked):
                self.profiles = profiles
                self.linked = linked
                self.config = {}

            def _load_profiles(self):
                return self.profiles

            def _link_daily_profile(self, _profile):
                return self.linked

        with self.assertRaisesRegex(Exception, '方案不存在'):
            FakeTask({}, True)._require_daily_profile('A1')

        failed = FakeTask({'A1': {}}, False)
        with self.assertRaisesRegex(Exception, '无法联动'):
            failed._require_daily_profile('A1')
        self.assertNotIn(CURRENT_ACCOUNT, failed.config)

        linked = FakeTask({'A1': {}}, True)
        self.assertTrue(linked._require_daily_profile('A1'))
        self.assertEqual(linked.config[CURRENT_ACCOUNT], 'A1')

    def test_dialog_login_click_retries_when_ui_does_not_transition(self):
        class FakeTask:
            _click_login_for_target = MultiAccountDailyTask._click_login_for_target

            def __init__(self):
                self._login_in_dialog = True
                self.clicks = 0
                self.transition_checks = 0

            def _confirm_target_before_login(self, _target):
                return True

            def _dialog_click_login(self):
                self.clicks += 1
                return True

            def wait_until(self, _condition, **_kwargs):
                self.transition_checks += 1
                return self.transition_checks >= 2

            def sleep(self, _seconds):
                pass

            def log_warning(self, *_args, **_kwargs):
                pass

            def log_error(self, *_args, **_kwargs):
                pass

            def screenshot(self, *_args):
                pass

            def tr(self, message):
                return message

        task = FakeTask()
        self.assertTrue(task._click_login_for_target('A3'))
        self.assertEqual(task.clicks, 2)
        self.assertEqual(task.transition_checks, 2)

    def test_login_postmessage_failure_switches_to_fresh_screen_click(self):
        class FakeTask:
            _click_login_for_target = MultiAccountDailyTask._click_login_for_target
            _main_login_screen_click = MultiAccountDailyTask._main_login_screen_click

            def __init__(self):
                self._login_in_dialog = False
                self.transition_checks = 0
                self.post_clicks = []
                self.screen_clicks = []
                self.ocr_calls = 0
                self.refreshes = 0
                self.front_calls = 0

            def _confirm_target_before_login(self, _target):
                return True

            def ocr(self):
                self.ocr_calls += 1
                # The fallback must use this new OCR frame, not the first box.
                x, y = (100, 200) if self.ocr_calls == 1 else (200, 300)
                return [AccountBox('登录', x=x, y=y, width=40, height=60)]

            def find_boxes(self, texts, boundary=None, match=None):
                return list(texts or []) if match == LOGIN_TEXTS else []

            def box_of_screen(self, *_args, **_kwargs):
                return object()

            def click(self, box, **_kwargs):
                self.post_clicks.append((box.x, box.y))
                return True

            def _refresh_hwnd_window_snapshot(self):
                self.refreshes += 1
                return True

            def _bring_account_window_to_front(self):
                self.front_calls += 1
                return True

            def _main_box_center_screen(self, box):
                return (box.x + box.width // 2, box.y + box.height // 2)

            def _screen_click(self, x, y, after_sleep=0):
                self.screen_clicks.append((x, y))
                return True

            def wait_until(self, _condition, **_kwargs):
                self.transition_checks += 1
                return self.transition_checks >= 2

            def sleep(self, _seconds):
                pass

            def log_info(self, *_args, **_kwargs):
                pass

            def log_warning(self, *_args, **_kwargs):
                pass

            def log_error(self, *_args, **_kwargs):
                pass

            def screenshot(self, *_args):
                pass

            def tr(self, message):
                return message

        task = FakeTask()
        self.assertTrue(task._click_login_for_target('A3'))
        self.assertEqual(task.post_clicks, [(100, 200)])
        self.assertEqual(task.screen_clicks, [(220, 330)])
        self.assertEqual(task.refreshes, 1)
        self.assertEqual(task.front_calls, 1)

    def test_login_screen_fallback_never_clicks_without_safe_coordinate(self):
        class FakeTask:
            _main_login_screen_click = MultiAccountDailyTask._main_login_screen_click

            def __init__(self):
                self.screen_clicks = []
                self.refreshes = 0

            def _refresh_hwnd_window_snapshot(self):
                self.refreshes += 1
                return True

            def _bring_account_window_to_front(self):
                return True

            def sleep(self, _seconds):
                pass

            def ocr(self):
                return [AccountBox('登录', x=10, y=20)]

            def find_boxes(self, texts, boundary=None, match=None):
                return list(texts or []) if match == LOGIN_TEXTS else []

            def box_of_screen(self, *_args, **_kwargs):
                return object()

            def _main_box_center_screen(self, _box):
                return None

            def _screen_click(self, *args, **kwargs):
                self.screen_clicks.append((args, kwargs))
                return True

            def log_info(self, *_args, **_kwargs):
                pass

            def log_warning(self, *_args, **_kwargs):
                pass

        task = FakeTask()
        self.assertFalse(task._main_login_screen_click())
        self.assertEqual(task.refreshes, 1)
        self.assertEqual(task.screen_clicks, [])

    def test_main_start_identifies_actual_account_before_daily_task(self):
        class FakeTask:
            _run_inner = MultiAccountDailyTask._run_inner

            def __init__(self):
                self.done_set = set()
                self.config = {}
                self.events = []
                self.targets = [None]

            def get_sequence_accounts(self):
                return ['A1', 'A3', 'A4']

            def _load_today_progress(self):
                return []

            def is_main(self, **_kwargs):
                return True

            def _switch_to_login(self):
                self.events.append('logout')

            def _detect_current_account_from_login(self):
                self.events.append('detect')
                return 'A4'

            def _same_account(self, left, right):
                return left == right

            def _is_done(self, account):
                return account in self.done_set

            def _select_and_login_specific(self, account):
                self.events.append(f'login:{account}')

            def _require_daily_profile(self, account):
                self.events.append(f'profile:{account}')
                self.config[CURRENT_ACCOUNT] = account

            def run_task_by_class(self, _task):
                self.events.append('daily')

            def _mark_done(self, account):
                self.done_set.add(account)

            def _save_today_progress(self):
                self.events.append('save')

            def ensure_main(self, **_kwargs):
                self.events.append('ensure_main')

            def _select_and_login_account(self):
                return self.targets.pop(0)

            def _login_back_to(self, account):
                self.events.append(f'return:{account}')

            def info_set(self, *_args, **_kwargs):
                pass

            def log_info(self, *_args, **_kwargs):
                pass

            def log_error(self, *_args, **_kwargs):
                pass

            def screenshot(self, *_args):
                pass

            def tr(self, message):
                return message

        task = FakeTask()
        task._run_inner()
        self.assertEqual(
            task.events,
            ['logout', 'detect', 'login:A4', 'profile:A4', 'daily',
             'save', 'ensure_main', 'logout', 'return:A4'],
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
                return [AccountBox('UTEST0007A'), AccountBox('199****0001')]

            def match_profile_from_login(self, name):
                return {
                    'UTEST0007A': 'profile-a1',
                    '199****0001': 'profile-a3',
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
        self.assertEqual(task.clicked, ['199****0001'])

    def test_click_account_list_prefers_safe_system_click_over_postmessage(self):
        class FakeTask:
            _main_box_center_screen = lambda self, box: (410, 520)

            def __init__(self):
                self._login_in_dialog = False
                self.screen_clicks = []
                self.post_clicks = []

            def ocr(self):
                return [AccountBox('199****0001', x=90, y=130)]

            def match_profile_from_login(self, name):
                return 'profile-a3' if name == '199****0001' else None

            def _screen_click(self, x, y, after_sleep=0):
                self.screen_clicks.append((x, y))
                return True

            def _account_list_expanded(self):
                return True

            def _bring_account_window_to_front(self):
                return True

            def sleep(self, _seconds):
                pass

            def click(self, account, after_sleep=0):
                self.post_clicks.append(account.name)
                return True

            def log_info(self, *args, **kwargs):
                pass

            def log_warning(self, *args, **kwargs):
                pass

            def log_error(self, *args, **kwargs):
                pass

        task = FakeTask()
        self.assertTrue(MultiAccountDailyTask._click_account_in_list(task, 'profile-a3'))
        self.assertEqual(task.screen_clicks, [(410, 520)])
        self.assertEqual(task.post_clicks, [])

    def test_click_account_list_falls_back_to_postmessage_without_safe_screen_point(self):
        class FakeTask:
            _main_box_center_screen = lambda self, box: None

            def __init__(self):
                self._login_in_dialog = False
                self.screen_clicks = []
                self.post_clicks = []

            def ocr(self):
                return [AccountBox('199****0001')]

            def match_profile_from_login(self, name):
                return 'profile-a3' if name == '199****0001' else None

            def _screen_click(self, x, y, after_sleep=0):
                self.screen_clicks.append((x, y))
                return True

            def click(self, account, after_sleep=0):
                self.post_clicks.append(account.name)
                return True

            def log_info(self, *args, **kwargs):
                pass

            def log_warning(self, *args, **kwargs):
                pass

            def log_error(self, *args, **kwargs):
                pass

        task = FakeTask()
        self.assertTrue(MultiAccountDailyTask._click_account_in_list(task, 'profile-a3'))
        self.assertEqual(task.screen_clicks, [])
        self.assertEqual(task.post_clicks, ['199****0001'])

    def test_main_mode_prefers_combo_list_client_target_over_selector_duplicate(self):
        class FakeTask:
            _click_account_in_list = MultiAccountDailyTask._click_account_in_list
            _find_and_click_account_in_combo_list = MultiAccountDailyTask._find_and_click_account_in_combo_list
            _box_center_screen = MultiAccountDailyTask._box_center_screen

            def __init__(self):
                self._login_in_dialog = False
                self.screen_clicks = []
                self.post_clicks = []
                self.main_ocr_calls = 0

            def _find_control_hwnd(self, class_name):
                return (88, (300, 400, 600, 580)) if class_name == 'ComboLBox' else (0, None)

            def _capture_hwnd_client(self, hwnd):
                return object(), (300, 400)

            def ocr(self, frame=None):
                if frame is None:
                    self.main_ocr_calls += 1
                    return [AccountBox('UTEST0007A', x=10, y=10)]
                return [
                    AccountBox('UTEST0007A', x=20, y=10),
                    AccountBox('199****0001', x=20, y=130),
                ]

            def match_profile_from_login(self, name):
                return {
                    'UTEST0007A': 'profile-current',
                    '199****0001': 'profile-a3',
                }.get(name)

            def _account_list_expanded(self):
                return True

            def _bring_account_window_to_front(self):
                return True

            def _screen_click(self, x, y, after_sleep=0):
                self.screen_clicks.append((x, y))
                return True

            def click(self, account, after_sleep=0):
                self.post_clicks.append(account.name)
                return True

            def sleep(self, _seconds):
                pass

            def log_info(self, *args, **kwargs):
                pass

            def log_warning(self, *args, **kwargs):
                pass

            def log_error(self, *args, **kwargs):
                pass

        task = FakeTask()
        self.assertTrue(task._click_account_in_list('profile-a3'))
        self.assertEqual(task.screen_clicks, [(370, 540)])
        self.assertEqual(task.post_clicks, [])
        self.assertEqual(task.main_ocr_calls, 0)
        self.assertEqual(task._last_account_click_mode, 'screen_combobox')

    def test_main_mode_falls_back_to_main_frame_when_combo_list_unavailable(self):
        class FakeTask:
            _click_account_in_list = MultiAccountDailyTask._click_account_in_list
            _main_box_center_screen = lambda self, box: (410, 520)

            def __init__(self):
                self._login_in_dialog = False
                self.screen_clicks = []
                self.post_clicks = []

            def _find_control_hwnd(self, class_name):
                return 0, None

            def ocr(self, frame=None):
                return [AccountBox('199****0001')]

            def match_profile_from_login(self, name):
                return 'profile-a3' if name == '199****0001' else None

            def _account_list_expanded(self):
                return True

            def _bring_account_window_to_front(self):
                return True

            def _screen_click(self, x, y, after_sleep=0):
                self.screen_clicks.append((x, y))
                return True

            def click(self, account, after_sleep=0):
                self.post_clicks.append(account.name)
                return True

            def sleep(self, _seconds):
                pass

            def log_info(self, *args, **kwargs):
                pass

            def log_warning(self, *args, **kwargs):
                pass

            def log_error(self, *args, **kwargs):
                pass

        task = FakeTask()
        self.assertTrue(task._click_account_in_list('profile-a3'))
        self.assertEqual(task.screen_clicks, [(410, 520)])
        self.assertEqual(task.post_clicks, [])
        self.assertEqual(task._last_account_click_mode, 'screen_main')

    def test_combo_screen_click_failure_is_not_recorded_as_postmessage(self):
        class FakeTask:
            _click_account_in_list = MultiAccountDailyTask._click_account_in_list
            _find_and_click_account_in_combo_list = MultiAccountDailyTask._find_and_click_account_in_combo_list
            _box_center_screen = MultiAccountDailyTask._box_center_screen

            def __init__(self):
                self._login_in_dialog = False
                self.screen_clicks = []
                self.post_clicks = []

            def _find_control_hwnd(self, class_name):
                return (88, (300, 400, 600, 580)) if class_name == 'ComboLBox' else (0, None)

            def _capture_hwnd_client(self, hwnd):
                return object(), (300, 400)

            def ocr(self, frame=None):
                return [AccountBox('199****0001', x=20, y=130)]

            def match_profile_from_login(self, name):
                return 'profile-a3' if name == '199****0001' else None

            def _account_list_expanded(self):
                return True

            def _bring_account_window_to_front(self):
                return True

            def _screen_click(self, x, y, after_sleep=0):
                self.screen_clicks.append((x, y))
                return False

            def click(self, account, after_sleep=0):
                self.post_clicks.append(account.name)
                return True

            def sleep(self, _seconds):
                pass

            def log_info(self, *args, **kwargs):
                pass

            def log_warning(self, *args, **kwargs):
                pass

            def log_error(self, *args, **kwargs):
                pass

        task = FakeTask()
        self.assertFalse(task._click_account_in_list('profile-a3'))
        self.assertEqual(task.screen_clicks, [(370, 540)])
        self.assertEqual(task.post_clicks, [])
        self.assertEqual(task._last_account_click_mode, 'screen_combobox_failed')

    def test_missing_foreground_confirmation_never_system_clicks(self):
        class FakeTask:
            _click_account_in_list = MultiAccountDailyTask._click_account_in_list
            _main_box_center_screen = lambda self, box: (410, 520)

            def __init__(self):
                self._login_in_dialog = False
                self.screen_clicks = []
                self.post_clicks = []

            def ocr(self, frame=None):
                return [AccountBox('199****0001')]

            def match_profile_from_login(self, name):
                return 'profile-a3' if name == '199****0001' else None

            def _screen_click(self, x, y, after_sleep=0):
                self.screen_clicks.append((x, y))
                return True

            def click(self, account, after_sleep=0):
                self.post_clicks.append(account.name)
                return True

            def log_info(self, *args, **kwargs):
                pass

            def log_warning(self, *args, **kwargs):
                pass

            def log_error(self, *args, **kwargs):
                pass

        task = FakeTask()
        self.assertTrue(task._click_account_in_list('profile-a3'))
        self.assertEqual(task.screen_clicks, [])
        self.assertEqual(task.post_clicks, ['199****0001'])

    def test_screen_click_checks_executor_before_cursor_move(self):
        class FakeExecutor:
            def __init__(self):
                self.check_calls = 0

            def check_enabled(self):
                self.check_calls += 1
                raise TaskDisabledException()

        class FakeTask:
            _screen_click = MultiAccountDailyTask._screen_click

            def __init__(self):
                self.executor = FakeExecutor()

            def sleep(self, _seconds):
                pass

        task = FakeTask()
        with patch('win32api.SetCursorPos') as set_cursor:
            with self.assertRaises(TaskDisabledException):
                task._screen_click(10, 20)
        self.assertEqual(task.executor.check_calls, 1)
        set_cursor.assert_not_called()

    def test_dialog_combo_list_uses_client_origin_and_target_bottom_after_duplicate_current(self):
        class FakeTask:
            _dialog_find_and_click_account = MultiAccountDailyTask._dialog_find_and_click_account
            _find_and_click_account_in_combo_list = MultiAccountDailyTask._find_and_click_account_in_combo_list
            _box_center_screen = MultiAccountDailyTask._box_center_screen

            def __init__(self, origin):
                self._login_in_dialog = True
                self.origin = origin
                self.screen_clicks = []
                self.post_clicks = []

            def _find_control_hwnd(self, class_name):
                if class_name == 'ComboLBox':
                    return 77, (self.origin[0], self.origin[1], self.origin[0] + 300, self.origin[1] + 180)
                return 0, None

            def _capture_hwnd_client(self, hwnd):
                if hwnd != 77:
                    raise AssertionError(f'expected ComboLBox hwnd 77, got {hwnd}')
                return object(), self.origin

            def _dialog_capture(self):
                return None, None

            def ocr(self, frame=None):
                return [
                    # selector 当前账号会在 ComboLBox 第一项重复出现；目标仍是列表底部。
                    AccountBox('UTEST0007A', x=20, y=10),
                    AccountBox('199****0005', x=20, y=50),
                    AccountBox('199****0001', x=20, y=130),
                ]

            def match_profile_from_login(self, name):
                return {
                    'UTEST0007A': 'profile-current',
                    '199****0005': 'profile-current',
                    '199****0001': 'profile-a3',
                }.get(name)

            def _screen_click(self, x, y, after_sleep=0):
                self.screen_clicks.append((x, y))
                return True

            def click(self, account, after_sleep=0):
                self.post_clicks.append(account.name)
                return True

            def log_info(self, *args, **kwargs):
                pass

            def log_warning(self, *args, **kwargs):
                pass

            def log_error(self, *args, **kwargs):
                pass

        for origin in ((100, 200), (100, 20)):
            with self.subTest(origin=origin):
                task = FakeTask(origin)
                ok, name = task._dialog_find_and_click_account('profile-a3')
                self.assertTrue(ok)
                self.assertEqual(name, '199****0001')
                self.assertEqual(task.screen_clicks, [(170, origin[1] + 140)])
                self.assertEqual(task.post_clicks, [])

    def test_wait_login_screen_stable_propagates_task_disabled_without_more_interaction(self):
        class FakeWindow:
            exists = True
            visible = True

            def __init__(self):
                self.front_count = 0

            def bring_to_front(self):
                self.front_count += 1

        class FakeTask:
            _wait_login_screen_stable = MultiAccountDailyTask._wait_login_screen_stable

            def __init__(self):
                self.hwnd = FakeWindow()
                self.ocr_calls = 0
                self.dialog_ocr_calls = 0

            def log_info(self, *args, **kwargs):
                pass

            def log_warning(self, *args, **kwargs):
                pass

            def log_error(self, *args, **kwargs):
                pass

            def ocr(self):
                self.ocr_calls += 1
                raise TaskDisabledException()

            def _ocr_login_dialog(self):
                self.dialog_ocr_calls += 1
                return []

            def sleep(self, _seconds):
                pass

        task = FakeTask()
        with self.assertRaises(TaskDisabledException):
            task._wait_login_screen_stable(time_out=1)
        self.assertEqual(task.ocr_calls, 1)
        self.assertEqual(task.dialog_ocr_calls, 0)
        self.assertEqual(task.hwnd.front_count, 0)

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
                    AccountBox('UTEST0007A'),
                    AccountBox('199****0001'),
                ]

            def match_profile_from_login(self, name):
                return {
                    'UTEST0007A': 'profile-a1',
                    '199****0001': 'profile-a3',
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
                if kwargs.get('time_out') == 20:
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
                return [AccountBox('199****0001')]

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
                if _kwargs.get('time_out') == 20:
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

    def test_selection_skips_click_when_closed_selector_already_matches_target(self):
        class FakeTask:
            _same_account = MultiAccountDailyTask._same_account

            def __init__(self):
                self.logs = []

            def _account_list_expanded(self):
                return False

            def _detect_current_account_from_login(self):
                return "profile-a3"

            def _open_account_list(self):
                raise AssertionError("matching closed selector must not be opened")

            def log_info(self, message, **_kwargs):
                self.logs.append(str(message))

            def log_warning(self, *_args, **_kwargs):
                pass

        task = FakeTask()
        self.assertTrue(
            MultiAccountDailyTask._select_account_with_retry(
                task, "profile-a3", max_retries=3,
            )
        )
        self.assertTrue(any("跳过重复点击" in message for message in task.logs))

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
        self.assertTrue(any(call.get('time_out') == 20 for call in task.wait_calls))
        self.assertEqual(
            sum('列表已收起' in message for message in task.info_logs),
            1,
        )

    def test_selection_reselects_only_after_stable_wrong_account_timeout(self):
        class FakeTask:
            def __init__(self):
                self.detected = iter([
                    # One initial closed-selector precheck, then the first
                    # selection remains on the wrong account for three frames.
                    "profile-a", "profile-a", "profile-a", "profile-a",
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
                if kwargs.get('time_out') == 20:
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
                    AccountBox("199****0014"),
                    AccountBox("UTEST1002A"),
                    AccountBox("199****0014"),
                    AccountBox("登录"),
                ]

            def match_profile_from_login(self, name):
                return {
                    "199****0014": "profile-a",
                    "UTEST1002A": "profile-b",
                }.get(name)

        profiles = MultiAccountDailyTask._visible_login_profiles(FakeTask())
        self.assertEqual(profiles, ["profile-a", "profile-b"])

    # ============ v1.03.74：下拉框收起/展开状态判定 ============

    def test_dropdown_ready_collapsed_single_mask_account(self):
        task = _fake_login_task(main_texts=['199****0006', '登录'])
        box = MultiAccountDailyTask.do_find_account_drop_down(task)
        self.assertIsNotNone(box)
        self.assertFalse(task._login_in_dialog)

    def test_dropdown_ready_expanded_multiple_accounts(self):
        # 列表已展开：账号条目 ≥2（掩码 + U 账号），仍视为登录就绪（返回下拉框）
        task = _fake_login_task(main_texts=['199****0014', 'UTEST1002A', '199****0006', '登入'])
        self.assertIsNotNone(MultiAccountDailyTask.do_find_account_drop_down(task))

    def test_dropdown_not_ready_without_login_text(self):
        task = _fake_login_task(main_texts=['199****0006'])
        self.assertIsNone(MultiAccountDailyTask.do_find_account_drop_down(task))

    def test_dropdown_dialog_fallback_sets_login_in_dialog(self):
        # 主窗口无特征 → 回退 #32770 登录对话框帧（U 扫码账号 + 登录文本）
        task = _fake_login_task(main_texts=[], dialog_texts=['UTEST1002A', '登录'])
        box = MultiAccountDailyTask.do_find_account_drop_down(task)
        self.assertIsNotNone(box)
        self.assertTrue(task._login_in_dialog)

    def test_dropdown_dialog_not_ready_when_only_launcher_texts(self):
        # 启动器界面（KURO GAMES / 修复，无登录文本无账号）→ 不命中
        task = _fake_login_task(main_texts=['KURO GAMES', '公告', '修复'])
        self.assertIsNone(MultiAccountDailyTask.do_find_account_drop_down(task))

    def test_account_list_expanded_true_with_two_entries(self):
        task = _fake_login_task(main_texts=['199****0014', 'UTEST1002A', '登入'])
        self.assertTrue(MultiAccountDailyTask._account_list_expanded(task))

    def test_account_list_expanded_false_with_single_entry(self):
        task = _fake_login_task(main_texts=['199****0014', '登入'])
        self.assertFalse(MultiAccountDailyTask._account_list_expanded(task))


if __name__ == "__main__":
    unittest.main()
