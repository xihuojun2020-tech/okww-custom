import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from src.account_config_bundle import (
    AccountConfigBundleService,
    BundleImportBlocked,
    ConfigBundleError,
    SequenceSourceConflict,
    extract_task_sequences,
    merge_sequence_sources,
)
from src.config_integrity import ConfigIntegrityService, fingerprint, normalize_master


PROFILE_A = "0f7b7f52-9da7-4b43-bbc2-9be7c539f801"
PROFILE_B = "1f7b7f52-9da7-4b43-bbc2-9be7c539f802"


def _task_config():
    return {
        "Which to Farm": "Tacet Suppression", "Which Tacet Suppression to Farm": 1,
        "Which Forgery Challenge to Farm": 1, "Material Selection": "Shell Credit",
        "Farm Nightmare Nest for Daily Echo": False, "Nightmare Which to Farm": [],
        "Tacet Discord Nests to Farm": [], "Auto Farm all Nightmare Nest": False,
        "Weekly Garden Check Day": "无", "Merge Echo on Sunday": False,
        "备用识别名称": "无", "备用识别名称内容": "",
    }


def _master(sequences=None):
    return {
        "schema_version": 1, "config_id": "bundle-test", "timezone": "Asia/Shanghai",
        "profiles": {
            PROFILE_A: {"display_name": "A1", "account_aliases": ["A1", "199****0001"],
                        "task_config": _task_config(), "schedule": {}, "extensions": {}},
            PROFILE_B: {"display_name": "A3", "account_aliases": ["A3", "199****0006"],
                        "task_config": _task_config(), "schedule": {}, "extensions": {}},
        }, "sequences": sequences or {"序列1": [PROFILE_A, PROFILE_B]}, "extensions": {},
    }


class TestAccountConfigBundle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "configs").mkdir()
        self.master = _master()
        (self.root / "configs/account_master_config.json").write_text(
            json.dumps(self.master, ensure_ascii=False), encoding="utf-8")
        # The compatibility projection must itself be valid before export.
        projection = ConfigIntegrityService(self.root)._rebuild_working(self.master, {})
        (self.root / "configs/daily_profiles.json").write_text(
            json.dumps(projection, ensure_ascii=False), encoding="utf-8")
        self.service = ConfigIntegrityService(self.root)
        self.service.paths.runtime.write_text(json.dumps({"accepted_master_fingerprint": fingerprint(normalize_master(self.master)),
                                                          "completed_at": {}, "progress": {}}), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_import_updates_existing_active_and_fresh_reader(self):
        from src.account_repository import AccountRepository
        repo = AccountRepository(self.root, integrity_service=self.service)
        repo._publish_master(self.master)
        bundles = AccountConfigBundleService(self.root, integrity_service=self.service)
        candidate = bundles.export_bundle()
        candidate['master_config']['profiles'][PROFILE_A]['task_config']['Which Tacet Suppression to Farm'] = 2
        result = bundles.import_bundle(candidate, confirm=True, trust_external=True)
        self.assertTrue(result.published_revision)
        for reader in (repo, AccountRepository(self.root, integrity_service=self.service)):
            self.assertEqual(reader.load_profile(PROFILE_A).tasks['Which Tacet Suppression to Farm'], 2)

    def test_stale_preview_rejected_and_edit_preserves_latest_progress(self):
        from src.account_repository import AccountRepository, ProfileRevisionConflict
        bundles = AccountConfigBundleService(self.root, integrity_service=self.service)
        candidate = bundles.export_bundle()
        preview = bundles.preflight_import(candidate)
        self.service.record_completion(PROFILE_A, 'daily', 'newest')
        self.service.paths.multi_account_task.write_text('{"latest_preference": true}', encoding='utf-8')
        candidate['master_config']['profiles'][PROFILE_A]['task_config']['Which Tacet Suppression to Farm'] = 2
        bundles.import_bundle(candidate, confirm=True, trust_external=True, preserve_runtime_and_preferences=True)
        self.assertEqual(self.service.get_completion(PROFILE_A, 'daily'), 'newest')
        self.assertEqual(json.loads(self.service.paths.multi_account_task.read_text()), {'latest_preference': True})
        with self.assertRaises(ProfileRevisionConflict):
            bundles.import_bundle(preview.bundle, preflight=preview, confirm=True)
        self.assertEqual(AccountRepository(self.root).load_profile(PROFILE_A).tasks['Which Tacet Suppression to Farm'], 2)

    def test_running_executor_blocks_external_import_but_allows_parameter_edit(self):
        import ok
        from types import SimpleNamespace
        service = AccountConfigBundleService(self.root)
        bundle = service.export_bundle()
        with patch.object(ok.og, 'executor', SimpleNamespace(current_task=object())):
            with self.assertRaisesRegex(BundleImportBlocked, '先停止任务'):
                service.import_bundle(bundle, confirm=True)
            self.assertTrue(service.import_bundle(bundle, confirm=True, preserve_runtime_and_preferences=True).ok)

    def test_corrupt_recovery_snapshot_is_preserved_without_guessing(self):
        from src.account_publish_service import AccountPublishService
        bundles = AccountConfigBundleService(self.root)
        candidate = bundles.export_bundle()
        candidate['master_config']['profiles'][PROFILE_A]['task_config']['Which Tacet Suppression to Farm'] = 2
        with patch.object(AccountPublishService, '_write_active_pointer', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                bundles.import_bundle(candidate, confirm=True, trust_external=True)
        intact = bundles._journal_path.read_bytes()
        damaged = json.loads(intact)
        damaged['before']['master']['data'] = 'invalid base64!'
        bundles._journal_path.write_text(json.dumps(damaged), encoding='utf-8')
        before = self.service.paths.master.read_bytes()
        with self.assertRaises(ConfigBundleError):
            bundles.recover_incomplete_transactions()
        self.assertTrue(bundles._journal_path.exists())
        self.assertEqual(self.service.paths.master.read_bytes(), before)
        bundles._journal_path.write_bytes(intact)
        bundles.recover_incomplete_transactions()
        self.assertTrue(self.service.check(record_incident=False).ok)

    def test_completion_waiting_during_edit_is_not_lost(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        entered, attempted = Event(), Event()
        def snapshot_hook(_before):
            entered.set()
            self.assertTrue(attempted.wait(5))
        bundles = AccountConfigBundleService(self.root, transaction_snapshot_hook=snapshot_hook)
        candidate = bundles.export_bundle()
        candidate['master_config']['profiles'][PROFILE_A]['task_config']['Which Tacet Suppression to Farm'] = 2
        def complete():
            self.assertTrue(entered.wait(5))
            attempted.set()
            self.service.record_completion(PROFILE_A, 'daily', 'concurrent')
        with ThreadPoolExecutor(max_workers=2) as executor:
            writer = executor.submit(bundles.import_bundle, candidate, confirm=True,
                                     trust_external=True, preserve_runtime_and_preferences=True)
            completion = executor.submit(complete)
            writer.result(timeout=15)
            completion.result(timeout=15)
        self.assertEqual(self.service.get_completion(PROFILE_A, 'daily'), 'concurrent')

    def test_forced_process_exit_recovers_pre_and_post_commit_including_same_revision(self):
        from tests.fixture_support import make_account_environment, synthetic_identity
        from src.account_repository import AccountRepository
        child = r'''
import os, sys
from src.account_config_bundle import AccountConfigBundleService
from src.account_publish_service import AccountPublishService
root, phase, same = sys.argv[1:]
service = AccountConfigBundleService(root)
bundle = service.export_bundle()
if same == 'False':
    pid = list(bundle['master_config']['profiles'])[1]
    del bundle['master_config']['profiles'][pid]
    bundle['master_config']['sequences']['S1'].remove(pid)
bundle['runtime_data']['progress'] = {'transaction_probe': 'new'}
write = service._write_journal
def journal(value):
    write(value)
    if value['phase'] == phase:
        os._exit(73)
service._write_journal = journal
activate = AccountPublishService._write_active_pointer
def pointer(self, *args):
    if phase == 'ACTIVE_BEFORE': os._exit(73)
    activate(self, *args)
    if phase == 'ACTIVE_AFTER': os._exit(73)
AccountPublishService._write_active_pointer = pointer
service.import_bundle(bundle, confirm=True, trust_external=True)
'''
        for same in (False, True):
            for phase in ('PREPARED', 'LEGACY_WRITTEN', 'ACTIVE_BEFORE', 'ACTIVE_AFTER', 'COMMITTED'):
                with self.subTest(same=same, phase=phase):
                    root = self.root / f'{same}-{phase}'
                    env = make_account_environment(root, names=('A1', 'A3'))
                    deleted = synthetic_identity('A3')['profile_id']
                    env.repository.record_completion(deleted, 'daily', 'old')
                    service = AccountConfigBundleService(root)
                    targets = service._transaction_targets([deleted])
                    before = {path: path.read_bytes() if path.exists() else None for path in targets.values()}
                    result = subprocess.run([sys.executable, '-c', child, str(root), phase, str(same)],
                                            capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 73, result.stderr)
                    service.recover_incomplete_transactions()
                    committed = phase == 'COMMITTED' or (not same and phase == 'ACTIVE_AFTER')
                    if not committed:
                        for path, payload in before.items():
                            self.assertEqual(path.read_bytes() if path.exists() else None, payload)
                    else:
                        self.assertEqual(env.integrity.get_progress('transaction_probe'), 'new')
                    self.assertEqual(deleted in AccountRepository(root).list_profile_ids(), same or not committed)
                    self.assertTrue(env.integrity.check(record_incident=False).ok)
                    self.assertFalse(service._journal_path.exists())

    def test_two_processes_cannot_commit_the_same_preview(self):
        from tests.fixture_support import make_account_environment
        from src.account_repository import AccountRepository
        root = self.root / 'concurrent'
        make_account_environment(root)
        child = r'''
import sys, time
from pathlib import Path
from src.account_config_bundle import AccountConfigBundleService
from src.account_repository import ProfileRevisionConflict
root, slot = sys.argv[1:]
service = AccountConfigBundleService(root)
bundle = service.export_bundle()
next(iter(bundle['master_config']['profiles'].values()))['task_config']['Which Tacet Suppression to Farm'] = int(slot) + 2
preview = service.preflight_import(bundle)
Path(root, 'ready' + slot).touch()
end = time.monotonic() + 10
while not all(Path(root, 'ready' + n).exists() for n in ('0', '1')):
    if time.monotonic() > end: raise RuntimeError('barrier timed out')
    time.sleep(0.02)
try:
    service.import_bundle(bundle, preflight=preview, confirm=True, trust_external=True)
except ProfileRevisionConflict:
    sys.exit(2)
'''
        processes = [subprocess.Popen([sys.executable, '-c', child, str(root), str(slot)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE) for slot in range(2)]
        try:
            for process in processes:
                output = process.communicate(timeout=30)
                self.assertIn(process.returncode, (0, 2), output)
            self.assertEqual(sorted(p.returncode for p in processes), [0, 2])
            self.assertIn(AccountRepository(root).list_profiles()[0].tasks['Which Tacet Suppression to Farm'], (2, 3))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.communicate()

    def test_task_sequence_extraction_preserves_empty_and_numeric_order(self):
        actual = extract_task_sequences({"序列 2 账号": ["A3"], "序列 1 账号": [], "other": 1})
        self.assertEqual(actual, {"序列1": [], "序列2": ["A3"]})

    def test_two_sources_equal_after_normalization_are_accepted(self):
        result = merge_sequence_sources({"序列一": ["A1", "A3"]}, {"序列 1 账号": ["A1", "A3"]})
        self.assertEqual(result.sequences, {"序列一": ["A1", "A3"]})
        self.assertEqual(result.source, "both_equal")

    def test_two_nonempty_conflicting_sources_are_blocked(self):
        with self.assertRaises(SequenceSourceConflict):
            merge_sequence_sources({"序列一": ["A1"]}, {"序列 1 账号": ["A3"]})

    def test_export_preflight_and_confirmed_import(self):
        bundle = AccountConfigBundleService(self.root, integrity_service=self.service)
        path = self.root / "export.json"
        exported = bundle.export_bundle(path)
        self.assertEqual(exported["bundle_version"], 3)
        self.assertIn("master_config", exported)
        preflight = bundle.preflight_import(path)
        self.assertTrue(preflight.ok)
        with self.assertRaises(BundleImportBlocked):
            bundle.import_bundle(path)
        imported = bundle.import_bundle(path, confirm=True)
        self.assertTrue(imported.ok)
        self.assertGreaterEqual(imported.account_count, 0)
        self.assertTrue(imported.diff_summary)

    def test_new_profile_template_round_trips_inside_master_extensions(self):
        template = {**_task_config(), "Which to Farm": "Forgery Challenge"}
        self.master["extensions"]["new_profile_template"] = template
        self.service.paths.master.write_text(
            json.dumps(self.master, ensure_ascii=False), encoding="utf-8")
        self.service.paths.working.write_text(
            json.dumps(self.service._rebuild_working(self.master, {}), ensure_ascii=False),
            encoding="utf-8",
        )
        self.service.paths.runtime.write_text(json.dumps({
            "accepted_master_fingerprint": fingerprint(normalize_master(self.master)),
            "completed_at": {}, "progress": {},
        }), encoding="utf-8")
        bundle = AccountConfigBundleService(self.root, integrity_service=self.service)

        exported = bundle.export_bundle()
        self.assertEqual(
            exported["master_config"]["extensions"]["new_profile_template"], template)
        imported = bundle.import_bundle(exported, confirm=True)

        self.assertTrue(imported.ok)
        restored = json.loads(self.service.paths.master.read_text(encoding="utf-8"))
        self.assertEqual(restored["extensions"]["new_profile_template"], template)

    def test_export_recursively_redacts_credentials_but_keeps_full_phone_identity(self):
        self.master["extensions"] = {
            "password": "secret-password", "nested": {
                "token": "secret-token",
                "auth_url": "https://example.invalid/oauth/token?pat=secret-pat",
            },
            "phone_identity": "19910000003",
        }
        self.service.paths.master.write_text(json.dumps(self.master, ensure_ascii=False), encoding="utf-8")
        self.service.paths.working.write_text(
            json.dumps(ConfigIntegrityService(self.root)._rebuild_working(self.master, {}), ensure_ascii=False),
            encoding="utf-8")
        self.service.paths.runtime.write_text(
            json.dumps({"accepted_master_fingerprint": fingerprint(normalize_master(self.master))}),
            encoding="utf-8")
        exported = AccountConfigBundleService(self.root, integrity_service=self.service).export_bundle()
        serialized = json.dumps(exported, ensure_ascii=False)
        for secret in ("secret-password", "secret-token", "secret-pat"):
            self.assertNotIn(secret, serialized)
        self.assertEqual(exported["master_config"]["extensions"]["phone_identity"], "19910000003")
        self.assertEqual(exported["master_config"]["extensions"]["password"], "[REDACTED]")

    def test_v3_malformed_nested_shapes_are_blocked_in_preflight(self):
        service = AccountConfigBundleService(self.root, integrity_service=self.service)
        bundle = service.export_bundle()
        bundle["master_config"]["sequences"]["序列1"] = [{}]
        malformed = service.preflight_import(bundle)
        self.assertFalse(malformed.ok)
        self.assertTrue(any("成员必须是字符串" in error for error in malformed.errors))

        bundle = service.export_bundle()
        bundle["device"] = "not-an-object"
        malformed = service.preflight_import(bundle)
        self.assertFalse(malformed.ok)
        self.assertTrue(any("device" in error for error in malformed.errors))

    def test_overwriting_existing_account_requires_strict_shape(self):
        service = AccountConfigBundleService(self.root, integrity_service=self.service)
        bundle = service.export_bundle()
        bundle["master_config"]["profiles"][PROFILE_A] = []
        preflight = service.preflight_import(bundle)
        self.assertFalse(preflight.ok)
        with self.assertRaises(ConfigBundleError):
            service.import_bundle(bundle, confirm=True, trust_external=True)

    def test_export_and_import_drop_machine_local_runtime_metadata(self):
        runtime = {
            "accepted_master_fingerprint": fingerprint(normalize_master(self.master)),
            "last_accepted_fingerprint": "obsolete-device-a-fingerprint",
            "last_integrity_event": "C:/device-a/private/incident",
            "last_bundle_import": "2026-01-01T00:00:00+00:00",
            "completed_at": {PROFILE_A: {"DailyTask": "2026-08-18T00:00:00+00:00"}},
            "progress": {PROFILE_A: {"step": 2}},
            "future_portable_field": {"keep": True},
        }
        self.service.paths.runtime.write_text(json.dumps(runtime), encoding="utf-8")
        service = AccountConfigBundleService(self.root, integrity_service=self.service)
        exported = service.export_bundle()
        for key in ("accepted_master_fingerprint", "last_accepted_fingerprint",
                    "last_integrity_event", "last_bundle_import"):
            self.assertNotIn(key, exported["runtime_data"])
        self.assertEqual(exported["runtime_data"]["progress"][PROFILE_A]["step"], 2)
        self.assertEqual(exported["runtime_data"]["future_portable_field"], {"keep": True})

        # Older/external v2 files may still contain these fields.  Rehash the
        # changed runtime partition to prove a valid file cannot import them.
        exported["runtime_data"]["last_integrity_event"] = "D:/other-device/incident"
        from src.account_config_bundle import _digest
        exported["manifest"]["partitions"]["runtime_data"] = _digest(exported["runtime_data"])
        preflight = service.preflight_import(exported)
        self.assertTrue(preflight.ok, preflight.errors)
        self.assertNotIn("last_integrity_event", preflight.candidate_runtime)

    def test_modified_manifest_requires_explicit_trust(self):
        bundle = AccountConfigBundleService(self.root, integrity_service=self.service)
        path = self.root / "export.json"
        bundle.export_bundle(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["master_config"]["profiles"][PROFILE_A]["display_name"] = "A1-renamed"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        preflight = bundle.preflight_import(path)
        self.assertTrue(preflight.trust_required)
        with self.assertRaises(BundleImportBlocked):
            bundle.import_bundle(path, confirm=True)
        self.assertTrue(bundle.import_bundle(path, confirm=True, trust_external=True).ok)

    def test_v2_missing_partition_hashes_and_unknown_type_are_rejected(self):
        bundle = AccountConfigBundleService(self.root, integrity_service=self.service)
        path = self.root / "export.json"
        bundle.export_bundle(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["manifest"]["partitions"].pop("runtime_data")
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        preflight = bundle.preflight_import(path)
        self.assertFalse(preflight.ok)
        self.assertTrue(any("hashes" in item for item in preflight.errors))
        data["manifest"]["partitions"]["runtime_data"] = "0" * 64
        data["type"] = "unknown_bundle"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        unknown = bundle.preflight_import(path)
        self.assertFalse(unknown.ok)
        self.assertTrue(any("unsupported account bundle" in item for item in unknown.errors))

    def test_current_execution_account_is_never_exported_or_imported(self):
        task_path = self.service.paths.multi_account_task
        task_path.write_text(json.dumps({"当前执行账号": "A3", "future": 1}, ensure_ascii=False), encoding="utf-8")
        bundle = AccountConfigBundleService(self.root, integrity_service=self.service)
        exported = bundle.export_bundle()
        self.assertNotIn("当前执行账号", exported["preferences"])
        exported["preferences"]["当前执行账号"] = "A1"
        imported = bundle.preflight_import(exported)
        self.assertNotIn("当前执行账号", imported.candidate_preferences)

    def test_twelve_account_legacy_task_keeps_four_eight_and_empty_sequences(self):
        profiles = {}
        names = [f"A{i}" for i in range(1, 13)]
        ids = {}
        for name in names:
            profile_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "okww:" + name))
            ids[name] = profile_id
            profiles[profile_id] = {"display_name": name, "account_aliases": [name],
                                    "task_config": _task_config(), "schedule": {}, "extensions": {}}
        master = {"schema_version": 1, "config_id": "twelve", "timezone": "Asia/Shanghai",
                  "profiles": profiles, "sequences": {}, "extensions": {}}
        task = {f"序列 {i} 账号": (names[:4] if i == 1 else names[4:] if i == 2 else [])
                for i in range(1, 6)}
        merged = merge_sequence_sources({}, extract_task_sequences(task))
        resolved = __import__("src.account_config_bundle", fromlist=["resolve_sequence_members"]).resolve_sequence_members(merged.sequences, master)
        self.assertEqual(resolved["序列1"], [ids[name] for name in names[:4]])
        self.assertEqual(resolved["序列2"], [ids[name] for name in names[4:]])
        self.assertEqual([resolved[f"序列{i}"] for i in range(3, 6)], [[], [], []])

    def test_v1_flat_profiles_are_upgraded_to_uuid_master(self):
        v1 = {"type": "okww_account_config", "version": 1,
              "profiles": {"A1": {**_task_config(), "display_name": "A1", "account_aliases": ["A1"]}},
              "sequences": {"序列 1": ["A1"]}}
        preflight = AccountConfigBundleService(self.root, integrity_service=self.service).preflight_import(v1)
        self.assertTrue(preflight.ok, preflight.errors)
        self.assertEqual(len(preflight.candidate_master["profiles"]), 1)
        self.assertEqual(len(preflight.candidate_master["sequences"]["序列1"]), 1)

    def test_v1_embedded_completion_is_migrated_to_uuid_runtime(self):
        v1 = {"type": "okww_account_config", "version": 1,
              "profiles": {"A1": {**_task_config(), "display_name": "A1",
                                    "account_aliases": ["A1"],
                                    "last_completed": {"DailyTask": "legacy-time",
                                                       "ExistingTask": "embedded-older"}}},
              "sequences": {"序列 1": ["A1"]},
              "runtime": {"completed_at": {}}}
        service = AccountConfigBundleService(self.root, integrity_service=self.service)
        preflight = service.preflight_import(v1)
        self.assertTrue(preflight.ok, preflight.errors)
        profile_id = next(iter(preflight.candidate_master["profiles"]))
        self.assertNotIn("last_completed", preflight.candidate_master["profiles"][profile_id])
        self.assertEqual(preflight.candidate_runtime["completed_at"][profile_id]["DailyTask"], "legacy-time")
        imported = service.import_bundle(v1, confirm=True)
        runtime = json.loads(self.service.paths.runtime.read_text(encoding="utf-8"))
        self.assertEqual(runtime["completed_at"][profile_id]["ExistingTask"], "embedded-older")

    def test_import_preserves_non_exported_preferences_and_calls_snapshot_hook(self):
        task_path = self.service.paths.multi_account_task
        task_path.write_text(json.dumps({"future_setting": {"keep": True}, "序列 1 账号": ["A1"]}, ensure_ascii=False), encoding="utf-8")
        snapshots = []
        bundle = AccountConfigBundleService(self.root, integrity_service=self.service,
                                            transaction_snapshot_hook=lambda before: snapshots.append(before))
        path = self.root / "export.json"
        bundle.export_bundle(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["preferences"].pop("future_setting", None)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        bundle.import_bundle(path, confirm=True, trust_external=True)
        restored_task = json.loads(task_path.read_text(encoding="utf-8"))
        self.assertEqual(restored_task["future_setting"], {"keep": True})
        self.assertTrue(snapshots)
        self.assertTrue(list((self.root / "config_bundle_transactions").glob("*/manifest.json")))

    def test_empty_master_bootstrap_recovers_real_four_eight_task_layout(self):
        # Integration regression for the production shape: no working
        # top-level sequences, four members in sequence 1, eight in sequence
        # 2, and explicitly retained empty sequences 3-5.
        self.service.paths.master.unlink()
        profiles = {}
        ids = {}
        names = [f"A{i}" for i in range(1, 13)]
        for name in names:
            profile_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "bootstrap:" + name))
            ids[name] = profile_id
            profiles[name] = {"profile_id": profile_id, "display_name": name,
                              "account_aliases": [name], **_task_config()}
        self.service.paths.working.write_text(json.dumps({"profiles": profiles, "sequences": {}}, ensure_ascii=False), encoding="utf-8")
        self.service.paths.multi_account_task.write_text(json.dumps({
            "序列 1 账号": names[:4], "序列 2 账号": names[4:],
            "序列 3 账号": [], "序列 4 账号": [], "序列 5 账号": []}, ensure_ascii=False), encoding="utf-8")
        result = self.service.bootstrap_master_from_working(confirm=True)
        self.assertTrue(result.ok)
        generated = json.loads(self.service.paths.master.read_text(encoding="utf-8"))
        self.assertEqual(generated["sequences"]["序列1"], [ids[name] for name in names[:4]])
        self.assertEqual(generated["sequences"]["序列2"], [ids[name] for name in names[4:]])
        self.assertEqual([generated["sequences"][f"序列{i}"] for i in range(3, 6)], [[], [], []])


if __name__ == "__main__":
    unittest.main()
