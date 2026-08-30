import unittest
from unittest.mock import Mock

from src.task.DiagnosisTask import DiagnosisTask


class TestDiagnosisTask(unittest.TestCase):
    def test_choose_level_uses_task_logger_and_click_flow(self):
        task = object.__new__(DiagnosisTask)
        task.log_info = Mock()
        task.click_relative = Mock()
        task.sleep = Mock()
        task.wait_click_feature = Mock()

        task.choose_level(2)

        task.log_info.assert_called_once()
        task.click_relative.assert_called_once()
        self.assertEqual(task.wait_click_feature.call_count, 3)


if __name__ == "__main__":
    unittest.main()
