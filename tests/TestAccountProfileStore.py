import json
import tempfile
import unittest
import uuid
from pathlib import Path

from src.account_profile_store import AccountProfileStore
from src.account_repository import AccountRepositoryError, ProfileRevisionConflict


class TestAccountProfileStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.a1 = str(uuid.uuid4())
        self.a3 = str(uuid.uuid4())
        self.store = AccountProfileStore(self.root)
        self.store.write_index({"schema_version": 1, "profile_ids": [self.a1, self.a3],
                                "sequences": {"序列一": [self.a1, self.a3]}})
        self.store.write_profile(self.a1, {"display_name": "A1"})
        self.store.write_profile(self.a3, {"display_name": "A3"})

    def tearDown(self):
        self.temp.cleanup()

    def test_editing_a1_does_not_change_a3(self):
        before = self.store.load_profile(self.a3).payload
        revision = self.store.load_profile(self.a1).revision
        self.store.write_profile(self.a1, {"display_name": "A1-new"}, revision)
        self.assertEqual(before, self.store.load_profile(self.a3).payload)

    def test_stale_profile_edit_is_rejected(self):
        revision = self.store.load_profile(self.a1).revision
        self.store.write_profile(self.a1, {"display_name": "first"}, revision)
        with self.assertRaises(ProfileRevisionConflict):
            self.store.write_profile(self.a1, {"display_name": "stale"}, revision)

    def test_profile_id_is_bound_to_filename(self):
        with self.assertRaises(AccountRepositoryError):
            self.store.write_profile(self.a1, {"profile_id": self.a3, "display_name": "wrong"})

    def test_writes_are_json_and_index_keeps_uuid_membership(self):
        payload = json.loads((self.root / "configs" / "accounts" / "profiles" / f"{self.a1}.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["profile_id"], self.a1)
        self.assertEqual(self.store.load_index()["sequences"]["序列一"], [self.a1, self.a3])


if __name__ == "__main__":
    unittest.main()
