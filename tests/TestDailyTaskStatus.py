import unittest
from unittest.mock import patch

from src.task.DailyTask import DailyTask


class TestDailyTaskStatus(unittest.TestCase):
    def test_publish_daily_stage_includes_active_account(self):
        task = DailyTask.__new__(DailyTask)
        task.get_active_profile_name = lambda: 'A3'
        with patch('src.task.DailyTask.publish_task_status') as publish:
            task._publish_daily_stage('清理体力', '无音区')
        publish.assert_called_once_with(
            task,
            account='A3',
            stage='清理体力',
            detail='无音区',
        )

    def test_publish_daily_stage_prefers_multi_account_runtime_label(self):
        task = DailyTask.__new__(DailyTask)
        task._runtime_status_account = 'A4'
        task.get_active_profile_name = lambda: 'internal-profile-name'
        with patch('src.task.DailyTask.publish_task_status') as publish:
            task._publish_daily_stage('每日任务', '正在领取奖励')
        publish.assert_called_once_with(
            task,
            account='A4',
            stage='每日任务',
            detail='正在领取奖励',
        )


if __name__ == '__main__':
    unittest.main()
