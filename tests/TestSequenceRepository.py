import copy
import unittest
from types import SimpleNamespace

from src.account_repository import ProfileRevisionConflict
from src.sequence_repository import SequenceDeletionBlocked, SequenceReferenceError, SequenceRepository


class FakeRepository:
    def __init__(self):
        self.revision = 1
        self.profiles = {
            "id-a1": SimpleNamespace(profile_id="id-a1", account={"display_name": "A1", "account_aliases": ["U1"]}, tasks={"x": 1}),
            "id-a3": SimpleNamespace(profile_id="id-a3", account={"display_name": "A3"}, tasks={"x": 3}),
        }
        self.sequences = {"默认": (["id-a1"], {"enabled": True})}

    def list_profiles(self):
        return [copy.deepcopy(value) for value in self.profiles.values()]

    def list_sequence_ids(self):
        return tuple(self.sequences)

    def load_sequence(self, name):
        members, metadata = self.sequences[name]
        return SimpleNamespace(sequence_id=name, revision=str(self.revision), profile_ids=tuple(members), metadata=metadata)

    def publish_sequence(self, name, members, expected_revision=0, metadata=None, **_kwargs):
        if expected_revision not in (0, "0") and str(expected_revision) != str(self.revision):
            raise ProfileRevisionConflict()
        self.revision += 1
        self.sequences[name] = (list(members), dict(metadata or {}))
        return self.load_sequence(name)

    def rename_sequence(self, old, new, expected_revision):
        if str(expected_revision) != str(self.revision):
            raise ProfileRevisionConflict()
        self.revision += 1
        self.sequences[new] = self.sequences.pop(old)
        return self.load_sequence(new)

    def delete_sequence(self, name, expected_revision):
        if str(expected_revision) != str(self.revision):
            raise ProfileRevisionConflict()
        self.revision += 1
        del self.sequences[name]


class TestSequenceRepository(unittest.TestCase):
    def setUp(self):
        self.raw = FakeRepository()
        self.service = SequenceRepository(self.raw)

    def test_crud_copy_enable_reorder_and_validation(self):
        created = self.service.create("轮换", ["A1", "A3"])
        self.assertEqual(created.profile_ids, ("id-a1", "id-a3"))
        copied = self.service.copy("轮换", "副本")
        disabled = self.service.set_enabled("副本", False)
        self.assertFalse(disabled.enabled)
        renamed = self.service.rename("副本", "备用")
        self.assertEqual(renamed.sequence_id, "备用")
        before = self.service.load("轮换")
        after = self.service.publish(before.scope, {"profile_ids": ["id-a3", "id-a1"]})
        self.assertTrue(self.service.diff(before, after).reordered)
        self.service.delete("备用")
        with self.assertRaises(SequenceReferenceError):
            self.service.create("重复", ["A1", "A1"])

    def test_snapshot_is_immutable_and_profile_delete_is_guarded(self):
        snapshot = self.service.create_run_snapshot("默认")
        self.raw.profiles["id-a1"].tasks["x"] = 99
        self.assertEqual(snapshot.profiles[0]["tasks"]["x"], 1)
        with self.assertRaises(TypeError):
            snapshot.profiles[0]["tasks"]["x"] = 2
        with self.assertRaises(SequenceDeletionBlocked):
            self.service.ensure_profile_deletable("id-a1")


if __name__ == "__main__":
    unittest.main()
