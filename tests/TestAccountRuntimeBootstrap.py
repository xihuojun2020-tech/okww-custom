import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config_integrity import ConfigPaths, ConfigIntegrityBlocked, get_default_service
from src.account_repository import get_default_repository
from src.runtime import account_runtime_bootstrap as bootstrap


class TestAccountRuntimeBootstrap(unittest.TestCase):
    def setUp(self):
        bootstrap._reset_account_runtime_for_tests()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        bootstrap._reset_account_runtime_for_tests()
        self.temp.cleanup()

    def _dependencies(self, events, *, safe=True):
        root = self.root

        class Publish:
            def __init__(self, *_args, **_kwargs):
                events.append("publish")

            def recover_incomplete_transactions(self):
                events.append("recover")

        class Integrity:
            def __init__(self, *_args, **_kwargs):
                self.paths = ConfigPaths.from_root(root)
                events.append("integrity")

            def check(self):
                events.append("check")
                return object()

            def guard_task_start(self):
                events.append("guard")
                if not safe:
                    raise ConfigIntegrityBlocked("blocked")
                return True

        class Repository:
            def __init__(self, *_args, **_kwargs):
                events.append("repository")

        class Snapshot:
            def __init__(self, _repository):
                events.append("snapshot")

        return patch.multiple(
            bootstrap,
            AccountPublishService=Publish,
            ConfigIntegrityService=Integrity,
            AccountRepository=Repository,
            SequenceSnapshotService=Snapshot,
        )

    def test_recovery_precedes_integrity_check_and_initialization_is_idempotent(self):
        events = []

        class Controller:
            def do_start(self):
                return True

        with self._dependencies(events):
            first = bootstrap.initialize_account_runtime(
                self.root, "test", controller_cls=Controller)
            second = bootstrap.initialize_account_runtime(
                self.root, "test", controller_cls=Controller)

        self.assertIs(first, second)
        self.assertLess(events.index("recover"), events.index("check"))
        self.assertEqual(1, events.count("publish"))
        self.assertIs(first.integrity_service, get_default_service())
        self.assertIs(first.repository, get_default_repository())

    def test_require_ready_fails_closed(self):
        events = []
        with self._dependencies(events, safe=False):
            bootstrap.initialize_account_runtime(
                self.root, "test", install_start_guard=False)
            with self.assertRaises(ConfigIntegrityBlocked):
                bootstrap.require_account_runtime_ready()
        self.assertIn("guard", events)

    def test_missing_controller_hook_does_not_publish_defaults(self):
        events = []

        class Controller:
            pass

        with self._dependencies(events):
            with self.assertRaises(RuntimeError):
                bootstrap.initialize_account_runtime(
                    self.root, "test", controller_cls=Controller)
        self.assertIsNone(bootstrap.get_account_runtime())
        self.assertIsNone(get_default_service())
        self.assertIsNone(get_default_repository())

    def test_real_task_without_launcher_is_lazily_guarded(self):
        events = []

        class Task:
            executor = object()
            integrity_service = None

        with self._dependencies(events):
            runtime = bootstrap.require_account_runtime_for_task(Task())
        self.assertIsNotNone(runtime)
        self.assertIn("guard", events)


if __name__ == "__main__":
    unittest.main()
