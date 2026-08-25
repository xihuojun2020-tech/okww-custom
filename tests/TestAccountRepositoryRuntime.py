import json
import tempfile
import unittest
import uuid
from pathlib import Path

from src.account_repository import (
    AccountRepository,
    AccountRepositoryError,
    get_default_repository,
    set_default_repository,
)


class _Migration:
    def __init__(self):
        self.calls = 0

    def recover_incomplete_transactions(self):
        self.calls += 1
        return True


class TestAccountRepositoryRuntime(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        configs = self.root / "configs"
        configs.mkdir()
        self.a = str(uuid.uuid4())
        self.b = str(uuid.uuid4())
        (configs / "account_master_config.json").write_text(json.dumps({
            "schema_version": 2,
            "accounts": {
                self.a: {"profile_id": self.a, "short_name": "A1"},
                self.b: {"profile_id": self.b, "short_name": "A3"},
            },
            "sequences": {"主序列": [self.a, self.b]},
        }, ensure_ascii=False), encoding="utf-8")
        self.repo = AccountRepository(self.root)

    def tearDown(self):
        set_default_repository(None)
        self.temp.cleanup()

    def test_completion_isolated_per_account(self):
        self.repo.record_completion(self.a, "Daily Task", "今天")
        self.assertEqual(self.repo.get_completion(self.a, "Daily Task"), "今天")
        self.assertEqual(self.repo.get_profile_completions(self.b), {})
        self.assertTrue((self.root / "运行状态" / "账号" / f"{self.a}.json").is_file())
        self.assertFalse((self.root / "运行状态" / "账号" / f"{self.b}.json").exists())

    def test_progress_has_own_global_file(self):
        self.repo.set_progress("cursor", {"账号": self.a, "step": 2})
        self.assertEqual(self.repo.get_progress("cursor")["账号"], self.a)
        self.assertEqual(json.loads(self.repo.progress_path.read_text(encoding="utf-8"))["cursor"]["step"], 2)
        self.assertEqual(self.repo.get_profile_completions(self.a), {})

    def test_recovery_and_default_lifecycle(self):
        migration = _Migration()
        repo = AccountRepository(self.root, migration_service=migration)
        self.assertTrue(repo.recover_incomplete_transactions())
        self.assertEqual(migration.calls, 1)
        self.assertIsNone(get_default_repository())
        set_default_repository(repo)
        self.assertIs(get_default_repository(), repo)
        set_default_repository(None)
        self.assertIsNone(get_default_repository())

    def test_chinese_validation_and_external_change_scope(self):
        with self.assertRaisesRegex(AccountRepositoryError, "账号 UUID 无效"):
            self.repo.get_completion("不是 UUID", "Daily Task")
        result = self.repo.verify_ready()
        self.assertTrue(result.ok)
        self.assertEqual(result.external_changes, [])
        raw = json.loads(self.repo.index_path.read_text(encoding="utf-8"))
        raw["accounts"][self.a]["short_name"] = "外部修改"
        self.repo.index_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        changed = self.repo.verify_ready()
        self.assertTrue(changed.ok)
        self.assertIn(self.a, changed.accounts)

    def test_backup_rejects_cross_account_payload(self):
        with self.assertRaisesRegex(AccountRepositoryError, "备份越界"):
            self.repo.backup_profile(self.a, {"profile_id": self.b})
        path = self.repo.backup_profile(self.a, {"name": "A1"})
        self.assertEqual(path.parent.name, self.a)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["profile_id"], self.a)


if __name__ == "__main__":
    unittest.main()
