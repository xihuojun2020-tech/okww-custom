import copy
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

from src.account_repository import (
    AccountRepository,
    AccountRepositoryError,
    ProfileRevisionConflict,
    get_default_repository,
    set_default_repository,
)
from src.account_publish_service import AccountPublishService
from src.config_integrity import _BOOTSTRAP_TASK_DEFAULTS, validate_master


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

    def _memory_repo(self):
        repo = AccountRepository.__new__(AccountRepository)
        repo._lock = threading.RLock()
        repo.raw = {
            "schema_version": 1,
            "config_id": "test",
            "timezone": "Asia/Shanghai",
            "profiles": {
                self.a: {
                    "profile_id": self.a,
                    "display_name": "A1",
                    "phone": "19910000001",
                    "masked_phone": "199****0001",
                    "nickname": "测试账号一",
                    "alternate_login_name": "UTEST0001A",
                    "game_feature_code": "FEATURE-A1",
                    "account_aliases": [],
                    "task_config": {
                        **copy.deepcopy(_BOOTSTRAP_TASK_DEFAULTS),
                        "备用识别名称": "使用",
                        "备用识别名称内容": "UTEST0001A",
                    },
                    "schedule": {},
                    "extensions": {},
                }
            },
            "sequences": {"主序列": [self.a]},
            "extensions": {},
        }

        def load_index():
            raw = copy.deepcopy(repo.raw)
            return raw, copy.deepcopy(raw["profiles"]), copy.deepcopy(raw["sequences"])

        repo._load_index = load_index
        repo._publish_master = lambda candidate: setattr(repo, "raw", copy.deepcopy(candidate))
        return repo

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

    def test_runtime_reads_verified_active_snapshot_before_mutable_master(self):
        service = AccountPublishService(self.root)
        service.publish(
            expected_revision="",
            profiles={self.a: {"profile_id": self.a, "short_name": "A1", "task_config": {}}},
            index={"config_id": "published", "timezone": "Asia/Shanghai"},
            sequences={"主序列": [self.a]},
        )
        mutable = json.loads(self.repo.index_path.read_text(encoding="utf-8"))
        mutable["accounts"][self.a]["short_name"] = "不应被运行时读取"
        self.repo.index_path.write_text(json.dumps(mutable, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.repo.load_profile(self.a).account["short_name"], "A1")

    def test_invalid_active_snapshot_is_a_hard_error(self):
        service = AccountPublishService(self.root)
        service.active_path.parent.mkdir(parents=True, exist_ok=True)
        service.active_path.write_text('{"revision":"missing"}', encoding="utf-8")
        with self.assertRaisesRegex(AccountRepositoryError, "已发布账号快照无效"):
            self.repo.list_profile_ids()

    def test_template_and_new_profile_publish_through_one_account_graph(self):
        repo = self._memory_repo()

        template = repo.load_profile_template(self.a)
        self.assertEqual(template.tasks["备用识别名称"], "无")
        self.assertEqual(template.tasks["备用识别名称内容"], "")
        template = repo.publish_profile_template(
            {"Which to Farm": "Forgery Challenge"}, expected_revision=template.revision)
        created = repo.create_profile(
            {"display_name": "A5", "phone": "19910000005", "masked_phone": "199****0005"},
            {**template.tasks, "备用识别名称": "无", "备用识别名称内容": ""},
            sequence_ids=("主序列",), expected_revision=template.revision,
        )

        self.assertEqual(created.account["display_name"], "A5")
        self.assertEqual(created.tasks["Which to Farm"], "Forgery Challenge")
        self.assertEqual(repo.raw["sequences"]["主序列"][-1], created.profile_id)

    def test_new_profile_always_owns_its_generated_uuid(self):
        repo = self._memory_repo()
        injected_id = str(uuid.uuid4())
        template = repo.load_profile_template(self.a)

        created = repo.create_profile(
            {"profile_id": injected_id, "display_name": "A5", "phone": "19910000005",
             "masked_phone": "199****0005", "nickname": "测试账号五",
             "alternate_login_name": "", "game_feature_code": "", "account_aliases": []},
            template.tasks, expected_revision=template.revision,
        )

        self.assertNotEqual(created.profile_id, injected_id)
        self.assertEqual(repo.raw["profiles"][created.profile_id]["profile_id"], created.profile_id)

    def test_template_publish_rejects_stale_revision(self):
        repo = self._memory_repo()
        template = repo.load_profile_template(self.a)
        repo.raw["extensions"]["external_change"] = True

        with self.assertRaisesRegex(ProfileRevisionConflict, "模板"):
            repo.publish_profile_template(template.tasks, expected_revision=template.revision)

    def test_duplicate_identity_failure_leaves_no_profile_or_sequence_reference(self):
        for field, value in (("phone", "19910000001"),
                             ("alternate_login_name", "UTEST0001A")):
            with self.subTest(field=field):
                repo = self._memory_repo()
                before = copy.deepcopy(repo.raw)

                def reject_invalid(candidate):
                    errors = validate_master(candidate)
                    if errors:
                        raise AccountRepositoryError("；".join(errors))
                    repo.raw = copy.deepcopy(candidate)

                repo._publish_master = reject_invalid
                template = repo.load_profile_template(self.a)
                account = {
                    "display_name": "A5", "phone": "19910000005",
                    "masked_phone": "199****0005", "nickname": "测试账号五",
                    "alternate_login_name": "UTEST0005A", "game_feature_code": "FEATURE-A5",
                    "account_aliases": [],
                }
                account[field] = value
                tasks = copy.deepcopy(template.tasks)
                if field == "alternate_login_name":
                    tasks.update({"备用识别名称": "使用", "备用识别名称内容": value})

                with self.assertRaisesRegex(AccountRepositoryError, "ambiguous"):
                    repo.create_profile(
                        account, tasks, sequence_ids=("主序列",),
                        expected_revision=template.revision,
                    )

                self.assertEqual(repo.raw, before)


if __name__ == "__main__":
    unittest.main()
