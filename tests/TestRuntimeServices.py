import unittest
from types import SimpleNamespace

from src.account_identity import AccountIdentityError
from src.runtime.account_selection_service import AccountSelectionService
from src.runtime.account_verification_service import AccountVerificationService
from src.runtime.login_flow_service import LoginFlowService
from src.runtime.task_run_coordinator import TaskRunCoordinator, TaskRunState


class TestRuntimeServices(unittest.TestCase):
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
