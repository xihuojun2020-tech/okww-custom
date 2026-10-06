import json
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
                from types import SimpleNamespace
                return SimpleNamespace(ok=True, master={})

            def guard_task_start(self):
                events.append("guard")
                if not safe:
                    raise ConfigIntegrityBlocked("blocked")
                return True

        class Repository:
            def __init__(self, *_args, **_kwargs):
                events.append("repository")

            def migrate_garden_execution_modes(self):
                events.append("garden_migrate")
                return False

            def migrate_fixed_account_slots(self):
                events.append('slot_migrate')
                return False

            def migrate_task_settings(self):
                events.append('task_migrate')
                return False

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
        self.assertLess(events.index("check"), events.index("garden_migrate"))
        self.assertLess(events.index("garden_migrate"), events.index("slot_migrate"))
        self.assertLess(events.index("slot_migrate"), events.index("task_migrate"))
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

    def test_startup_migrates_legacy_garden_mode_and_preserves_completion(self):
        from tests.fixture_support import make_account_environment
        env = make_account_environment(self.root, names=('A1', 'A3'), legacy_garden_mode=True)
        profile_id = next(iter(env.master['profiles']))
        stamp = '2026-09-28T05:00:00+08:00'
        env.integrity.record_completion(profile_id, 'Weekly Garden', stamp)

        runtime = bootstrap.initialize_account_runtime(
            self.root, 'test', install_start_guard=False)

        self.assertEqual(runtime.repository.load_profile(profile_id).tasks['Garden Execution Mode'],
                         'multi_account_weekly')
        self.assertEqual(runtime.integrity_service.get_completion(profile_id, 'Weekly Garden'), stamp)
        self.assertTrue(runtime.integrity_service.check().ok)

    def test_missing_master_skips_migration_and_keeps_repair_runtime_available(self):
        (self.root / 'configs').mkdir()
        (self.root / 'configs' / 'daily_profiles.json').write_text('{"profiles": {}}', encoding='utf-8')

        runtime = bootstrap.initialize_account_runtime(self.root, 'test', install_start_guard=False)

        self.assertTrue(runtime.integrity_result.master_missing)
        self.assertFalse(runtime.integrity_result.ok)
        self.assertIsNotNone(runtime.repository)

    def test_corrupt_master_skips_migration_without_startup_exception(self):
        from tests.fixture_support import make_account_environment
        make_account_environment(self.root, names=('A1', 'A3'), legacy_garden_mode=True)
        master_path = self.root / 'configs' / 'account_master_config.json'
        master_path.write_text('{broken json', encoding='utf-8')

        runtime = bootstrap.initialize_account_runtime(self.root, 'test', install_start_guard=False)

        self.assertFalse(runtime.integrity_result.master_valid)
        self.assertFalse(runtime.integrity_result.ok)

    def test_protected_master_conflict_skips_migration_and_preserves_source(self):
        from tests.fixture_support import make_account_environment
        env = make_account_environment(self.root, names=('A1', 'A3'), legacy_garden_mode=True)
        profile_id = next(iter(env.master['profiles']))
        master_path = self.root / 'configs' / 'account_master_config.json'
        altered = json.loads(master_path.read_text(encoding='utf-8'))
        altered['profiles'][profile_id]['task_config']['Weekly Garden Check Day'] = 'Wednesday'
        master_path.write_text(json.dumps(altered), encoding='utf-8')

        runtime = bootstrap.initialize_account_runtime(self.root, 'test', install_start_guard=False)

        self.assertFalse(runtime.integrity_result.ok)
        saved = json.loads(master_path.read_text(encoding='utf-8'))
        self.assertNotIn('Garden Execution Mode', saved['profiles'][profile_id]['task_config'])
        self.assertEqual(saved['profiles'][profile_id]['task_config']['Weekly Garden Check Day'], 'Wednesday')


if __name__ == "__main__":
    unittest.main()
