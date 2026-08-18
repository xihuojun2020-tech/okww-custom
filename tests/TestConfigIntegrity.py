# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from src.config_integrity import (
    ConfigIntegrityBlocked,
    ConfigIntegrityService,
    ConfigWriteBlocked,
    TaskStartGuard,
    atomic_write_json,
    assert_master_read_only,
    fingerprint,
    normalize_master,
    normalize_working,
    validate_master,
    IntegrityResult,
    install_task_start_guard,
)
from src.task.DailyTask import DailyTask, DAILY_PROFILE
from src.gui.ConfigIntegrityDialog import ConfigIntegrityDialogController


PROFILE_A = "0f7b7f52-9da7-4b43-bbc2-9be7c539f801"
PROFILE_B = "1f7b7f52-9da7-4b43-bbc2-9be7c539f802"


def master():
    return {
        "schema_version": 1,
        "config_id": "test-config",
        "timezone": "Asia/Shanghai",
        "profiles": {
            PROFILE_A: {
                "display_name": "A1",
                "account_aliases": ["A1", "153****9621"],
                "task_config": {
                    "Which to Farm": "Tacet Suppression", "Which Tacet Suppression to Farm": 1,
                    "Which Forgery Challenge to Farm": 1, "Material Selection": "Shell Credit",
                    "Farm Nightmare Nest for Daily Echo": True, "Nightmare Which to Farm": ["Tacet Discord Nest"],
                    "Tacet Discord Nests to Farm": [], "Auto Farm all Nightmare Nest": False,
                    "Weekly Garden Check Day": "无", "Merge Echo on Sunday": False,
                    "备用识别名称": "无", "备用识别名称内容": "",
                },
                "schedule": {"mode": "daily", "local_time": "04:00", "weekdays": []},
                "extensions": {"x-test": {"value": True}},
            },
            PROFILE_B: {
                "display_name": "A3",
                "account_aliases": ["A3", "180****0004"],
                "task_config": {
                    "Which to Farm": "Forgery Challenge", "Which Tacet Suppression to Farm": 1,
                    "Which Forgery Challenge to Farm": 1, "Material Selection": "Shell Credit",
                    "Farm Nightmare Nest for Daily Echo": True, "Nightmare Which to Farm": ["Tacet Discord Nest"],
                    "Tacet Discord Nests to Farm": [], "Auto Farm all Nightmare Nest": False,
                    "Weekly Garden Check Day": "无", "Merge Echo on Sunday": False,
                    "备用识别名称": "无", "备用识别名称内容": "",
                },
                "schedule": {},
                "extensions": {},
            },
        },
        "sequences": {"序列一": [PROFILE_A, PROFILE_B]},
        "extensions": {"x-root": {"keep": True}},
    }


def working():
    return {
        "profiles": {
            "A1": {
                "profile_id": PROFILE_A,
                "display_name": "A1",
                "account_aliases": ["A1", "153****9621"],
                "Which to Farm": "Tacet Suppression", "Which Tacet Suppression to Farm": 1,
                "Which Forgery Challenge to Farm": 1, "Material Selection": "Shell Credit",
                "Farm Nightmare Nest for Daily Echo": True, "Nightmare Which to Farm": ["Tacet Discord Nest"],
                "Tacet Discord Nests to Farm": [], "Auto Farm all Nightmare Nest": False,
                "Weekly Garden Check Day": "无", "Merge Echo on Sunday": False,
                "备用识别名称": "无", "备用识别名称内容": "",
                "schedule": {"mode": "daily", "local_time": "04:00", "weekdays": []},
                "extensions": {"x-test": {"value": True}},
            },
            "A3": {
                "profile_id": PROFILE_B,
                "display_name": "A3",
                "account_aliases": ["A3", "180****0004"],
                "Which to Farm": "Forgery Challenge", "Which Tacet Suppression to Farm": 1,
                "Which Forgery Challenge to Farm": 1, "Material Selection": "Shell Credit",
                "Farm Nightmare Nest for Daily Echo": True, "Nightmare Which to Farm": ["Tacet Discord Nest"],
                "Tacet Discord Nests to Farm": [], "Auto Farm all Nightmare Nest": False,
                "Weekly Garden Check Day": "无", "Merge Echo on Sunday": False,
                "备用识别名称": "无", "备用识别名称内容": "",
            },
        },
        "sequences": {"序列一": ["A1", "A3"]},
        "active_profile": "A1",
        "extensions": {"x-root": {"keep": True}},
    }


class TestConfigIntegrity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "configs").mkdir()
        (self.root / "configs" / "account_master_config.json").write_text(
            json.dumps(master(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (self.root / "configs" / "daily_profiles.json").write_text(
            json.dumps(working(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.service = ConfigIntegrityService(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_first_check_requires_explicit_fingerprint_acceptance(self):
        result = self.service.check()
        self.assertTrue(result.master_valid)
        self.assertTrue(result.working_valid)
        self.assertTrue(result.master_changed)
        self.assertFalse(result.ok)
        self.assertTrue(result.event_dir.joinpath("PENDING_REVIEW").exists())
        accepted = self.service.accept_master_change(result=result)
        self.assertTrue(accepted.ok)
        self.assertEqual(accepted.master_fingerprint, fingerprint(normalize_master(master())))

    def test_json_formatting_does_not_create_diff(self):
        self.service.accept_master_change(result=self.service.check())
        result = self.service.check()
        self.assertTrue(result.ok)
        # Reformat the files only; semantic fingerprints remain stable.
        self.service.paths.master.write_text(json.dumps(master(), ensure_ascii=False), encoding="utf-8")
        self.service.paths.working.write_text(json.dumps(working(), ensure_ascii=False, indent=4), encoding="utf-8")
        self.assertTrue(self.service.check().ok)

    def test_working_change_is_recorded_and_restore_is_atomic(self):
        self.service.accept_master_change(result=self.service.check())
        changed = working()
        changed["profiles"]["A1"]["Which to Farm"] = "Simulation Challenge"
        self.service.paths.working.write_text(json.dumps(changed), encoding="utf-8")
        result = self.service.check()
        self.assertFalse(result.ok)
        self.assertTrue(any(d["field"] == "task_config" for d in result.differences))
        restored = self.service.restore_working_from_master(result=result)
        self.assertTrue(restored.ok)
        restored_data = json.loads(self.service.paths.working.read_text())
        self.assertEqual(restored_data["profiles"]["A1"]["task_config"]["Which to Farm"],
                         "Tacet Suppression")
        self.assertEqual(restored_data["profiles"]["A1"]["Which to Farm"],
                         "Tacet Suppression")
        self.assertTrue(any((p / "RESOLVED_BY_MASTER_RESTORE").exists() for p in self.service.paths.incidents.iterdir()))

    def test_invalid_schema_and_alias_conflict(self):
        invalid = master()
        invalid["schema_version"] = 2
        invalid["profiles"][PROFILE_B]["account_aliases"] = ["A1"]
        errors = validate_master(invalid)
        self.assertTrue(any("schema_version" in error for error in errors))
        self.assertTrue(any("ambiguous" in error for error in errors))

    def test_validate_master_rejects_derived_phone_identity_collision(self):
        invalid = master()
        invalid["profiles"][PROFILE_A]["account_aliases"] = ["15300000001"]
        invalid["profiles"][PROFILE_B]["account_aliases"] = ["153****0001"]
        errors = validate_master(invalid)
        self.assertTrue(any("153****0001" in error and "ambiguous" in error for error in errors))

    def test_validate_master_keeps_a1_and_a10_derived_names_distinct(self):
        valid = master()
        valid["profiles"][PROFILE_A]["display_name"] = "A1"
        valid["profiles"][PROFILE_A]["account_aliases"] = ["A1"]
        valid["profiles"][PROFILE_B]["display_name"] = "A10"
        valid["profiles"][PROFILE_B]["account_aliases"] = ["A10"]
        self.assertFalse(validate_master(valid))

    def test_dialog_confirm_closes_with_fresh_safe_result(self):
        controller = ConfigIntegrityDialogController(self.service)
        controller.acknowledge()
        result = controller.confirm_master_change()
        self.assertTrue(result.ok)
        self.assertTrue(controller.can_run)

    def test_master_write_is_rejected(self):
        with self.assertRaises(ConfigWriteBlocked):
            assert_master_read_only(self.service.paths.master)
        with self.assertRaises(ConfigWriteBlocked):
            atomic_write_json(self.service.paths.master, master())

    def test_task_guard_rejects_until_safe(self):
        guard = TaskStartGuard(self.service)
        with self.assertRaises(ConfigIntegrityBlocked):
            guard.check()
        self.service.accept_master_change(result=self.service.last_result)
        self.assertTrue(guard.check())

    def test_incident_is_deduplicated(self):
        first = self.service.check()
        second = self.service.check()
        self.assertEqual(first.event_dir, second.event_dir)
        manifest = json.loads((first.event_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(manifest["occurrences"]), 2)
        self.assertNotEqual(manifest["program_version"], "unknown")
        incident_log = (first.event_dir / "integrity.log").read_text(encoding="utf-8")
        self.assertIn("differences:", incident_log)

    def test_runtime_updates_are_serialized_without_lost_fields(self):
        self.service.accept_master_change(result=self.service.check())

        def update(index):
            self.service.record_completion(PROFILE_A, f"task-{index}", when=str(index))
            self.service.set_progress(f"cursor-{index}", index)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(update, range(20)))
        runtime = json.loads(self.service.paths.runtime.read_text(encoding="utf-8"))
        self.assertEqual(len(runtime["completed_at"][PROFILE_A]), 20)
        self.assertEqual(len(runtime["progress"]), 20)

    def test_corrupt_runtime_requires_explicit_rebuild_before_accept(self):
        self.service.paths.runtime.write_text("{broken", encoding="utf-8")
        result = self.service.check()
        self.assertTrue(any("runtime state invalid" in error for error in result.errors))
        self.assertTrue((result.event_dir / "runtime.snapshot.json").exists())
        with self.assertRaises(ConfigIntegrityBlocked):
            self.service.accept_master_change(result=result)
        rebuilt = self.service.rebuild_runtime_state(confirm=True)
        self.assertFalse(rebuilt.ok)  # master fingerprint still needs confirmation
        accepted = self.service.accept_master_change(result=rebuilt)
        self.assertTrue(accepted.ok)

    def test_runtime_corruption_is_fail_closed_for_reads_and_multi_progress(self):
        self.service.accept_master_change(result=self.service.check())
        self.service.paths.runtime.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ConfigIntegrityBlocked):
            self.service.get_completion(PROFILE_A, 'Daily Task')
        with self.assertRaises(ConfigIntegrityBlocked):
            self.service.get_profile_completions(PROFILE_A)
        with self.assertRaises(ConfigIntegrityBlocked):
            self.service.get_progress('cursor')
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask
        task = object.__new__(MultiAccountDailyTask)
        task.integrity_service = self.service
        task._today = lambda: '2026-08-18'
        with self.assertRaises(ConfigIntegrityBlocked):
            task._load_today_progress()
        self.service.check()
        self.service.check()
        self.assertEqual(list(self.service.paths.config_dir.glob('account_runtime_state.json.corrupt_*')), [])

    def test_legacy_identity_candidates_map_short_masked_and_u_names(self):
        source = master()
        source['profiles'][PROFILE_B]['display_name'] = 'A10'
        source['profiles'][PROFILE_B]['account_aliases'] = ['A10', '180****0004', 'U-A10']
        source['profiles'][PROFILE_B]['task_config']['备用识别名称内容'] = 'U-A10'
        legacy = {
            'profiles': {
                'A1:15300000001': {
                    'Which to Farm': 'Tacet Suppression', 'last_completed': {'Daily Task': 'today'}
                },
                'U-A10': {
                    'Which to Farm': 'Forgery Challenge', 'last_completed': {'Daily Task': 'yesterday'}
                },
            },
            'sequences': {'序列一': ['A1:15300000001', 'U-A10']},
            'active_profile': 'A1:15300000001',
        }
        normalized = normalize_working(legacy, source)
        self.assertEqual(set(normalized['profiles']), {PROFILE_A, PROFILE_B})
        rebuilt = self.service._rebuild_working(source, legacy)
        self.assertEqual(rebuilt['profiles']['A1']['last_completed']['Daily Task'], 'today')
        self.assertEqual(rebuilt['profiles']['A10']['last_completed']['Daily Task'], 'yesterday')

    def test_legacy_identity_short_names_do_not_match_a10_or_ambiguous_aliases(self):
        source = master()
        source['profiles'][PROFILE_B]['display_name'] = 'A10'
        source['profiles'][PROFILE_B]['account_aliases'] = ['A10', '180****0004']
        one = {'profiles': {'A1': {'Which to Farm': 'Tacet Suppression'}}, 'sequences': {}}
        self.assertEqual(set(normalize_working(one, source)['profiles']), {PROFILE_A})
        source['profiles'][PROFILE_B]['account_aliases'] = ['A1']
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            normalize_working(one, source)

    def test_restore_postcheck_failure_rolls_back_original_bytes(self):
        self.service.accept_master_change(result=self.service.check())
        changed = working()
        changed["profiles"]["A1"]["Which to Farm"] = "Simulation Challenge"
        self.service.paths.working.write_text(json.dumps(changed), encoding="utf-8")
        result = self.service.check()
        original = self.service.paths.working.read_bytes()
        failed = IntegrityResult(ok=False, master_valid=True, working_valid=True,
                                 master=result.master, working=result.working,
                                 master_fingerprint=result.master_fingerprint,
                                 working_fingerprint=result.working_fingerprint)
        with patch.object(self.service, "check", return_value=failed):
            with self.assertRaises(ConfigIntegrityBlocked):
                self.service.restore_working_from_master(result=result)
        self.assertEqual(self.service.paths.working.read_bytes(), original)

    def test_oserror_during_read_fails_closed(self):
        with patch("src.config_integrity._read_json", side_effect=OSError("permission denied")):
            result = self.service.check(record_incident=False)
        self.assertFalse(result.ok)
        self.assertTrue(result.errors)

    def test_daily_profile_switch_does_not_write_protected_config(self):
        task = object.__new__(DailyTask)
        task.integrity_service = object()
        task.config = {DAILY_PROFILE: "A1", "Which to Farm": "old"}
        task._verified_profile_id = None
        task._verified_profile_name = None
        task.load_daily_profiles = lambda: {"A1": {"profile_id": PROFILE_A, "Which to Farm": "new"}}
        task.apply_profile_config = DailyTask.apply_profile_config.__get__(task)
        task._do_switch_profile(None, "A1")
        self.assertEqual(task.config["Which to Farm"], "old")
        self.assertEqual(task._verified_profile_id, PROFILE_A)

    def test_multi_binding_repairs_same_label_with_stale_or_empty_verified_id(self):
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask

        class Daily:
            def __init__(self):
                self.config = {DAILY_PROFILE: 'A1'}
                self.bound = PROFILE_B

            def bind_verified_profile(self, name, expected_profile_id=None):
                self.bound = expected_profile_id or PROFILE_A

        daily = Daily()
        task = object.__new__(MultiAccountDailyTask)
        task.integrity_service = object()
        task.config = {}
        task.get_task_by_class = lambda _kind: daily
        task.log_info = lambda *_args, **_kwargs: None
        task.log_warning = lambda *_args, **_kwargs: None
        self.assertTrue(task._link_daily_profile('A1'))
        self.assertEqual(daily.bound, PROFILE_A)

    def test_child_task_execution_config_uses_snapshot_not_stale_config(self):
        task = object.__new__(DailyTask)
        task.integrity_service = object()
        task.config = {DAILY_PROFILE: "A1", "Which to Farm": "stale"}
        task._runtime_overrides = {}
        task.load_daily_profiles = lambda: {
            "A1": {"profile_id": PROFILE_A, "Which to Farm": "master", "Nightmare Which to Farm": []}
        }
        snapshot = task._readonly_profile_config()
        self.assertEqual(snapshot["Which to Farm"], "master")
        self.assertEqual(task.config["Which to Farm"], "stale")
        snapshot["Nightmare Which to Farm"].append("mutated child copy")
        self.assertEqual(task.load_daily_profiles()["A1"]["Nightmare Which to Farm"], [])

    def test_runtime_override_does_not_mutate_daily_config(self):
        task = object.__new__(DailyTask)
        task.integrity_service = None
        task.config = {"Logout PC After Daily Task": True}
        task._runtime_overrides = {}
        with task.runtime_config_override("Logout PC After Daily Task", False):
            self.assertFalse(task.get_readonly_config_value("Logout PC After Daily Task"))
            self.assertTrue(task.config["Logout PC After Daily Task"])
        self.assertTrue(task.config["Logout PC After Daily Task"])

    def test_completion_records_use_explicit_profile_ids_without_cross_writes(self):
        self.service.accept_master_change(result=self.service.check())
        task = object.__new__(DailyTask)
        task.integrity_service = self.service
        task._verified_profile_id = PROFILE_A
        task._runtime_overrides = {}
        task.log_error = lambda *_args, **_kwargs: self.fail('completion write unexpectedly failed')
        task.record_last_completed('Daily Task', profile_id=PROFILE_A)
        task._verified_profile_id = PROFILE_B
        task.record_last_completed('Daily Task', profile_id=PROFILE_B)
        self.assertIsNotNone(self.service.get_completion(PROFILE_A, 'Daily Task'))
        self.assertIsNotNone(self.service.get_completion(PROFILE_B, 'Daily Task'))
        self.assertIsNone(self.service.get_completion(PROFILE_A, 'Merge Echo'))

    def test_completion_rejects_unknown_profile_id(self):
        self.service.accept_master_change(result=self.service.check())
        with self.assertRaises(ConfigIntegrityBlocked):
            self.service.record_completion('00000000-0000-4000-8000-000000000099', 'Daily Task')
        with self.assertRaises(ConfigIntegrityBlocked):
            self.service.get_completion('', 'Daily Task')

    def test_start_guard_wrapper_rejects_before_original(self):
        calls = []

        class Controller:
            def do_start(self, *_args, **_kwargs):
                calls.append("device-refresh")
                return True

        class Service:
            def guard_task_start(self):
                raise ConfigIntegrityBlocked("blocked")

        self.assertTrue(install_task_start_guard(Service(), Controller))
        self.assertFalse(Controller().do_start())
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
