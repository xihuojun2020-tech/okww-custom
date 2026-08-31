import unittest

from src.win32_login_input import (
    _normalize_absolute_point,
    force_foreground,
    send_input_click,
)


class FakeWin32Api:
    def __init__(self):
        self.windows = {}
        self.foreground = 0
        self.hit = 0
        self.allow_foreground = True
        self.send_count = 3
        self.sent_points = []
        self.attached = []

    def add_window(
        self,
        hwnd,
        *,
        pid,
        rect,
        root=None,
        root_window=None,
        parent=0,
        visible=True,
        enabled=True,
        iconic=False,
        thread_id=None,
    ):
        self.windows[hwnd] = {
            "pid": pid,
            "rect": rect,
            "root_owner": root or hwnd,
            "root_window": root_window or ((root or hwnd) if parent else hwnd),
            "parent": parent,
            "visible": visible,
            "enabled": enabled,
            "iconic": iconic,
            "thread_id": thread_id or (pid + 1000),
        }

    def is_window(self, hwnd):
        return hwnd in self.windows

    def is_window_visible(self, hwnd):
        return bool(self.windows[hwnd]["visible"])

    def is_window_enabled(self, hwnd):
        return bool(self.windows[hwnd]["enabled"])

    def window_thread_process_id(self, hwnd):
        window = self.windows[hwnd]
        return window["thread_id"], window["pid"]

    def root_owner(self, hwnd):
        return self.windows[hwnd]["root_owner"]

    def root_window(self, hwnd):
        return self.windows[hwnd]["root_window"]

    def is_child(self, parent, child):
        current = self.windows.get(child, {}).get("parent", 0)
        while current:
            if current == parent:
                return True
            current = self.windows.get(current, {}).get("parent", 0)
        return False

    def is_iconic(self, hwnd):
        return bool(self.windows[hwnd]["iconic"])

    def restore_window(self, hwnd):
        self.windows[hwnd]["iconic"] = False

    def current_thread_id(self):
        return 7000

    def get_foreground_window(self):
        return self.foreground

    def attach_thread_input(self, source, target, attach):
        self.attached.append((source, target, bool(attach)))
        return True

    def bring_window_to_top(self, _hwnd):
        return True

    def set_foreground_window(self, hwnd):
        if self.allow_foreground:
            self.foreground = hwnd
            return True
        return False

    def window_rect(self, hwnd):
        return self.windows[hwnd]["rect"]

    def virtual_screen(self):
        return -1920, 0, 3840, 1080

    def window_from_point(self, _point):
        return self.hit

    def send_mouse_click(self, point, virtual_screen):
        self.sent_points.append((point, virtual_screen))
        return self.send_count


def _ready_api():
    api = FakeWin32Api()
    api.add_window(10, pid=99, rect=(100, 100, 900, 700), root=10)
    api.add_window(11, pid=99, rect=(200, 200, 400, 300), root=10, parent=10)
    api.foreground = 10
    api.hit = 11
    return api


class TestWin32LoginInput(unittest.TestCase):
    def test_click_accepts_related_foreground_and_hit_window(self):
        api = _ready_api()

        result = send_input_click(10, 99, (250, 250), api=api)

        self.assertTrue(result.delivered)
        self.assertEqual(result.reason, "delivered")
        self.assertEqual(result.hit_hwnd, 11)
        self.assertEqual(api.sent_points, [((250, 250), (-1920, 0, 3840, 1080))])

    def test_click_rejects_same_process_but_unrelated_window(self):
        api = _ready_api()
        api.add_window(20, pid=99, rect=(200, 200, 400, 300), root=20)
        api.hit = 20

        result = send_input_click(10, 99, (250, 250), api=api)

        self.assertFalse(result.delivered)
        self.assertEqual(result.reason, "point-target-mismatch")
        self.assertEqual(api.sent_points, [])

    def test_click_rejects_target_pid_mismatch(self):
        api = _ready_api()

        result = send_input_click(10, 100, (250, 250), api=api)

        self.assertFalse(result.delivered)
        self.assertEqual(result.reason, "target-pid-mismatch")
        self.assertEqual(api.sent_points, [])

    def test_click_rejects_hidden_or_disabled_target(self):
        for field, reason in (("visible", "target-not-visible"), ("enabled", "target-disabled")):
            with self.subTest(field=field):
                api = _ready_api()
                api.windows[10][field] = False
                result = send_input_click(10, 99, (250, 250), api=api)
                self.assertFalse(result.delivered)
                self.assertEqual(result.reason, reason)
                self.assertEqual(api.sent_points, [])

    def test_click_rejects_virtual_screen_and_target_rect_bounds(self):
        cases = [
            ((2000, 200), "point-outside-virtual-screen"),
            ((50, 200), "point-outside-target"),
        ]
        for point, reason in cases:
            with self.subTest(point=point):
                api = _ready_api()
                result = send_input_click(10, 99, point, api=api)
                self.assertFalse(result.delivered)
                self.assertEqual(result.reason, reason)
                self.assertEqual(api.sent_points, [])

    def test_click_rejects_missing_hit_or_hit_pid_mismatch(self):
        api = _ready_api()
        api.hit = 0
        result = send_input_click(10, 99, (250, 250), api=api)
        self.assertFalse(result.delivered)
        self.assertEqual(result.reason, "point-no-window")

        api = _ready_api()
        api.add_window(12, pid=100, rect=(200, 200, 400, 300), root=10, parent=10)
        api.hit = 12
        result = send_input_click(10, 99, (250, 250), api=api)
        self.assertFalse(result.delivered)
        self.assertEqual(result.reason, "point-pid-mismatch")

    def test_partial_sendinput_is_not_delivery(self):
        api = _ready_api()
        api.send_count = 2

        result = send_input_click(10, 99, (250, 250), api=api)

        self.assertFalse(result.delivered)
        self.assertEqual(result.reason, "sendinput-partial-2-of-3")

    def test_force_foreground_restores_and_detaches_threads(self):
        api = _ready_api()
        api.add_window(30, pid=200, rect=(0, 0, 100, 100), root=30, thread_id=330)
        api.foreground = 30
        api.windows[10]["iconic"] = True

        result = force_foreground(10, 99, api=api)

        self.assertTrue(result.ready)
        self.assertEqual(result.foreground_hwnd, 10)
        self.assertFalse(api.windows[10]["iconic"])
        attached = [entry for entry in api.attached if entry[2]]
        detached = [entry for entry in api.attached if not entry[2]]
        self.assertTrue(attached)
        self.assertEqual(detached, list(reversed([(a, b, False) for a, b, _ in attached])))

    def test_force_foreground_activates_owned_dialog_instead_of_owner_main_window(self):
        api = FakeWin32Api()
        api.add_window(10, pid=99, rect=(0, 0, 1000, 800), root=10)
        api.add_window(20, pid=99, rect=(200, 150, 800, 650), root=10)
        api.add_window(
            21,
            pid=99,
            rect=(250, 200, 750, 300),
            root=10,
            root_window=20,
            parent=20,
        )
        api.foreground = 10

        result = force_foreground(21, 99, api=api)

        self.assertTrue(result.ready)
        self.assertEqual(result.foreground_hwnd, 20)

    def test_force_foreground_refusal_stops_delivery(self):
        api = _ready_api()
        api.add_window(30, pid=200, rect=(0, 0, 100, 100), root=30)
        api.foreground = 30
        api.allow_foreground = False

        result = send_input_click(10, 99, (250, 250), api=api)

        self.assertFalse(result.delivered)
        self.assertEqual(result.reason, "foreground-mismatch")
        self.assertEqual(api.sent_points, [])

    def test_virtual_desktop_absolute_normalization_handles_negative_origin(self):
        self.assertEqual(_normalize_absolute_point((-1920, 0), (-1920, 0, 3840, 1080)), (0, 0))
        self.assertEqual(_normalize_absolute_point((1919, 1079), (-1920, 0, 3840, 1080)), (65535, 65535))
        center = _normalize_absolute_point((0, 540), (-1920, 0, 3840, 1080))
        self.assertIn(center[0], (32775, 32776))
        self.assertIn(center[1], (32797, 32798))


if __name__ == "__main__":
    unittest.main()
