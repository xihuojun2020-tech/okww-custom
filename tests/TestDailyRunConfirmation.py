import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget, QMessageBox
from ok import TaskDisabledException
from src.gui.DailyRunConfirmation import DailyRunConfirmation
from src.task.DailyTask import DailyTask
from src.config_integrity import ConfigIntegrityBlocked
from src.account_repository import ProfileEditScope
from tests.fixture_support import make_account_environment


class TestDailyRunConfirmation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_worker_confirmation_accept_cancel_timeout_stop_and_destroy(self):
        for action in ('accept', 'cancel', 'timeout', 'stop', 'destroy'):
            with self.subTest(action=action):
                parent = QWidget()
                bridge = DailyRunConfirmation(parent)
                stopped = threading.Event()
                def check():
                    if stopped.is_set():
                        raise TaskDisabledException('stopped')
                task = SimpleNamespace(executor=SimpleNamespace(check_enabled=check, exit_event=threading.Event()))
                result = []
                def work():
                    try:
                        result.append(bridge.confirm(task, 'Synthetic A1', timeout=0.3))
                    except TaskDisabledException:
                        result.append('stopped')
                thread = threading.Thread(target=work)
                thread.start()
                handled = False
                end = time.monotonic() + 3
                while thread.is_alive() and time.monotonic() < end:
                    self.app.processEvents()
                    if bridge.dialogs and not handled:
                        dialog = next(iter(bridge.dialogs.values()))
                        if action == 'accept':
                            dialog.done(QMessageBox.Yes)
                        elif action == 'cancel':
                            dialog.reject()
                        elif action == 'stop':
                            stopped.set()
                        elif action == 'destroy':
                            parent.deleteLater()
                            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                        handled = True
                    time.sleep(0.005)
                thread.join(1)
                self.assertFalse(thread.is_alive())
                self.app.processEvents()
                self.assertEqual(result, [True if action == 'accept' else 'stopped' if action == 'stop' else False])
                if action != 'destroy':
                    self.assertFalse(bridge.dialogs)
                    parent.deleteLater()

    def test_real_daily_boundary_rejects_cancel_and_changed_revision(self):
        for answer in ('cancel', 'changed', 'accept'):
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as temp:
                env = make_account_environment(temp)
                task = object.__new__(DailyTask)
                task.integrity_service = env.integrity
                task.config = {'Daily Profile': 'A1'}
                task._executor = SimpleNamespace()
                task._publish_daily_stage = Mock()
                task.validate_daily_tasks = Mock()
                task.log_info = Mock()
                task.run_task_by_class = Mock()
                task.record_last_completed = Mock()
                def confirm():
                    if answer == 'changed':
                        p = env.repository.list_profiles()[0]
                        env.repository.publish_profile(ProfileEditScope(p.profile_id, p.revision), {
                            'account': p.account, 'tasks': {**p.tasks, 'Which Tacet Suppression to Farm': 7}})
                    return answer != 'cancel'
                task._confirm_standalone_profile = Mock(side_effect=confirm)
                expected = TaskDisabledException if answer == 'cancel' else ConfigIntegrityBlocked if answer == 'changed' else RuntimeError
                with patch('src.task.DailyTask.require_account_runtime_for_task'), \
                        patch('src.task.DailyTask.get_default_repository', return_value=env.repository), \
                        patch('src.task.DailyTask.WWOneTimeTask.run', side_effect=RuntimeError('before-game')) as entry:
                    with self.assertRaises(expected):
                        task.run()
                    self.assertEqual(entry.call_count, 1 if answer == 'accept' else 0)
                task.run_task_by_class.assert_not_called()
                task.record_last_completed.assert_not_called()
                self.assertIsNone(task._verified_profile_snapshot)

    def test_multi_snapshot_does_not_prompt_or_persist_selection(self):
        from src.sequence_repository import SequenceRepository
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(temp)
            task = object.__new__(DailyTask)
            task.integrity_service = env.integrity
            task.config = {'Daily Profile': 'A3'}
            task._executor = SimpleNamespace()
            task._confirm_standalone_profile = Mock(side_effect=AssertionError('unexpected prompt'))
            snapshot = SequenceRepository(env.repository).create_run_snapshot('S1')
            task.bind_verified_profile('A1', snapshot_profile=snapshot.profiles[0])
            task._run_daily_inner = task._ensure_run_account_confirmation
            with patch('src.task.DailyTask.get_default_repository', return_value=env.repository):
                task.run()
            self.assertEqual(task.config['Daily Profile'], 'A3')
            task._confirm_standalone_profile.assert_not_called()


if __name__ == '__main__':
    unittest.main()
