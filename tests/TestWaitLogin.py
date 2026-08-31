import unittest
from unittest.mock import patch

from src.task.BaseWWTask import BaseWWTask, LOGIN_CLICK_SETTLE_TIME, LOGIN_TEXTS
from src.win32_login_input import LoginClickDelivery


class TextBox:
    def __init__(self, name, x=10, y=20, width=30, height=40):
        self.name = name
        self.x = x
        self.y = y
        self.width = width
        self.height = height


class FakeLoginTask:
    """Drives BaseWWTask.wait_login with scripted OCR frames.

    Each entry in frames is the list of TextBox returned by one ocr() call,
    so a frame sequence like [[login], []] simulates a login button that
    disappears while the game's own auto login is running (#1356).
    """

    def __init__(self, frames):
        self.frames = list(frames)
        self.logged_in = False
        self.debug = False
        self.clicked = []
        self.slept = []

    def in_team_and_world(self):
        return False

    def handle_monthly_card(self):
        return False

    def find_one(self, *args, **kwargs):
        return None

    def box_of_screen(self, *args, **kwargs):
        return args

    def ocr(self, log=False):
        return self.frames.pop(0) if self.frames else []

    def find_boxes(self, texts, boundary=None, match=None):
        if not texts:
            return None
        if match == LOGIN_TEXTS:
            return [b for b in texts
                    if 'log' in b.name.lower() or '登录' in b.name or '登入' in b.name] or None
        if match == "+86":
            return [b for b in texts if '+86' in b.name] or None
        return None

    def _click_login_box(self, target, after_sleep=0):
        self.clicked.append([b.name for b in target])
        return True

    def click(self, *_args, **_kwargs):
        raise AssertionError('PC login path must not use PostMessage')

    def sleep(self, timeout):
        self.slept.append(timeout)

    def log_info(self, *args, **kwargs):
        pass

    def log_debug(self, *args, **kwargs):
        pass


class TestWaitLogin(unittest.TestCase):

    def test_pc_login_click_uses_main_hwnd_capture_origin_and_sendinput(self):
        class Hwnd:
            hwnd = 10

            @staticmethod
            def get_capture_origin():
                return 100, 200

        class Task:
            hwnd = Hwnd()
            executor = None

            @staticmethod
            def _main_window_identity():
                return 10, 99

            _main_box_center_screen = BaseWWTask._main_box_center_screen

            @staticmethod
            def log_warning(*_args, **_kwargs):
                pass

            @staticmethod
            def sleep(_seconds):
                raise AssertionError('after_sleep=0 must not sleep')

        delivered = LoginClickDelivery(True, 'delivered', 10, 10, 11, 99, (125, 240))
        with patch('src.task.BaseWWTask.send_input_click', return_value=delivered) as send:
            result = BaseWWTask._click_login_box(Task(), [TextBox('Log In')], after_sleep=0)

        self.assertTrue(result)
        send.assert_called_once_with(10, 99, (125, 240))

    def test_transient_login_button_is_not_clicked(self):
        # Global server auto login: the login button disappears by itself,
        # clicking it would pop up the account/password dialog (#1356).
        task = FakeLoginTask(frames=[[TextBox('Log In')], []])

        result = BaseWWTask.wait_login(task)

        self.assertFalse(result)
        self.assertEqual(task.clicked, [])
        self.assertEqual(task.slept, [LOGIN_CLICK_SETTLE_TIME])

    def test_persistent_login_button_is_clicked(self):
        # No saved credentials: the login button stays, so it must be clicked.
        task = FakeLoginTask(frames=[[TextBox('Log In')], [TextBox('Log In')]])

        result = BaseWWTask.wait_login(task)

        self.assertFalse(result)
        self.assertEqual(task.clicked, [['Log In']])

    def test_no_click_and_no_settle_when_phone_login_is_already_shown(self):
        # +86 phone login present on the first frame: the pre-existing guard
        # must skip both the click and the settle wait entirely.
        task = FakeLoginTask(frames=[[TextBox('登录'), TextBox('+86 手机号')]])

        result = BaseWWTask.wait_login(task)

        self.assertFalse(result)
        self.assertEqual(task.clicked, [])
        self.assertEqual(task.slept, [])

    def test_no_click_when_phone_login_appears_after_settle(self):
        # CN phone-number login screen (+86) must never be auto clicked,
        # even when it only shows up on the confirmation frame.
        task = FakeLoginTask(frames=[[TextBox('登录')],
                                     [TextBox('登录'), TextBox('+86 手机号')]])

        result = BaseWWTask.wait_login(task)

        self.assertFalse(result)
        self.assertEqual(task.clicked, [])


if __name__ == "__main__":
    unittest.main()
