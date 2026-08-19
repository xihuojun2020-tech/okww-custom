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
    diff_normalized,
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


def legacy_working_without_ids():
    data = working()
    for profile in data["profiles"].values():
        profile.pop("profile_id", None)
        profile.pop("display_name", None)
        profile.pop("account_aliases", None)
        profile.pop("schedule", None)
        profile.pop("extensions", None)
    return data


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

    def test_legacy_bootstrap_requires_confirmation_and_creates_trusted_master(self):
        self.service.paths.master.unlink()
        legacy = legacy_working_without_ids()
        legacy["ui_only_global"] = {"keep": True}
        legacy["profiles"]["A1"]["last_completed"] = {"Daily Task": "legacy-completion"}
        self.service.paths.working.write_text(
            json.dumps(legacy, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result = self.service.check()
        self.assertTrue(result.master_missing)
        self.assertFalse(result.ok)
        with self.assertRaisesRegex(ConfigIntegrityBlocked, "confirmation"):
            self.service.bootstrap_master_from_working(confirm=False)

        bootstrapped = self.service.bootstrap_master_from_working(confirm=True)
        self.assertTrue(bootstrapped.ok)
        generated = json.loads(self.service.paths.master.read_text(encoding="utf-8"))
        updated = json.loads(self.service.paths.working.read_text(encoding="utf-8"))
        self.assertEqual(generated["schema_version"], 1)
        self.assertEqual(generated["timezone"], "Asia/Shanghai")
        self.assertEqual(len(generated["profiles"]), 2)
        profile_ids = set(generated["profiles"])
        self.assertEqual(
            {profile["profile_id"] for profile in updated["profiles"].values()}, profile_ids
        )
        self.assertEqual(updated["ui_only_global"], {"keep": True})
        self.assertEqual(
            updated["profiles"]["A1"]["last_completed"], {"Daily Task": "legacy-completion"}
        )
        self.assertEqual(
            generated["profiles"][updated["profiles"]["A1"]["profile_id"]]["task_config"]["Which to Farm"],
            legacy["profiles"]["A1"]["Which to Farm"],
        )
        self.assertFalse(diff_normalized(normalize_master(generated), normalize_working(updated, generated)))
        runtime = json.loads(self.service.paths.runtime.read_text(encoding="utf-8"))
        self.assertEqual(runtime["accepted_master_fingerprint"], fingerprint(normalize_master(generated)))
        a1_id = updated["profiles"]["A1"]["profile_id"]
        self.assertEqual(runtime["completed_at"][a1_id]["Daily Task"], "legacy-completion")
        markers = sorted(path.name for path in result.event_dir.glob("RESOLVED_*"))
        self.assertEqual(markers, ["RESOLVED_BY_LEGACY_BOOTSTRAP"])

    def test_legacy_bootstrap_preserves_runtime_progress_and_completion(self):
        self.service.paths.master.unlink()
        self.service.paths.working.write_text(
            json.dumps(legacy_working_without_ids(), ensure_ascii=False), encoding="utf-8"
        )
        runtime = {
            "completed_at": {"legacy-A1": {"Daily Task": "2026-08-18 05:00:00"}},
            "progress": {"multi_account_daily": {"cursor": 3}},
            "future_runtime_field": {"keep": True},
        }
        self.service.paths.runtime.write_text(json.dumps(runtime), encoding="utf-8")
        self.assertTrue(self.service.bootstrap_master_from_working(confirm=True).ok)
        after = json.loads(self.service.paths.runtime.read_text(encoding="utf-8"))
        self.assertEqual(after["completed_at"], runtime["completed_at"])
        self.assertEqual(after["progress"], runtime["progress"])
        self.assertEqual(after["future_runtime_field"], runtime["future_runtime_field"])
        self.assertTrue(after["accepted_master_fingerprint"])

    def test_legacy_bootstrap_reuses_existing_ids_preserves_sequence_order_and_fills_defaults(self):
        self.service.paths.master.unlink()
        legacy = legacy_working_without_ids()
        legacy["profiles"]["A1"]["profile_id"] = PROFILE_A
        legacy["profiles"]["A3"]["profile_id"] = PROFILE_B
        legacy["profiles"]["A1"].pop("Merge Echo on Sunday")
        legacy["profiles"]["A3"].pop("备用识别名称内容")
        legacy["sequences"] = {"序列一": ["A3", "A1"]}
        self.service.paths.working.write_text(json.dumps(legacy), encoding="utf-8")

        self.assertTrue(self.service.bootstrap_master_from_working(confirm=True).ok)
        generated = json.loads(self.service.paths.master.read_text(encoding="utf-8"))
        updated = json.loads(self.service.paths.working.read_text(encoding="utf-8"))
        self.assertEqual(set(generated["profiles"]), {PROFILE_A, PROFILE_B})
        self.assertEqual(generated["sequences"]["序列一"], [PROFILE_B, PROFILE_A])
        self.assertFalse(generated["profiles"][PROFILE_A]["task_config"]["Merge Echo on Sunday"])
        self.assertEqual(generated["profiles"][PROFILE_B]["task_config"]["备用识别名称内容"], "")
        self.assertFalse(updated["profiles"]["A1"]["Merge Echo on Sunday"])
        self.assertEqual(updated["profiles"]["A3"]["备用识别名称内容"], "")

    def test_legacy_bootstrap_preserves_profile_key_as_login_alias(self):
        self.service.paths.master.unlink()
        legacy = legacy_working_without_ids()
        profile = legacy["profiles"].pop("A1")
        profile["display_name"] = "主账号"
        profile["account_aliases"] = ["U-A1"]
        legacy["profiles"]["A1:15300000001"] = profile
        legacy["sequences"] = {"序列一": ["A1:15300000001", "A3"]}
        self.service.paths.working.write_text(json.dumps(legacy), encoding="utf-8")

        self.assertTrue(self.service.bootstrap_master_from_working(confirm=True).ok)
        generated = json.loads(self.service.paths.master.read_text(encoding="utf-8"))
        updated = json.loads(self.service.paths.working.read_text(encoding="utf-8"))
        profile_id = updated["profiles"]["A1:15300000001"]["profile_id"]
        self.assertEqual(
            generated["profiles"][profile_id]["account_aliases"],
            ["U-A1", "A1:15300000001"],
        )
        self.assertEqual(generated["sequences"]["序列一"][0], profile_id)

    def test_legacy_bootstrap_blocks_missing_invalid_empty_and_ambiguous_working(self):
        self.service.paths.master.unlink()

        self.service.paths.working.unlink()
        with self.assertRaisesRegex(ConfigIntegrityBlocked, "working"):
            self.service.bootstrap_master_from_working(confirm=True)

        self.service.paths.working.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(ConfigIntegrityBlocked, "working"):
            self.service.bootstrap_master_from_working(confirm=True)

        self.service.paths.working.write_text(json.dumps({"profiles": {}}), encoding="utf-8")
        with self.assertRaisesRegex(ConfigIntegrityBlocked, "no account profiles"):
            self.service.bootstrap_master_from_working(confirm=True)

        ambiguous = legacy_working_without_ids()
        ambiguous["profiles"]["A1"]["account_aliases"] = ["same-login"]
        ambiguous["profiles"]["A3"]["account_aliases"] = ["same-login"]
        self.service.paths.working.write_text(json.dumps(ambiguous), encoding="utf-8")
        with self.assertRaisesRegex(ConfigIntegrityBlocked, "ambiguous"):
            self.service.bootstrap_master_from_working(confirm=True)
        self.assertFalse(self.service.paths.master.exists())
        controller = ConfigIntegrityDialogController(self.service)
        controller.acknowledge()
        self.assertFalse(controller.can_bootstrap_master)
        self.assertIn("ambiguous", controller.bootstrap_error)

    def test_legacy_bootstrap_blocks_corrupt_runtime_without_touching_files(self):
        self.service.paths.master.unlink()
        self.service.paths.working.write_text(
            json.dumps(legacy_working_without_ids(), ensure_ascii=False), encoding="utf-8"
        )
        self.service.paths.runtime.write_text("{broken", encoding="utf-8")
        working_before = self.service.paths.working.read_bytes()
        runtime_before = self.service.paths.runtime.read_bytes()
        with self.assertRaisesRegex(ConfigIntegrityBlocked, "runtime state is corrupt"):
            self.service.bootstrap_master_from_working(confirm=True)
        self.assertFalse(self.service.paths.master.exists())
        self.assertEqual(self.service.paths.working.read_bytes(), working_before)
        self.assertEqual(self.service.paths.runtime.read_bytes(), runtime_before)

        self.service.paths.runtime.write_text(json.dumps({"completed_at": []}), encoding="utf-8")
        with self.assertRaisesRegex(ConfigIntegrityBlocked, "completed_at"):
            self.service.bootstrap_master_from_working(confirm=True)
        controller = ConfigIntegrityDialogController(self.service)
        controller.acknowledge()
        self.assertFalse(controller.can_bootstrap_master)
        self.assertTrue(controller.can_rebuild_runtime)
        self.assertIn("completed_at", controller.bootstrap_error)

    def test_legacy_bootstrap_rolls_back_master_working_and_runtime_bytes(self):
        self.service.paths.master.unlink()
        self.service.paths.working.write_text(
            json.dumps(legacy_working_without_ids(), ensure_ascii=False, indent=4), encoding="utf-8"
        )
        self.service.paths.runtime.write_text(
            json.dumps({"progress": {"cursor": 7}}, indent=4), encoding="utf-8"
        )
        initial = self.service.check()
        working_before = self.service.paths.working.read_bytes()
        runtime_before = self.service.paths.runtime.read_bytes()
        failed = IntegrityResult(
            ok=False, master_valid=True, working_valid=True,
            master_fingerprint="failed", working_fingerprint="failed",
        )
        with patch.object(self.service, "check", side_effect=[initial, failed]):
            with self.assertRaisesRegex(ConfigIntegrityBlocked, "still inconsistent"):
                self.service.bootstrap_master_from_working(confirm=True)
        self.assertFalse(self.service.paths.master.exists())
        self.assertEqual(self.service.paths.working.read_bytes(), working_before)
        self.assertEqual(self.service.paths.runtime.read_bytes(), runtime_before)

    def test_bootstrapped_master_remains_read_only_after_migration(self):
        self.service.paths.master.unlink()
        self.service.paths.working.write_text(
            json.dumps(legacy_working_without_ids(), ensure_ascii=False), encoding="utf-8"
        )
        self.assertTrue(self.service.bootstrap_master_from_working(confirm=True).ok)
        with self.assertRaises(ConfigWriteBlocked):
            atomic_write_json(self.service.paths.master, master())
        with self.assertRaises(ConfigWriteBlocked):
            assert_master_read_only(self.service.paths.master)

    def test_first_anchor_reads_sequences_from_legacy_multi_account_task(self):
        self.service.paths.master.unlink()
        legacy = legacy_working_without_ids()
        legacy["sequences"] = {}
        legacy["profiles"]["A1"]["profile_id"] = PROFILE_A
        legacy["profiles"]["A3"]["profile_id"] = PROFILE_B
        self.service.paths.working.write_text(json.dumps(legacy), encoding="utf-8")
        self.service.paths.multi_account_task.write_text(json.dumps({
            "序列 1 账号": ["A3", "A1"], "序列 2 账号": []
        }, ensure_ascii=False), encoding="utf-8")
        self.assertTrue(self.service.bootstrap_master_from_working(confirm=True).ok)
        generated = json.loads(self.service.paths.master.read_text(encoding="utf-8"))
        self.assertEqual(generated["sequences"]["序列1"], [PROFILE_B, PROFILE_A])
        self.assertEqual(generated["sequences"]["序列2"], [])

    def test_empty_master_sequences_have_pure_detection_and_confirmed_recovery(self):
        empty = master()
        empty["sequences"] = {}
        self.service.paths.master.write_text(json.dumps(empty), encoding="utf-8")
        working_empty = working()
        working_empty["sequences"] = {}
        self.service.paths.working.write_text(json.dumps(working_empty), encoding="utf-8")
        self.service.paths.multi_account_task.write_text(json.dumps({
            "序列 1 账号": ["A1", "A3"], "序列 2 账号": [],
            "序列 3 账号": [], "序列 4 账号": [], "序列 5 账号": []
        }, ensure_ascii=False), encoding="utf-8")
        self.service.accept_master_change(result=self.service.check())
        before = self.service.paths.master.read_bytes()
        detected = self.service.detect_missing_sequences()
        self.assertTrue(detected["eligible"])
        self.assertEqual(detected["sequence_count"], 5)
        self.assertEqual(self.service.paths.master.read_bytes(), before)
        with self.assertRaises(ConfigIntegrityBlocked):
            self.service.repair_missing_sequences(confirm=False)
        recovered = self.service.repair_missing_sequences(confirm=True)
        self.assertTrue(recovered.ok)
        after = json.loads(self.service.paths.master.read_text(encoding="utf-8"))
        self.assertEqual(after["sequences"]["序列1"], [PROFILE_A, PROFILE_B])
        self.assertEqual(after["sequences"]["序列2"], [])
        self.assertEqual(after["sequences"]["序列5"], [])
        runtime = json.loads(self.service.paths.runtime.read_text(encoding="utf-8"))
        self.assertEqual(runtime["legacy_sequence_migration_v1"]["status"], "completed")

    def test_nonempty_master_sequences_never_recover_old_task_sequences(self):
        self.service.paths.multi_account_task.write_text(json.dumps({"序列 2 账号": ["A1"]}, ensure_ascii=False), encoding="utf-8")
        detected = self.service.detect_missing_sequences()
        self.assertFalse(detected["eligible"])
        self.assertIn("already contains", detected["reason"])

    def test_missing_sequence_recovery_rolls_back_all_three_files_byte_exactly(self):
        empty = master()
        empty["sequences"] = {}
        self.service.paths.master.write_text(json.dumps(empty, ensure_ascii=False, indent=4), encoding="utf-8")
        working_empty = working()
        working_empty["sequences"] = {}
        self.service.paths.working.write_text(json.dumps(working_empty, ensure_ascii=False, indent=2), encoding="utf-8")
        self.service.paths.multi_account_task.write_text(json.dumps({"序列 1 账号": ["A1", "A3"]}, ensure_ascii=False), encoding="utf-8")
        self.service.accept_master_change(result=self.service.check())
        before = {path: path.read_bytes() if path.exists() else None
                  for path in (self.service.paths.master, self.service.paths.working, self.service.paths.runtime)}
        initial = self.service.check(record_incident=False)
        failed = IntegrityResult(ok=False, master_valid=True, working_valid=True,
                                 master_fingerprint="failed", working_fingerprint="failed")
        with patch.object(self.service, "check", side_effect=[initial, initial, failed]):
            with self.assertRaisesRegex(ConfigIntegrityBlocked, "still inconsistent"):
                self.service.repair_missing_sequences(confirm=True)
        for path, payload in before.items():
            self.assertEqual(path.read_bytes() if path.exists() else None, payload)

    def test_dialog_uses_distinct_bootstrap_branch_and_rechecks_external_master(self):
        self.service.paths.master.unlink()
        self.service.paths.working.write_text(
            json.dumps(legacy_working_without_ids(), ensure_ascii=False), encoding="utf-8"
        )
        controller = ConfigIntegrityDialogController(self.service)
        self.assertTrue(controller.result.master_missing)
        self.assertFalse(controller.can_bootstrap_master)
        self.assertFalse(controller.can_apply_master)
        self.assertIn("锚定", controller.primary_action_label)
        controller.acknowledge()
        self.assertTrue(controller.can_bootstrap_master)
        self.assertFalse(controller.can_apply_master)

        self.service.paths.master.write_text(json.dumps(master()), encoding="utf-8")
        controller.recheck()
        self.assertFalse(controller.result.master_missing)
        self.assertFalse(controller.can_bootstrap_master)
        self.assertIn("覆盖", controller.primary_action_label)
        self.assertFalse(controller.can_apply_master)
        controller.acknowledge()
        self.assertTrue(controller.can_apply_master)

    def test_dialog_requires_new_acknowledgement_after_legacy_working_changes(self):
        self.service.paths.master.unlink()
        legacy = legacy_working_without_ids()
        self.service.paths.working.write_text(json.dumps(legacy), encoding="utf-8")
        controller = ConfigIntegrityDialogController(self.service)

        legacy["profiles"]["A1"]["Which to Farm"] = "Forgery Challenge"
        self.service.paths.working.write_text(json.dumps(legacy), encoding="utf-8")
        controller.acknowledge()
        self.assertFalse(controller.state.acknowledged)
        self.assertFalse(controller.can_bootstrap_master)
        controller.acknowledge()
        self.assertTrue(controller.can_bootstrap_master)

        legacy["profiles"]["A3"]["Which to Farm"] = "Simulation Challenge"
        self.service.paths.working.write_text(json.dumps(legacy), encoding="utf-8")
        with self.assertRaisesRegex(ConfigIntegrityBlocked, "changed after review"):
            controller.bootstrap_master()
        self.assertFalse(controller.state.acknowledged)
        self.assertFalse(self.service.paths.master.exists())

    def test_dialog_close_or_manual_choice_keeps_missing_master_in_safe_mode(self):
        self.service.paths.master.unlink()
        controller = ConfigIntegrityDialogController(self.service)
        controller.acknowledge()
        self.assertTrue(controller.can_bootstrap_master)
        controller.choose_manual_review()
        self.assertTrue(controller.blocked)
        self.assertFalse(self.service.paths.master.exists())

    def test_controller_primary_action_applies_first_deployment_master_and_removes_pollution(self):
        dirty = working()
        dirty["profiles"]["A1"]["Which to Farm"] = "Simulation Challenge"
        dirty["profiles"]["A1"]["polluted_old_option"] = "must disappear"
        self.service.paths.working.write_text(json.dumps(dirty), encoding="utf-8")
        controller = ConfigIntegrityDialogController(self.service)
        self.assertTrue(controller.result.master_changed)
        self.assertTrue(controller.result.differences)
        self.assertFalse(controller.can_apply_master)
        controller.acknowledge()
        self.assertTrue(controller.can_apply_master)
        result = controller.apply_master()
        self.assertTrue(result.ok)
        restored = json.loads(self.service.paths.working.read_text(encoding="utf-8"))
        self.assertNotIn("polluted_old_option", restored["profiles"]["A1"])
        self.assertEqual(restored["profiles"]["A1"]["Which to Farm"], "Tacet Suppression")

    def test_primary_action_handles_external_master_change_and_polluted_working(self):
        self.assertTrue(self.service.apply_master_to_working().ok)
        changed_master = master()
        changed_master["profiles"][PROFILE_A]["task_config"]["Which to Farm"] = "Simulation Challenge"
        self.service.paths.master.write_text(json.dumps(changed_master), encoding="utf-8")
        dirty = json.loads(self.service.paths.working.read_text(encoding="utf-8"))
        dirty["profiles"]["A1"]["Which to Farm"] = "Forgery Challenge"
        dirty["profiles"]["A1"]["stale_unknown"] = True
        self.service.paths.working.write_text(json.dumps(dirty), encoding="utf-8")
        controller = ConfigIntegrityDialogController(self.service)
        controller.recheck()
        controller.acknowledge()
        self.assertTrue(controller.result.master_changed)
        self.assertTrue(controller.can_apply_master)
        self.assertTrue(controller.apply_master().ok)
        restored = json.loads(self.service.paths.working.read_text(encoding="utf-8"))
        self.assertNotIn("stale_unknown", restored["profiles"]["A1"])
        self.assertEqual(restored["profiles"]["A1"]["Which to Farm"], "Simulation Challenge")

    def test_primary_action_repairs_working_only_pollution_and_preserves_runtime(self):
        self.assertTrue(self.service.apply_master_to_working().ok)
        self.service.record_completion(PROFILE_A, "Daily Task", when="completion")
        self.service.set_progress("cursor", 42)
        dirty = json.loads(self.service.paths.working.read_text(encoding="utf-8"))
        dirty["profiles"]["A1"]["working_only_pollution"] = {"bad": True}
        self.service.paths.working.write_text(json.dumps(dirty), encoding="utf-8")
        controller = ConfigIntegrityDialogController(self.service)
        controller.acknowledge()
        self.assertFalse(controller.result.master_changed)
        self.assertTrue(controller.can_apply_master)
        self.assertTrue(controller.apply_master().ok)
        self.assertEqual(self.service.get_completion(PROFILE_A, "Daily Task"), "completion")
        self.assertEqual(self.service.get_progress("cursor"), 42)
        restored = json.loads(self.service.paths.working.read_text(encoding="utf-8"))
        self.assertNotIn("working_only_pollution", restored["profiles"]["A1"])

    def test_combined_action_rolls_back_working_and_runtime_after_postcheck_failure(self):
        self.assertTrue(self.service.apply_master_to_working().ok)
        self.service.record_completion(PROFILE_A, "Daily Task", when="keep-completion")
        self.service.set_progress("keep-progress", {"cursor": 7})
        runtime_before = self.service.paths.runtime.read_bytes()

        changed_master = master()
        changed_master["profiles"][PROFILE_A]["task_config"]["Which to Farm"] = "Simulation Challenge"
        self.service.paths.master.write_text(json.dumps(changed_master), encoding="utf-8")
        dirty = json.loads(self.service.paths.working.read_text(encoding="utf-8"))
        dirty["profiles"]["A1"]["Which to Farm"] = "Forgery Challenge"
        self.service.paths.working.write_text(json.dumps(dirty), encoding="utf-8")
        working_before = self.service.paths.working.read_bytes()
        fresh = self.service.check()
        failed = IntegrityResult(
            ok=False, master_valid=True, working_valid=True,
            master=fresh.master, working=fresh.working,
            master_fingerprint=fresh.master_fingerprint,
            working_fingerprint=fresh.working_fingerprint,
            accepted_fingerprint=fresh.accepted_fingerprint,
        )
        with patch.object(self.service, "check", side_effect=[fresh, failed]):
            with self.assertRaises(ConfigIntegrityBlocked):
                self.service.apply_master_to_working(result=fresh)
        self.assertEqual(self.service.paths.working.read_bytes(), working_before)
        self.assertEqual(self.service.paths.runtime.read_bytes(), runtime_before)
        runtime = json.loads(self.service.paths.runtime.read_text(encoding="utf-8"))
        self.assertEqual(runtime["completed_at"][PROFILE_A]["Daily Task"], "keep-completion")
        self.assertEqual(runtime["progress"]["keep-progress"], {"cursor": 7})

    def test_combined_action_resolves_rebuilt_incident_with_single_restore_marker(self):
        self.assertTrue(self.service.apply_master_to_working().ok)
        dirty = json.loads(self.service.paths.working.read_text(encoding="utf-8"))
        dirty["profiles"]["A1"]["Which to Farm"] = "Simulation Challenge"
        self.service.paths.working.write_text(json.dumps(dirty), encoding="utf-8")
        pending = self.service.check()
        self.assertIsNotNone(pending.event_dir)
        self.assertTrue(self.service.apply_master_to_working(result=pending).ok)
        manifest = json.loads((pending.event_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "RESOLVED_BY_MASTER_RESTORE")
        self.assertFalse((pending.event_dir / "PENDING_REVIEW").exists())
        markers = sorted(path.name for path in pending.event_dir.glob("RESOLVED_*") )
        self.assertEqual(markers, ["RESOLVED_BY_MASTER_RESTORE"])

    def test_identical_working_with_unaccepted_master_needs_no_working_rewrite(self):
        before = self.service.paths.working.read_bytes()
        controller = ConfigIntegrityDialogController(self.service)
        controller.acknowledge()
        self.assertTrue(controller.result.master_changed)
        self.assertFalse(controller.result.differences)
        self.assertTrue(controller.can_apply_master)
        self.assertTrue(controller.apply_master().ok)
        self.assertEqual(self.service.paths.working.read_bytes(), before)

    def test_missing_or_invalid_master_disables_primary_action(self):
        self.service.paths.master.unlink()
        controller = ConfigIntegrityDialogController(self.service)
        controller.acknowledge()
        self.assertFalse(controller.result.master_valid)
        self.assertFalse(controller.can_apply_master)
        self.assertIn("account_master_config.json", str(self.service.master_path))

        self.service.paths.master.write_text("{broken", encoding="utf-8")
        result = controller.recheck()
        self.assertFalse(result.master_valid)
        self.assertFalse(result.master_missing)
        self.assertFalse(controller.can_apply_master)
        self.assertFalse(controller.can_bootstrap_master)

    def test_corrupt_runtime_disables_primary_and_allows_explicit_rebuild(self):
        self.assertTrue(self.service.apply_master_to_working().ok)
        self.service.paths.runtime.write_text("{broken", encoding="utf-8")
        controller = ConfigIntegrityDialogController(self.service)
        controller.recheck()
        controller.acknowledge()
        self.assertFalse(controller.can_apply_master)
        self.assertTrue(controller.can_rebuild_runtime)

    def test_external_master_edit_is_seen_after_controller_recheck(self):
        self.assertTrue(self.service.apply_master_to_working().ok)
        changed_master = master()
        changed_master["profiles"][PROFILE_B]["task_config"]["Which to Farm"] = "Simulation Challenge"
        self.service.paths.master.write_text(json.dumps(changed_master), encoding="utf-8")
        controller = ConfigIntegrityDialogController(self.service)
        result = controller.recheck()
        self.assertTrue(result.master_changed)
        controller.acknowledge()
        self.assertTrue(controller.can_apply_master)
        self.assertTrue(controller.apply_master().ok)

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
