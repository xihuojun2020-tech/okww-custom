import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from custom_ok.ok.gui.MainWindow import MainWindow


class TestMainWindowStartup(unittest.TestCase):
    """Regression tests for the post-show integrity gate."""

    def _window(self, **attrs):
        window = MainWindow.__new__(MainWindow)
        window._startup_post_show_scheduled = False
        window._startup_post_show_complete = False
        window._startup_args = {}
        window._integrity_review_blocked = False
        window.bring_to_front = Mock()
        window._review_account_integrity_before_start = Mock(return_value=True)
        window._check_okscript_args = Mock()
        window.main_window_config = {"last_version": "1.08.00"}
        window.version = "1.08.00"
        window.config = {}
        window.basic_global_config = {}
        window.app = Mock()
        window.app.start_controller.start = Mock()
        window.app.start = Mock()
        window.handler = Mock()
        window.show_startup_version_change_notice = Mock()
        window.__dict__.update(attrs)
        return window

    @patch("custom_ok.ok.gui.MainWindow.QTimer.singleShot")
    def test_post_show_review_is_scheduled_once(self, single_shot):
        window = self._window()

        self.assertTrue(window._schedule_post_show_startup())
        self.assertFalse(window._schedule_post_show_startup())

        single_shot.assert_called_once_with(150, window._run_post_show_startup)

    def test_failed_review_blocks_all_automatic_start_actions(self):
        window = self._window(
            _startup_args={"task": 3, "exit": True},
            _review_account_integrity_before_start=Mock(return_value=False),
        )

        window._run_post_show_startup()

        self.assertTrue(window._integrity_review_blocked)
        window.app.start_controller.start.assert_not_called()
        window._check_okscript_args.assert_not_called()
        window.bring_to_front.assert_called_once_with()

    @patch("custom_ok.ok.gui.MainWindow.QTimer.singleShot")
    def test_first_show_completes_readiness_before_deferring_review(self, single_shot):
        events = []
        window = self._window()
        window._complete_window_readiness = Mock(side_effect=lambda: events.append("ready"))
        window.bring_to_front = Mock(side_effect=lambda: events.append("front"))
        window._schedule_post_show_startup = Mock(side_effect=lambda: events.append("deferred"))

        window._handle_first_show()

        self.assertEqual(["ready", "deferred"], events)
        single_shot.assert_called_once_with(0, window.bring_to_front)

    def test_duplicate_post_show_callback_cannot_start_twice(self):
        window = self._window(_startup_args={"task": 0, "exit": False})

        window._run_post_show_startup()
        window._run_post_show_startup()

        self.assertTrue(window._startup_post_show_complete)
        window._review_account_integrity_before_start.assert_called_once_with()
        window._check_okscript_args.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
