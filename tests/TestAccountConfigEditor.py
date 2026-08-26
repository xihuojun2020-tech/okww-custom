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


class TestAccountConfigEditor(unittest.TestCase):
    def test_gui_error_text_is_redacted(self):
        text = sanitize_error(RuntimeError(
            "phone 13812345678 token abcdefghijklmnopqrstuvwxyz123456"))
        self.assertNotIn("13812345678", text)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz123456", text)

    def setUp(self):
        self.repository = FakeRepository()
        self.editor = AccountConfigEditor(self.repository)

    def test_draft_is_detached_diff_is_redacted_and_save_backs_up(self):
        draft = self.editor.load_draft("id")
        draft.tasks["Which to Farm"] = "15300000001"
        self.assertEqual(self.repository.record.tasks["Which to Farm"], "before")
        diff = self.editor.preview_diff(draft)
        self.assertEqual(diff.changes[0].after, "153****0001")
        saved = self.editor.save_draft(draft.scope, draft, confirmed_account_label="A3")
        self.assertEqual(saved.tasks["Which to Farm"], "15300000001")
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


if __name__ == "__main__":
    unittest.main()
