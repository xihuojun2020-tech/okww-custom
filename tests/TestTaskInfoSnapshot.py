import unittest
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

from custom_ok.ok.gui.tasks.TaskTab import TaskTab


class TestTaskInfoSnapshot(unittest.TestCase):
    def test_background_writer_during_ten_thousand_refreshes(self):
        panel = Mock()
        panel.current_task_name = ''
        panel.tr.side_effect = lambda text: text
        task = SimpleNamespace(enabled=False, start_time=0, info={'stage': 'daily'})
        stopped = threading.Event()

        def write():
            while not stopped.is_set():
                task.info['progress'] = 'running'
                task.info.pop('progress', None)
                stopped.wait(.0001)

        worker = threading.Thread(target=write)
        worker.start()
        try:
            with patch('custom_ok.ok.gui.tasks.TaskTab.og',
                       SimpleNamespace(app=SimpleNamespace(tr=lambda text: text))):
                for _ in range(10000):
                    TaskTab.update_task_info(panel, task)
                    rows = panel.task_info_table.setRowCount.call_args.args[0]
                    self.assertEqual(rows, len(panel.task_summary.setText.call_args.args[0].splitlines()))
                    panel.reset_mock()
        finally:
            stopped.set()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())

    def test_updates_during_render_use_one_snapshot(self):
        panel = Mock()
        panel.current_task_name = ''
        panel.tr.side_effect = lambda text: text
        task = SimpleNamespace(enabled=False, start_time=0, info={})
        app = SimpleNamespace(tr=lambda text: text)

        def mutate(value):
            task.info['added_while_rendering'] = 'new'
            task.info.pop('stage', None)
            return value

        with patch('custom_ok.ok.gui.tasks.TaskTab.og', SimpleNamespace(app=app)), \
                patch('src.account_display.account_option_label', side_effect=mutate):
            for _ in range(10000):
                task.info = {'Status Account': 'A1', 'stage': 'daily'}
                TaskTab.update_task_info(panel, task)
                panel.task_info_table.setRowCount.assert_called_with(2)
                self.assertIn('stage', panel.task_summary.setText.call_args.args[0])
                self.assertNotIn('added_while_rendering', panel.task_summary.setText.call_args.args[0])
                panel.reset_mock()


if __name__ == '__main__':
    unittest.main()
