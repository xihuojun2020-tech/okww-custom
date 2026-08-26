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
                       "phone": "13800001234", "task_config": {"Which to Farm": "active"}}
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
