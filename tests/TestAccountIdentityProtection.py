import copy
import unittest
from types import SimpleNamespace

from src.account_config_editor import AccountConfigEditor, LockedProfileField
from src.account_rebind_service import AccountRebindService
from src.account_identity import AccountIdentityError


class FakeRepository:
    def __init__(self):
        self.records = {
            "a1": {"profile_id": "a1", "display_name": "A1", "masked_phone": "199****0004",
                   "nickname": "夜归", "alternate_login_name": "UTEST0003A", "game_feature_code": "F1",
                   "account_aliases": [], "task_config": {"Which to Farm": "Tacet Suppression"}},
            "a3": {"profile_id": "a3", "display_name": "A3", "masked_phone": "199****0008",
                   "nickname": "昼行", "alternate_login_name": "UTEST0004A", "game_feature_code": "F3",
                   "account_aliases": [], "task_config": {"Which to Farm": "Tacet Suppression"}},
        }
        self.revision = "r1"
        self.backups = []

    def load_profile(self, profile_id):
        value = copy.deepcopy(self.records[profile_id])
        tasks = value.pop("task_config")
        return SimpleNamespace(profile_id=profile_id, revision=self.revision, account=value, tasks=tasks)

    def list_profiles(self):
        return tuple(self.load_profile(profile_id) for profile_id in self.records)

    def backup_profile(self, profile_id, payload):
        self.backups.append((profile_id, payload))

    def publish_profile(self, scope, payload, **_kwargs):
        if scope.base_revision != self.revision:
            raise RuntimeError("stale revision")
        account = copy.deepcopy(payload["account"])
        tasks = copy.deepcopy(payload["tasks"])
        account["task_config"] = tasks
        self.records[scope.profile_id] = account
        self.revision = "r2"
        return self.load_profile(scope.profile_id)


class TestAccountIdentityProtection(unittest.TestCase):
    def setUp(self):
        self.repository = FakeRepository()
        self.editor = AccountConfigEditor(self.repository)

    def test_all_identity_fields_are_rejected_by_normal_editor(self):
        for key, value in {
            "phone": "19910000007",
            "masked_phone": "199****0009",
            "nickname": "changed",
            "alternate_login_name": "UTEST0005A",
            "game_feature_code": "Fchanged",
            "account_aliases": ["changed"],
        }.items():
            draft = self.editor.load_draft("a1")
            draft.account[key] = value
            with self.subTest(key=key), self.assertRaises(LockedProfileField):
                self.editor.save_draft(draft.scope, draft, confirmed_account_label="A1")

    def test_rebind_rejects_identity_collision(self):
        service = AccountRebindService(self.repository)
        with self.assertRaises(AccountIdentityError):
            service.preview("a1", {"masked_phone": "199****0008"})

    def test_rebind_creates_backup_and_publishes_after_confirmation(self):
        service = AccountRebindService(self.repository)
        result = service.rebind(
            "a1", current_identity="199****0004",
            new_identity={"masked_phone": "199****0010", "alternate_login_name": "UTEST0006A"},
            confirmed=True,
        )
        self.assertEqual(result.account["masked_phone"], "199****0010")
        self.assertEqual(len(self.repository.backups), 1)


if __name__ == "__main__":
    unittest.main()
