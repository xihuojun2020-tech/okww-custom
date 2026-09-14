import unittest
from unittest.mock import Mock, call

from src.task.BaseWWTask import BaseWWTask


class TestSkipDialogConfirm(unittest.TestCase):

    def setUp(self):
        self.task = BaseWWTask.__new__(BaseWWTask)
        self.task.find_one = Mock()
        self.task.click = Mock()
        self.task.sleep = Mock()

    def test_clicks_checkbox_then_confirm(self):
        confirm = object()
        checkbox = object()
        self.task.find_one.side_effect = [confirm, checkbox]

        clicked = self.task.click_skip_dialog_confirm()

        self.assertTrue(clicked)
        self.task.find_one.assert_has_calls([
            call(
                ['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter'],
                horizontal_variance=0.1,
                vertical_variance=0.1,
            ),
            call(
                'skip_dialog_check',
                horizontal_variance=0.1,
                vertical_variance=0.1,
            ),
        ])
        self.assertEqual(self.task.click.call_args_list, [call(checkbox), call(confirm)])
        self.assertEqual(self.task.sleep.call_args_list, [call(0.5), call(0.5), call(0.2)])

    def test_does_nothing_when_dialog_is_absent(self):
        self.task.find_one.return_value = None

        clicked = self.task.click_skip_dialog_confirm()

        self.assertFalse(clicked)
        self.task.click.assert_not_called()
        self.task.sleep.assert_not_called()

    def test_waits_for_optional_dialog_without_raising(self):
        self.task.wait_until = Mock(return_value=True)

        clicked = self.task.wait_click_skip_dialog_confirm(time_out=2)

        self.assertTrue(clicked)
        self.task.wait_until.assert_called_once_with(
            self.task.click_skip_dialog_confirm,
            time_out=2,
            raise_if_not_found=False,
        )

    def test_teleport_delegates_to_verified_navigation(self):
        self.task.require_game_frame=Mock(return_value=object())
        self.task._travel_button=Mock(return_value=object())
        self.task._navigate_travel=Mock(return_value=True)
        self.assertTrue(self.task.click_traval_button())
        self.task._navigate_travel.assert_called_once()
        self.task.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
