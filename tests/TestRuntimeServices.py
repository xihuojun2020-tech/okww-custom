import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.account_identity import AccountIdentityError
from src.runtime.account_selection_service import AccountSelectionService
from src.runtime.account_verification_service import AccountVerificationService
from src.runtime.login_flow_service import LoginFlowService
from src.runtime.task_run_coordinator import TaskRunCoordinator, TaskRunState


class TestRuntimeServices(unittest.TestCase):
    def test_disabling_queued_multi_does_not_stop_current_focused_test(self):
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask
        from src.task.BaseWWTask import BaseWWTask
        task = MultiAccountDailyTask.__new__(MultiAccountDailyTask)
        task.run_coordinator = TaskRunCoordinator()
        task.run_coordinator.start(SimpleNamespace(profile_ids=('A1',)))
        task._executor = SimpleNamespace(current_task=object())
        with patch.object(BaseWWTask, 'disable') as disable:
            task.disable()
        disable.assert_called_once()
        self.assertEqual(task.run_coordinator.state, TaskRunState.RUNNING)

    def test_framework_stop_propagates_in_selection_login_and_world_wait(self):
        from ok import TaskDisabledException
        from ok.task.TaskExecutor import TaskExecutor
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask
        from src.task.BaseWWTask import BaseWWTask
        for stop_stage in ('select', 'login', 'world'):
            with self.subTest(stage=stop_stage):
                task = MultiAccountDailyTask.__new__(MultiAccountDailyTask)
                task.run_coordinator = TaskRunCoordinator()
                snapshot = SimpleNamespace(profile_ids=('a1',), revision='r', run_id='stop')
                task.run_coordinator.start(snapshot)
                executor = TaskExecutor.__new__(TaskExecutor)
                executor.current_task = task
                executor.paused = False
                task._executor = executor
                task._enabled = True
                task.unpause = Mock()
                mouse_reset = Mock(enabled=True)
                executor.get_task_by_class = lambda _cls: mouse_reset
                task.integrity_service = None
                task._begin_account_switch_evidence = Mock()
                task._finish_account_switch_evidence = Mock(return_value=None)
                task._evidence_stage = Mock()
                task.log_info = task.log_warning = Mock()
                task.do_find_account_drop_down = lambda: object()
                task._wait_login_screen_stable = lambda **_: executor.check_enabled()
                task.sleep = lambda _: executor.check_enabled()
                inputs = []
                capture = Mock()
                capture.__enter__ = Mock(return_value=capture)
                capture.__exit__ = Mock(return_value=False)
                task._create_account_switch_capture_session = lambda: capture

                def step(stage):
                    executor.check_enabled()
                    inputs.append(stage)
                    if stage == stop_stage:
                        task.request_coordinated_stop()
                        self.assertEqual(task.run_coordinator.state, TaskRunState.STOPPING)
                        executor.check_enabled()
                        inputs.append('input-after-stop')

                task._select_account_with_retry = lambda *_args, **_kwargs: step('select')
                task._click_login_for_target = lambda *_args: step('login')
                task.ensure_main = lambda **_kwargs: step('world')
                with patch.object(BaseWWTask, 'disable', side_effect=lambda: setattr(task, '_enabled', False)), \
                        patch('src.task.BaseWWTask.og.my_app', SimpleNamespace(logged_in=True)):
                    with self.assertRaises(TaskDisabledException):
                        task.switch_to_account('a1')
                self.assertNotIn('input-after-stop', inputs)
                self.assertEqual(inputs[-1], stop_stage)
                task._finish_account_switch_evidence.assert_called_once_with(False, '', stage='stopped', stopped=True)
                self.assertIsNone(task._active_account_switch_capture)
                capture.__exit__.assert_called_once()
                mouse_reset.enable.assert_called_once()
                self.assertEqual(task.run_coordinator.state, TaskRunState.STOPPING)
                task.clear_run_snapshot()
                self.assertEqual(task.run_coordinator.state, TaskRunState.STOPPED)

    def setUp(self):
        self.profiles = {
            "a1": {"profile_id": "a1", "display_name": "A1",
                   "masked_phone": "199****0004", "alternate_login_name": "UTEST0003A"},
            "a3": {"profile_id": "a3", "display_name": "A3",
                   "masked_phone": "199****0008", "alternate_login_name": "UTEST0004A"},
        }

    def test_selection_prioritizes_masked_phone_and_rejects_missing(self):
        service = AccountSelectionService()
        self.assertEqual(service.resolve("199****0004", self.profiles), "a1")
        with self.assertRaises(AccountIdentityError):
            service.resolve("missing", self.profiles)

    def test_stop_does_not_mutate_snapshot(self):
        snapshot = SimpleNamespace(sequence_id="序列1", revision="r1",
                                   profile_ids=("a1", "a3"), run_id="run")
        coordinator = TaskRunCoordinator()
        coordinator.start(snapshot)
        coordinator.request_stop()
        self.assertEqual(snapshot.profile_ids, ("a1", "a3"))
        self.assertEqual(coordinator.state, TaskRunState.STOPPING)
        with self.assertRaises(RuntimeError):
            coordinator.start(snapshot)
        coordinator.finish()
        self.assertEqual(coordinator.state, TaskRunState.STOPPED)

    def test_verification_rejects_wrong_account_and_keeps_feature_code_disabled(self):
        profiles = {**self.profiles, "a4": {"profile_id": "a4", "display_name": "A4",
                                             "game_feature_code": "TEST-FEATURE-A4"}}
        service = AccountVerificationService()
        self.assertEqual(service.verify("a1", "199****0004", profiles), "a1")
        with self.assertRaises(AccountIdentityError):
            service.verify("a3", "199****0004", profiles)
        self.assertIsNone(service.resolve_observed("TEST-FEATURE-A4", profiles))

    def test_login_flow_orchestrates_the_existing_task_primitives(self):
        events = []

        class CaptureSession:
            def __enter__(self):
                events.append("capture_enter")
                return self

            def __exit__(self, *_args):
                events.append("capture_exit")

        class Task:
            executor = None
            logged_in = True
            _active_account_switch_capture = None

            def _guard_account_transition(self): events.append("guard")
            def _begin_account_switch_evidence(self, target): events.append(("begin", target))
            def _create_account_switch_capture_session(self): return CaptureSession()
            def do_find_account_drop_down(self): return object()
            def _evidence_stage(self, stage): events.append(stage)
            def _wait_login_screen_stable(self, time_out): events.append(("wait", time_out))
            def _select_account_with_retry(self, target, max_retries): events.append(("select", target, max_retries))
            def sleep(self, seconds): events.append(("sleep", seconds))
            def _click_login_for_target(self, target): events.append(("login", target))
            def ensure_main(self, time_out): events.append(("main", time_out))
            def log_info(self, message): events.append(("log", message))
            def _finish_account_switch_evidence(self, success, *args, **kwargs):
                events.append(("finish", success))

        task = Task()
        self.assertEqual(LoginFlowService(task).switch_to_account("a3", max_retries=2), "a3")
        self.assertIn(("select", "a3", 2), events)
        self.assertIn(("login", "a3"), events)
        self.assertIn(("finish", True), events)
        self.assertFalse(task.logged_in)
        self.assertIsNone(task._active_account_switch_capture)
        self.assertLess(events.index("capture_enter"), events.index(("wait", 120)))
        self.assertGreater(events.index("capture_exit"), events.index(("main", 180)))

    def test_login_flow_cleans_capture_session_after_failure(self):
        events = []

        class CaptureSession:
            def __enter__(self):
                events.append("capture_enter")
                return self

            def __exit__(self, *_args):
                events.append("capture_exit")

        class Task:
            executor = None
            logged_in = True
            _active_account_switch_capture = None

            def _guard_account_transition(self): pass
            def _begin_account_switch_evidence(self, _target): pass
            def _create_account_switch_capture_session(self): return CaptureSession()
            def do_find_account_drop_down(self): return object()
            def _evidence_stage(self, _stage): pass
            def _wait_login_screen_stable(self, time_out):
                raise RuntimeError(f"wait failed after {time_out}")
            def _finish_account_switch_evidence(self, *_args, **_kwargs): return None

        task = Task()
        with self.assertRaises(RuntimeError):
            LoginFlowService(task).switch_to_account("a3")

        self.assertEqual(["capture_enter", "capture_exit"], events)
        self.assertIsNone(task._active_account_switch_capture)


if __name__ == "__main__":
    unittest.main()
