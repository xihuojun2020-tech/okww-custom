import unittest
from types import SimpleNamespace
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

    def test_refresh_gui_never_updates_qt_widgets_from_worker_thread(self):
        task = DailyTask.__new__(DailyTask)
        updates = []
        card = SimpleNamespace(task=task, update_config=lambda: updates.append('updated'))
        fake_og = SimpleNamespace(
            main_window=SimpleNamespace(
                onetime_tab=SimpleNamespace(card_widgets=[card]),
            ),
        )
        gui_thread = object()

        with patch('ok.og', fake_og), \
                patch('src.task.DailyTask.QApplication') as application, \
                patch('src.task.DailyTask.QThread') as q_thread:
            application.instance.return_value.thread.return_value = gui_thread
            q_thread.currentThread.return_value = object()
            self.assertFalse(task._refresh_gui())

        self.assertEqual([], updates)

    def test_refresh_gui_still_updates_task_card_on_gui_thread(self):
        task = DailyTask.__new__(DailyTask)
        updates = []
        card = SimpleNamespace(task=task, update_config=lambda: updates.append('updated'))
        fake_og = SimpleNamespace(
            main_window=SimpleNamespace(
                onetime_tab=SimpleNamespace(card_widgets=[card]),
            ),
        )
        gui_thread = object()

        with patch('ok.og', fake_og), \
                patch('src.task.DailyTask.QApplication') as application, \
                patch('src.task.DailyTask.QThread') as q_thread:
            application.instance.return_value.thread.return_value = gui_thread
            q_thread.currentThread.return_value = gui_thread
            self.assertTrue(task._refresh_gui())

        self.assertEqual(['updated'], updates)


if __name__ == '__main__':
    unittest.main()
