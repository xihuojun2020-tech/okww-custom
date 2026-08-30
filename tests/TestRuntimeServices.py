import unittest
from types import SimpleNamespace

from src.account_identity import AccountIdentityError
from src.runtime.account_selection_service import AccountSelectionService
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


if __name__ == "__main__":
    unittest.main()
