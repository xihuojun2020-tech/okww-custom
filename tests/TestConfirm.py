import unittest
from unittest.mock import Mock
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.BaseWWTask import BaseWWTask
from src.task.FiveToOneTask import FiveToOneTask

config['debug'] = True


class TestConfirm(TaskTestCase):
    task_class = FiveToOneTask
    config = config

    def test_confirm(self):
        self.task.do_reset_to_false()
        self.set_image('tests/images/confirm_highlight.png')
        confirm_btn_hcenter_vcenter = self.task.find_one('confirm_btn_hcenter_vcenter')
        self.task.log_debug(f'confirm_btn_hcenter_vcenter {confirm_btn_hcenter_vcenter}')
        self.assertIsNotNone(confirm_btn_hcenter_vcenter)


class TestBaseWWTaskConfirm(unittest.TestCase):
    def setUp(self):
        self.task = BaseWWTask.__new__(BaseWWTask)
        self.task.wait_click_feature = Mock()

    def test_click_confirm_passes_timeout_and_returns_success(self):
        self.task.wait_click_feature.return_value = True

        result = self.task.click_confirm(timeout=10)

        self.assertTrue(result)
        self.task.wait_click_feature.assert_called_once_with(
            ['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter'],
            relative_x=-1,
            raise_if_not_found=False,
            threshold=0.6,
            time_out=10,
        )

    def test_click_confirm_returns_failure(self):
        self.task.wait_click_feature.return_value = False

        result = self.task.click_confirm(timeout=3)

        self.assertFalse(result)
        self.task.wait_click_feature.assert_called_once_with(
            ['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter'],
            relative_x=-1,
            raise_if_not_found=False,
            threshold=0.6,
            time_out=3,
        )


if __name__ == '__main__':
    unittest.main()
