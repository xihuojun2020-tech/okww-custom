import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np

from ok import TaskDisabledException
from src.config_integrity import ConfigIntegrityBlocked
from src.runtime.game_runtime_errors import FrameUnavailable, GameProcessLost
from src.task.MultiAccountDailyTask import MultiAccountDailyTask


class TestMultiStartState(unittest.TestCase):
    def test_redispatch_preserves_real_snapshot_and_initial_account(self):
        import tempfile
        from tests.fixture_support import make_account_environment, synthetic_identity
        from src.task.MultiAccountDailyTask import CURRENT_ACCOUNT, CURRENT_SEQUENCE
        from src.runtime.game_runtime_errors import StartupStateChanged
        from src.runtime.task_run_coordinator import TaskRunCoordinator
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(temp)
            task = object.__new__(MultiAccountDailyTask)
            task.integrity_service = env.integrity
            task.config = {CURRENT_ACCOUNT: 'A1', CURRENT_SEQUENCE: 'S1'}
            task.run_coordinator = TaskRunCoordinator()
            task.done_set = set()
            task._load_today_progress = Mock(return_value=[])
            task._classify_start_state = Mock(side_effect=['login', 'world'])
            task._is_done = Mock(return_value=True)
            task._next_target_account = Mock(side_effect=['A1', None])
            task.log_info = task.info_set = task._notify_user = Mock()
            task._switch_to_login = Mock()
            snapshots = []
            def changed():
                snapshots.append(task._active_run_snapshot)
                task.config[CURRENT_ACCOUNT] = 'A3'
                raise StartupStateChanged('world')
            task._select_and_login_account = changed
            with patch('src.task.MultiAccountDailyTask.get_default_repository', return_value=env.repository):
                task._run_inner()
            self.assertIs(task._active_run_snapshot, snapshots[0])
            self.assertEqual(task._run_return_profile_id, synthetic_identity('A1')['profile_id'])
            self.assertFalse(task._starting_from_login)
            task._switch_to_login.assert_not_called()

    def task(self, worlds=(False, True, True), login=False):
        task = SimpleNamespace()
        task.executor = SimpleNamespace(check_enabled=Mock(), next_frame=Mock(return_value=np.zeros((20, 20, 3))),
                                        exit_event=threading.Event())
        task.hwnd = SimpleNamespace(exists=True, hwnd=123, get_capture_origin=lambda: (0, 0))
        task._guard_account_transition = Mock()
        task.in_team_and_world = Mock(side_effect=list(worlds))
        task.ocr = Mock(return_value=[])
        task._ocr_login_dialog = Mock(return_value=[])
        task._find_login_ready_box = Mock(return_value=object() if login else None)
        task._find_connect_target = Mock(return_value=None)
        task.log_info = task.log_warning = Mock()
        task.sleep = Mock(side_effect=AssertionError('startup classification must not invoke actionful sleep'))
        return task

    def test_unknown_then_world_requires_two_new_frames_without_input(self):
        task = self.task()
        self.assertEqual(MultiAccountDailyTask._classify_start_state(task), 'world')
        self.assertEqual(task.executor.next_frame.call_count, 3)
        self.assertEqual(task.ocr.call_count, 1)
        task.sleep.assert_not_called()

    def test_strong_login_and_fail_closed_states(self):
        task = self.task(worlds=(False,), login=True)
        self.assertEqual(MultiAccountDailyTask._classify_start_state(task), 'login')
        task.hwnd.exists = False
        with self.assertRaises(GameProcessLost):
            MultiAccountDailyTask._classify_start_state(task)
        task.hwnd.exists = True
        for exc in (TaskDisabledException, ConfigIntegrityBlocked):
            task._guard_account_transition.side_effect = exc('stop')
            with self.assertRaises(exc):
                MultiAccountDailyTask._classify_start_state(task)

    def test_persistent_no_frame_has_a_shared_deadline(self):
        task = self.task()
        task.executor.next_frame.return_value = None
        with patch('src.task.MultiAccountDailyTask.time.monotonic', side_effect=range(100)):
            with self.assertRaises(FrameUnavailable):
                MultiAccountDailyTask._classify_start_state(task, time_out=5)
        task.in_team_and_world.assert_not_called()
        task.ocr.assert_not_called()


if __name__ == '__main__':
    unittest.main()
