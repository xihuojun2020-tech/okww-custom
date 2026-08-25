import copy
import json
import tempfile
import unittest
import uuid
from pathlib import Path

from src.account_config_editor import AccountConfigEditor, AccountLabelMismatch
from src.account_repository import AccountRepository, AccountRepositoryError, ProfileEditScope
from src.config_integrity import ConfigIntegrityService, fingerprint, normalize_master


class TestAccountDeletion(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "configs").mkdir()
        self.a, self.b = str(uuid.uuid4()), str(uuid.uuid4())
        self.master = {
            "schema_version": 2,
            "accounts": {
                self.a: {"profile_id": self.a, "short_name": "A1"},
                self.b: {"profile_id": self.b, "short_name": "A3"},
            },
            "sequences": {"S1": [self.a, self.b], "S2": [self.b]},
        }
        self.path = self.root / "configs" / "account_master_config.json"
        self.path.write_text(json.dumps(self.master), encoding="utf-8")
        self.repo = AccountRepository(self.root)
        self.repo._publish_master = lambda value: self.path.write_text(json.dumps(value), encoding="utf-8")
        self.repo.record_completion(self.b, "daily", "today")

    def tearDown(self):
        self.temp.cleanup()

    def test_cascade_delete_removes_all_references_and_runtime(self):
        record = self.repo.load_profile(self.b)
        preview = self.repo.preview_profile_deletion(self.b)
        self.assertEqual(preview.sequence_ids, ("S1", "S2"))
        self.repo.delete_profile_cascade(self.b, expected_revision=record.revision)
        self.assertNotIn(self.b, self.repo.list_profile_ids())
        self.assertEqual(self.repo.load_sequence("S1").profile_ids, (self.a,))
        self.assertEqual(self.repo.load_sequence("S2").profile_ids, ())
        self.assertFalse(self.repo._account_state_path(self.b).exists())
        self.assertTrue(any((self.repo.backup_dir / self.b).iterdir()))

    def test_failure_restores_master_and_runtime_and_last_account_is_protected(self):
        before_master = self.path.read_bytes()
        before_state = self.repo._account_state_path(self.b).read_bytes()
        self.repo.deletion_postcheck_hook = lambda: (_ for _ in ()).throw(RuntimeError("forced"))
        with self.assertRaisesRegex(RuntimeError, "forced"):
            self.repo.delete_profile_cascade(self.b, expected_revision=self.repo.load_profile(self.b).revision)
        self.assertEqual(self.path.read_bytes(), before_master)
        self.assertEqual(self.repo._account_state_path(self.b).read_bytes(), before_state)
        del self.master["accounts"][self.b]
        self.master["sequences"] = {"S1": [self.a]}
        self.path.write_text(json.dumps(self.master), encoding="utf-8")
        with self.assertRaisesRegex(AccountRepositoryError, "至少必须保留"):
            self.repo.delete_profile_cascade(self.a, expected_revision=self.repo.load_profile(self.a).revision)

    def test_editor_requires_exact_account_label(self):
        editor = AccountConfigEditor(self.repo)
        record = self.repo.load_profile(self.b)
        with self.assertRaises(AccountLabelMismatch):
            editor.delete_profile(ProfileEditScope(self.b, record.revision), confirmed_account_label="A4")

    def test_schema_v1_deletion_uses_real_integrity_transaction(self):
        tasks = {
            "Which to Farm": "Tacet Suppression", "Which Tacet Suppression to Farm": 1,
            "Which Forgery Challenge to Farm": 1, "Material Selection": "Shell Credit",
            "Farm Nightmare Nest for Daily Echo": False, "Nightmare Which to Farm": [],
            "Tacet Discord Nests to Farm": [], "Auto Farm all Nightmare Nest": False,
            "Weekly Garden Check Day": "无", "Merge Echo on Sunday": False,
            "备用识别名称": "无", "备用识别名称内容": "",
        }
        master = {
            "schema_version": 1, "config_id": "deletion-test", "timezone": "Asia/Shanghai",
            "profiles": {
                self.a: {"display_name": "A1", "account_aliases": ["A1"],
                         "task_config": tasks, "schedule": {}, "extensions": {}},
                self.b: {"display_name": "A3", "account_aliases": ["A3"],
                         "task_config": tasks, "schedule": {}, "extensions": {}},
            },
            "sequences": {"S1": [self.a, self.b]}, "extensions": {},
        }
        service = ConfigIntegrityService(self.root)
        service.paths.master.write_text(json.dumps(master, ensure_ascii=False), encoding="utf-8")
        projection = service._rebuild_working(master, {})
        service.paths.working.write_text(json.dumps(projection, ensure_ascii=False), encoding="utf-8")
        service.paths.runtime.write_text(json.dumps({
            "accepted_master_fingerprint": fingerprint(normalize_master(master)),
            "completed_at": {}, "progress": {},
        }), encoding="utf-8")
        repository = AccountRepository(self.root, integrity_service=service)

        repository.delete_profile_cascade(
            self.b, expected_revision=repository.load_profile(self.b).revision)

        published = json.loads(service.paths.master.read_text(encoding="utf-8"))
        self.assertNotIn(self.b, published["profiles"])
        self.assertEqual(published["sequences"], {"S1": [self.a]})
        self.assertTrue(service.check(record_incident=False).ok)


if __name__ == "__main__":
    unittest.main()
