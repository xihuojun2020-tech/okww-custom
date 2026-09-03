import copy
import unittest
from types import SimpleNamespace

from src.account_config_editor import (AccountConfigEditor, AccountLabelMismatch,
                                       LockedProfileField, sanitize_error)
from src.account_repository import ProfileRevisionConflict


class FakeRepository:
    def __init__(self):
        self.record = SimpleNamespace(profile_id="id", revision="r1",
                                      account={"display_name": "A3", "account_aliases": ["secret"]},
                                      tasks={"Which to Farm": "before", "备用识别名称内容": "hidden"})
        self.backups = []
        self.published_sequence_ids = None
        self.template = SimpleNamespace(revision="r1", tasks={
            "Which to Farm": "before", "备用识别名称": "无", "备用识别名称内容": "",
        })
        self.created = None

    def load_profile(self, _profile_id):
        return copy.deepcopy(self.record)

    def backup_profile(self, profile_id, payload):
        self.backups.append((profile_id, payload))

    def publish_profile(self, scope, payload, **_kwargs):
        if scope.base_revision != self.record.revision:
            raise ProfileRevisionConflict()
        self.record.account, self.record.tasks, self.record.revision = payload["account"], payload["tasks"], "r2"
        self.published_sequence_ids = payload.get("sequence_ids")
        return self.load_profile(scope.profile_id)

    def load_profile_template(self, _fallback=None):
        return copy.deepcopy(self.template)

    def publish_profile_template(self, tasks, *, expected_revision):
        if expected_revision != self.template.revision:
            raise ProfileRevisionConflict()
        self.template = SimpleNamespace(revision="r2", tasks=copy.deepcopy(tasks))
        return copy.deepcopy(self.template)

    def create_profile(self, account, tasks, **kwargs):
        self.created = (copy.deepcopy(account), copy.deepcopy(tasks), kwargs)
        return SimpleNamespace(profile_id="new-id", revision="r2", account=account, tasks=tasks)


class TestAccountConfigEditor(unittest.TestCase):
    def test_gui_error_text_is_redacted(self):
        text = sanitize_error(RuntimeError(
            "phone 19910000004 token abcdefghijklmnopqrstuvwxyz123456"))
        self.assertNotIn("19910000004", text)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz123456", text)

    def setUp(self):
        self.repository = FakeRepository()
        self.editor = AccountConfigEditor(self.repository)

    def test_draft_is_detached_diff_is_redacted_and_save_backs_up(self):
        draft = self.editor.load_draft("id")
        draft.tasks["Which to Farm"] = "19910000005"
        self.assertEqual(self.repository.record.tasks["Which to Farm"], "before")
        diff = self.editor.preview_diff(draft)
        self.assertEqual(diff.changes[0].after, "199****0005")
        saved = self.editor.save_draft(draft.scope, draft, confirmed_account_label="A3")
        self.assertEqual(saved.tasks["Which to Farm"], "19910000005")
        self.assertEqual(len(self.repository.backups), 1)

    def test_locked_identity_label_and_stale_revision_are_rejected(self):
        draft = self.editor.load_draft("id")
        draft.account["account_aliases"] = ["changed"]
        with self.assertRaises(LockedProfileField):
            self.editor.save_draft(draft.scope, draft, confirmed_account_label="A3")
        draft = self.editor.load_draft("id")
        with self.assertRaises(AccountLabelMismatch):
            self.editor.save_draft(draft.scope, draft, confirmed_account_label="A4")
        draft = self.editor.load_draft("id")
        self.repository.record.revision = "r2"
        with self.assertRaises(ProfileRevisionConflict):
            self.editor.save_draft(draft.scope, draft, confirmed_account_label="A3")

    def test_save_passes_sequence_membership_without_changing_identity(self):
        draft = self.editor.load_draft("id")
        self.editor.save_draft(draft.scope, draft, confirmed_account_label="A3",
                               sequence_ids=("序列2",))
        self.assertEqual(self.repository.published_sequence_ids, ("序列2",))

    def test_alias_choice_updates_the_canonical_identity_and_preserves_disabled_text(self):
        self.repository.record.tasks.update({"备用识别名称": "无", "备用识别名称内容": "OLD"})
        self.repository.record.account["alternate_login_name"] = ""
        draft = self.editor.load_draft("id")
        draft.tasks["备用识别名称"] = "使用"
        draft.tasks["备用识别名称内容"] = "UTEST0091A"
        saved = self.editor.save_draft(draft.scope, draft, confirmed_account_label="A3")
        self.assertEqual(saved.account["alternate_login_name"], "UTEST0091A")

        draft = self.editor.load_draft("id")
        draft.tasks["备用识别名称"] = "无"
        saved = self.editor.save_draft(draft.scope, draft, confirmed_account_label="A3")
        self.assertEqual(saved.account["alternate_login_name"], "")
        self.assertEqual(saved.tasks["备用识别名称内容"], "UTEST0091A")

    def test_new_account_copies_template_but_never_its_identity(self):
        template = self.editor.load_template("id")
        created = self.editor.create_profile(
            template,
            display_name="a5",
            phone="19910000005",
            nickname="新账号",
            game_feature_code="FEATURE-A5",
            alias_enabled=True,
            alias_text="UTEST0005A",
            sequence_ids=("序列1",),
        )
        account, tasks, kwargs = self.repository.created
        self.assertEqual(created.profile_id, "new-id")
        self.assertEqual(account["display_name"], "A5")
        self.assertEqual(account["masked_phone"], "199****0005")
        self.assertEqual(tasks["Which to Farm"], "before")
        self.assertEqual(tasks["备用识别名称"], "使用")
        self.assertEqual(kwargs["sequence_ids"], ("序列1",))
        self.assertEqual(kwargs["expected_revision"], "r1")


if __name__ == "__main__":
    unittest.main()
