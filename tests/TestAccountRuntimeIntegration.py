# -*- coding: utf-8 -*-
"""Small runtime-boundary tests for the account repository integration."""

import copy
import hashlib
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from src.account_repository import AccountRepository
from src.account_publish_service import AccountPublishService
from src.config_integrity import ConfigPaths
from src.task.DailyTask import DailyTask
from src.task.MultiAccountDailyTask import MultiAccountDailyTask
from src.task.TestAccountSwitchTask import (
    CONTINUOUS_MODE,
    DEFAULT_CONTINUOUS_ORDER,
    TestAccountSwitchTask,
)


def _digest(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TestAccountRuntimeIntegration(unittest.TestCase):
    def test_one_validation_per_projection_and_snapshot_at_2_10_50_accounts(self):
        from tests.fixture_support import make_account_environment
        from src.sequence_repository import SequenceRepository
        original = AccountPublishService._validate_bundle_dir
        for count in (2, 10, 50):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as temp:
                env = make_account_environment(temp, names=tuple(f'A{n}' for n in range(1, count + 1)))
                for create in (env.repository.get_detached_projection,
                               lambda: SequenceRepository(env.repository).create_run_snapshot('S1')):
                    with patch.object(AccountPublishService, '_validate_bundle_dir',
                                      autospec=True, side_effect=original) as check:
                        create()
                        self.assertEqual(check.call_count, 1)

    def test_real_run_uses_snapshot_after_parameter_sequence_and_label_edits(self):
        from src.account_repository import ProfileEditScope
        from src.config_integrity import ConfigIntegrityBlocked
        from src.runtime.task_run_coordinator import TaskRunCoordinator
        from src.task.MultiAccountDailyTask import CURRENT_ACCOUNT, CURRENT_SEQUENCE
        from src.task.DailyTask import DAILY_PROFILE
        from tests.fixture_support import make_account_environment, synthetic_identity
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(temp)
            repo = env.repository
            a1 = synthetic_identity('A1')['profile_id']
            a3 = synthetic_identity('A3')['profile_id']
            multi = object.__new__(MultiAccountDailyTask)
            multi.integrity_service = env.integrity
            multi.config = {CURRENT_SEQUENCE: 'S1', CURRENT_ACCOUNT: 'A1'}
            multi.run_coordinator = TaskRunCoordinator()
            multi.done_set = set()
            multi.failed_accounts = {}
            snapshot = multi.create_run_snapshot(None, sequence_id='S1')
            multi._set_run_start('A1')
            daily = object.__new__(DailyTask)
            daily.integrity_service = env.integrity
            daily.config = {DAILY_PROFILE: 'A3'}
            daily.bind_verified_profile('A1', expected_profile_id=a1, snapshot_profile=snapshot.profiles[0])
            record = repo.load_profile(a1)
            repo.publish_profile(ProfileEditScope(a1, record.revision), {
                'account': {**record.account, 'display_name': 'A10'},
                'tasks': {**record.tasks, 'Which Tacet Suppression to Farm': 2}})
            repo.publish_sequence('S1', [a3])
            multi.config[CURRENT_ACCOUNT] = 'A3'
            self.assertEqual(multi._next_target_account(), 'A1')
            self.assertEqual(multi._run_return_profile_id, a1)
            self.assertTrue(multi._guard_account_transition())
            daily.ensure_daily_profiles()
            self.assertEqual(daily._profile_get('Which Tacet Suppression to Farm'), 1)
            self.assertEqual(daily.config[DAILY_PROFILE], 'A3')
            self.assertEqual(daily.get_active_profile_name(), 'A1')
            daily.clear_profile_binding()
            multi.clear_run_snapshot()
            new = multi.create_run_snapshot(None, sequence_id='S1')
            self.assertEqual(new.profile_ids, (a3,))
            self.assertEqual(repo.load_profile(a1).tasks['Which Tacet Suppression to Farm'], 2)
            repo.delete_profile_cascade(a3, expected_revision=repo.load_profile(a3).revision)
            with self.assertRaises(ConfigIntegrityBlocked):
                multi._screen_click(0, 0, target_hwnd=1)

    def test_alias_disable_is_respected_by_production_with_flat_and_nested_profiles(self):
        from tests.fixture_support import synthetic_identity
        identity = synthetic_identity('A1')
        for nested in (False, True):
            settings = {'备用识别名称': '无', '备用识别名称内容': identity['alternate_login_name']}
            profile = {**identity, 'display_name': 'A1', 'account_aliases': [identity['alternate_login_name']],
                       **({'task_config': settings} if nested else settings)}
            task = object.__new__(MultiAccountDailyTask)
            task._load_profiles = lambda: {'A1': profile}
            self.assertIsNone(task.match_profile_from_login(identity['alternate_login_name']))
            self.assertEqual(task.match_profile_from_login(identity['masked_phone']), 'A1')
            settings['备用识别名称'] = '使用'
            if not nested:
                profile.update(settings)
            self.assertEqual(task.match_profile_from_login(identity['alternate_login_name']), 'A1')

    def test_arbitrary_sequence_counts_construct_and_refresh_real_task(self):
        from tests.fixture_support import make_account_environment
        from src.task.MultiAccountDailyTask import CURRENT_ACCOUNT, CURRENT_SEQUENCE, CURRENT_SEQUENCE_MEMBERS
        module = __import__('src.task.MultiAccountDailyTask', fromlist=['MultiAccountDailyTask'])
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(temp)
            repo = env.repository
            for count in (0, 1, 10, 11, 50):
                master = copy.deepcopy(env.master)
                master['sequences'] = {f'S{i}': list(master['profiles']) for i in range(count)}
                repo._publish_master(master)
                with patch.object(module, 'get_default_service', return_value=env.integrity), \
                        patch.object(module, 'get_default_repository', return_value=repo):
                    from types import SimpleNamespace
                    executor = SimpleNamespace(scene=None, text_fix={}, global_config=SimpleNamespace(get_config=lambda _: {}))
                    task = MultiAccountDailyTask(executor=executor, app=None)
                    task.config = {**task.default_config, CURRENT_SEQUENCE: f'S{count-1}', CURRENT_ACCOUNT: ''}
                    task.running = False
                    self.assertTrue(task.refresh_account_options())
                    self.assertEqual(len(task.config_type[CURRENT_SEQUENCE]['options']), count)
                    self.assertEqual(task.get_readonly_config_value(CURRENT_SEQUENCE_MEMBERS),
                                     ['A1', 'A3', 'A4'] if count else [])
                    if count:
                        self.assertEqual(len(task.create_run_snapshot(None, sequence_id=f'S{count-1}').profiles), 3)
                    task.clear_run_snapshot()

    def test_test_task_reads_real_default_repository_and_reports_corruption(self):
        from tests.fixture_support import make_account_environment
        module = __import__('src.task.TestAccountSwitchTask', fromlist=['TestAccountSwitchTask'])
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(temp)
            task = object.__new__(TestAccountSwitchTask)
            task.log_error = lambda *args: None
            with patch.object(module, 'get_default_repository', return_value=env.repository):
                self.assertEqual(task._get_profile_names(), ['A1', 'A3', 'A4'])
                env.publisher.active_path.write_text('{}', encoding='utf-8')
                self.assertEqual(task._get_profile_names(), [])
                self.assertTrue(task._profile_load_error)

    def test_projection_and_snapshot_validate_once_and_fail_closed_after_corruption(self):
        from tests.fixture_support import make_account_environment
        from src.sequence_repository import SequenceRepository
        from src.config_integrity import ConfigIntegrityBlocked
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(temp)
            original = AccountPublishService._validate_bundle_dir
            calls = []
            def counted(service, *args):
                calls.append(1)
                return original(service, *args)
            for operation in (env.repository.get_detached_projection,
                              lambda: SequenceRepository(env.repository).create_run_snapshot('S1')):
                calls.clear()
                with patch.object(AccountPublishService, '_validate_bundle_dir', counted):
                    operation()
                self.assertEqual(len(calls), 1)
            active = env.publisher.load_active()
            (active.bundle_dir / 'sequences.json').write_text('{}', encoding='utf-8')
            for cls, method in ((DailyTask, 'load_daily_profiles'), (MultiAccountDailyTask, '_load_profiles')):
                task = object.__new__(cls)
                task.integrity_service = env.integrity
                with self.assertRaises(ConfigIntegrityBlocked):
                    getattr(task, method)()

    def test_nested_input_guard_stops_before_delivery_and_is_released(self):
        from types import SimpleNamespace
        from tests.fixture_support import make_account_environment, synthetic_identity
        from src.config_integrity import ConfigIntegrityBlocked
        from src.task.BaseWWTask import BaseWWTask
        from src.sequence_repository import SequenceRepository
        with tempfile.TemporaryDirectory() as temp:
            env = make_account_environment(temp)
            daily = object.__new__(DailyTask)
            daily.integrity_service = env.integrity
            daily.config = {'Daily Profile': 'A3'}
            executor = SimpleNamespace()
            daily._executor = executor
            child = object.__new__(BaseWWTask)
            child._executor = executor
            a1 = synthetic_identity('A1')['profile_id']
            profile = SequenceRepository(env.repository).create_run_snapshot('S1').profiles[0]
            daily.bind_verified_profile('A1', snapshot_profile=profile)
            with daily.account_input_guard(daily._guard_bound_profile_identity):
                env.repository.delete_profile_cascade(a1, expected_revision=env.repository.load_profile(a1).revision)
                with self.assertRaises(ConfigIntegrityBlocked):
                    child.send_key('e')
            self.assertIsNone(executor._account_input_guard)

    def test_daily_exception_releases_run_binding(self):
        task = object.__new__(DailyTask)
        task._snapshot_bound_externally = True
        task._verified_profile_snapshot = {'old': True}
        task._run_daily_inner = lambda: (_ for _ in ()).throw(RuntimeError('forced'))
        with self.assertRaisesRegex(RuntimeError, 'forced'):
            task.run()
        self.assertIsNone(task._verified_profile_snapshot)
        self.assertFalse(task._snapshot_bound_externally)

    def test_daily_task_prefers_detached_default_repository_projection(self):
        projection = {"A1": {"profile_id": "a1", "Which to Farm": "repository"}}

        class Repository:
            def legacy_profile_projection(self, *_args, **_kwargs):
                return {"profiles": copy.deepcopy(projection), "sequences": {}}

            # Keep the test compatible with the repository naming used by the
            # runtime adapter while still asserting a detached result.
            get_detached_projection = legacy_profile_projection

        task = object.__new__(DailyTask)
        task.integrity_service = None
        task.config = {"Daily Profile": "A1"}
        module = __import__("src.task.DailyTask", fromlist=["DailyTask"])
        with patch.object(module, "get_default_repository", return_value=Repository(), create=True), \
                patch.object(module, "read_json_file", side_effect=AssertionError("legacy daily_profiles read")):
            profiles = task.load_daily_profiles()
        self.assertEqual(profiles["A1"]["Which to Farm"], "repository")
        profiles["A1"]["Which to Farm"] = "mutated caller copy"
        self.assertEqual(projection["A1"]["Which to Farm"], "repository")

    def test_daily_and_multi_tasks_read_active_snapshot_with_integrity_service(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile_id = str(uuid.uuid4())
            profile = {"profile_id": profile_id, "display_name": "A1",
                       "phone": "19910000008", "task_config": {"Which to Farm": "active"}}
            AccountPublishService(root).publish(
                expected_revision="", profiles={profile_id: profile},
                index={"config_id": "active-test"}, sequences={"序列1": [profile_id]})

            class Integrity:
                paths = ConfigPaths.from_root(root)

            daily = object.__new__(DailyTask)
            daily.integrity_service = Integrity()
            multi = object.__new__(MultiAccountDailyTask)
            multi.integrity_service = Integrity()
            self.assertEqual(daily.load_daily_profiles()["A1"]["Which to Farm"], "active")
            self.assertIn("A1", multi._load_profiles())

    def test_task_option_refresh_methods_use_new_account_graph(self):
        from src.task.DailyTask import DAILY_PROFILE, PROFILE_SEQUENCE, DailyTask
        from src.task.MultiAccountDailyTask import (
            CURRENT_ACCOUNT, CURRENT_SEQUENCE, SEQ_ACCOUNTS, MultiAccountDailyTask,
        )

        daily = object.__new__(DailyTask)
        daily.running = False
        daily.config = {PROFILE_SEQUENCE: "序列2", DAILY_PROFILE: "A1"}
        daily.config_type = {PROFILE_SEQUENCE: {}, DAILY_PROFILE: {}}
        daily._sync_sequence_options = lambda: None
        daily.get_profile_sequences = lambda: ["序列2"]
        daily.get_profile_names = lambda _sequence=None: ["A1"]
        seen = {}
        daily._update_dropdown_items = lambda key, options: seen.setdefault(key, list(options))
        daily._refresh_gui = lambda: None
        self.assertTrue(daily.refresh_account_options())
        self.assertEqual(seen[PROFILE_SEQUENCE], ["序列2"])
        self.assertEqual(seen[DAILY_PROFILE], ["A1"])

        multi = object.__new__(MultiAccountDailyTask)
        multi.running = False
        multi._account_refresh_pending = False
        multi.config = {CURRENT_SEQUENCE: "序列2", CURRENT_ACCOUNT: "A1"}
        multi.config_type = {
            CURRENT_SEQUENCE: {}, CURRENT_ACCOUNT: {},
            **{key: {} for key in SEQ_ACCOUNTS},
        }
        multi.get_sequence_names = lambda: ["序列2"]
        multi.get_profile_names = lambda: ["A1", "A3"]
        self.assertTrue(multi.refresh_account_options())
        self.assertEqual(multi.config_type[CURRENT_SEQUENCE]["options"], ["序列2"])
        self.assertEqual(multi.config_type[CURRENT_ACCOUNT]["options"], ["", "A1", "A3"])

    def test_bind_verified_profile_keeps_immutable_run_snapshot(self):
        profile_id = str(uuid.uuid4())
        source = {
            "A1": {"profile_id": profile_id, "Which to Farm": "before", "Nested": {"value": 1}}
        }
        task = object.__new__(DailyTask)
        task.config = {"Daily Profile": "A1"}
        task.integrity_service = object()
        task._runtime_overrides = {}
        task.load_daily_profiles = lambda: source

        task.bind_verified_profile("A1", expected_profile_id=profile_id)
        source["A1"]["Which to Farm"] = "after"
        source["A1"]["Nested"]["value"] = 2

        self.assertEqual(task._profile_get("Which to Farm"), "before")
        self.assertEqual(task._profile_get("Nested")["value"], 1)

    def test_bind_verified_profile_synchronizes_runtime_selector(self):
        profile_a = str(uuid.uuid4())
        profile_b = str(uuid.uuid4())
        task = object.__new__(DailyTask)
        task.config = {"Daily Profile": "A1"}
        task.integrity_service = type("Integrity", (), {"is_safe": True})()
        task._runtime_overrides = {}
        task._switching_profile = False
        task.load_daily_profiles = lambda: {
            "A1": {"profile_id": profile_a, "Auto Farm all Nightmare Nest": False},
            "A3": {"profile_id": profile_b, "Auto Farm all Nightmare Nest": True},
        }

        task.bind_verified_profile("A3", expected_profile_id=profile_b)
        task.ensure_daily_profiles()

        self.assertEqual(task.config["Daily Profile"], "A3")
        self.assertEqual(task._verified_profile_id, profile_b)
        self.assertTrue(task._profile_get("Auto Farm all Nightmare Nest"))

    def test_unconfirmed_external_edit_is_scoped_to_changed_account(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            configs = root / "configs"
            configs.mkdir()
            a1, a3 = str(uuid.uuid4()), str(uuid.uuid4())
            a1_payload = {"profile_id": a1, "short_name": "A1"}
            a3_payload = {"profile_id": a3, "short_name": "A3"}
            a1_payload["digest"] = _digest(a1_payload)
            a3_payload["digest"] = _digest(a3_payload)
            master = {
                "accounts": {a1: a1_payload, a3: a3_payload},
                "sequences": {"default": [a1, a3]},
            }
            path = configs / "account_master_config.json"
            path.write_text(json.dumps(master), encoding="utf-8")
            repo = AccountRepository(root)

            changed = json.loads(path.read_text(encoding="utf-8"))
            changed["accounts"][a1]["short_name"] = "tampered"
            path.write_text(json.dumps(changed), encoding="utf-8")
            result = repo.verify_ready()

            self.assertIn(a1, result.account_errors)
            self.assertNotIn(a3, result.account_errors)
            self.assertIn(a1, result.external_changes)
            self.assertNotIn(a3, result.external_changes)

    def test_switch_test_and_multi_account_use_same_production_entry_and_default_order(self):
        self.assertEqual(DEFAULT_CONTINUOUS_ORDER, "A1,A3,A4")
        calls = []

        class FakeMultiTask:
            _select_and_login_specific = MultiAccountDailyTask._select_and_login_specific
            _select_and_login_sequence = MultiAccountDailyTask._select_and_login_sequence

            def switch_to_account(self, target):
                calls.append(target)
                return target

            def resolve_profile_short_names(self, short_names):
                return list(short_names)

            def log_info(self, *_args, **_kwargs):
                pass

            def _switch_to_login(self):
                pass

            def sleep(self, _seconds):
                pass

        multi = FakeMultiTask()
        self.assertIs(FakeMultiTask._select_and_login_sequence, MultiAccountDailyTask._select_and_login_sequence)
        self.assertEqual(multi._select_and_login_sequence(["A1", "A3", "A4"]), ["A1", "A3", "A4"])

        task = object.__new__(TestAccountSwitchTask)
        task.config = {
            "测试模式": CONTINUOUS_MODE,
            "连续账号顺序": DEFAULT_CONTINUOUS_ORDER,
            "测试轮数": "1",
        }
        task._get_multi_account_task = lambda: multi
        targets = multi.resolve_profile_short_names(
            task._parse_continuous_order(task.config["连续账号顺序"])
        )
        self.assertEqual(multi._select_and_login_sequence(targets), ["A1", "A3", "A4"])
        self.assertEqual(calls, ["A1", "A3", "A4", "A1", "A3", "A4"])


if __name__ == "__main__":
    unittest.main()
