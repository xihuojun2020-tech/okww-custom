import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.gui.TaskStatusWindow import TaskStatusWindow, exclude_window_from_capture
from src.task_status import publish_task_status


class FakeUser32:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def SetWindowDisplayAffinity(self, hwnd, affinity):
        self.calls.append((int(hwnd), int(affinity)))
        return self.result


class FakeTask:
    def __init__(self, name="Multi Account Daily", start_time=100.0):
        self.name = name
        self.start_time = start_time
        self.info = {}
        self.executor = None
        self.running = True

    def info_set(self, key, value):
        self.info[key] = value

    def tr(self, value):
        return value


class FakeExecutor:
    def __init__(self, current_task=None):
        self.paused = False
        self.current_task = current_task
        self.device_manager = type("DeviceManager", (), {"hwnd_window": None})()
        if current_task is not None:
            current_task.executor = self


class TestTaskStatusWindow(unittest.TestCase):
    def test_status_display_expands_account_without_changing_published_status(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from tests.fixture_support import make_account_environment
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(Path(temp))
            task = FakeTask()
            publish_task_status(task, account='A3')
            before = dict(task.info)
            with patch('src.account_repository.get_default_repository', return_value=env.repository):
                window = TaskStatusWindow(FakeExecutor(task))
                try:
                    window.refresh()
                    self.assertIn('A3-测试账号三-199****0003', window.label.text())
                    self.assertEqual(task.info, before)
                finally:
                    window.shutdown()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_window_is_topmost_click_through_and_non_activating(self):
        window = TaskStatusWindow(FakeExecutor())
        flags = window.windowFlags()
        self.assertTrue(flags & Qt.WindowStaysOnTopHint)
        self.assertTrue(flags & Qt.WindowTransparentForInput)
        self.assertTrue(flags & Qt.WindowDoesNotAcceptFocus)
        window.shutdown()

    def test_capture_exclusion_uses_wda_excludefromcapture(self):
        user32 = FakeUser32(1)
        self.assertTrue(exclude_window_from_capture(123, user32=user32))
        self.assertEqual([(123, 0x11)], user32.calls)

    def test_error_is_visible_after_current_task_is_cleared(self):
        task = FakeTask()
        executor = FakeExecutor(task)
        task.info["Error"] = "登录界面等待超时"
        window = TaskStatusWindow(executor)
        window.on_task(task)
        executor.current_task = None
        window.on_task(None)
        window.refresh()
        self.assertIn("登录界面等待超时", window.label.text())
        self.assertTrue(window.isVisible())
        window.shutdown()

    def test_status_publication_failure_does_not_change_task(self):
        task = FakeTask()
        executor = FakeExecutor(task)
        task.info_set = lambda key, value: (_ for _ in ()).throw(RuntimeError("ui unavailable"))
        publish_task_status(task, stage="账号切换", detail="等待界面稳定")
        self.assertIs(executor.current_task, task)


if __name__ == "__main__":
    unittest.main()
