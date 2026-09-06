import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from src.account_graph_store import AccountGraphStore
from src.account_publish_service import AccountPublishService, PublishState


class TestAccountGraphStore(unittest.TestCase):
    def test_runtime_reads_only_active_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile_id = str(uuid.uuid4())
            service = AccountPublishService(root)
            service.publish(expected_revision="", profiles={profile_id: {
                "profile_id": profile_id, "display_name": "A1", "task_config": {}}},
                            index={"config_id": "test"}, sequences={"主序列": [profile_id]})
            (root / "configs" / "account_master_config.json").write_text("stale", encoding="utf-8")
            graph = AccountGraphStore(root).load_active()
            self.assertEqual(graph.profiles[profile_id]["display_name"], "A1")

    def test_publish_requires_complete_candidate_and_cas(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile_id = str(uuid.uuid4())
            store = AccountGraphStore(root)
            first = store.publish({"profiles": {profile_id: {"profile_id": profile_id,
                                                               "display_name": "A1",
                                                               "task_config": {}}},
                                   "index": {"config_id": "test"},
                                   "sequences": {"主序列": [profile_id]}})
            self.assertEqual(store.state, PublishState.MIRRORED)
            with self.assertRaises(Exception):
                store.publish({"profiles": {}, "index": {"config_id": "test"}, "sequences": {}},
                              expected_revision="stale")
            self.assertEqual(store.load_active().revision, first.revision)

    def test_interrupted_mirror_keeps_new_active_revision_readable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile_id = str(uuid.uuid4())
            store = AccountGraphStore(root)
            first = store.publish({"profiles": {profile_id: {"profile_id": profile_id,
                                                               "display_name": "A1",
                                                               "task_config": {}}},
                                   "index": {"config_id": "test"},
                                   "sequences": {"主序列": [profile_id]}})
            candidate = {"profiles": {profile_id: {"profile_id": profile_id,
                                                    "display_name": "changed",
                                                    "task_config": {}}},
                         "index": {"config_id": "test"},
                         "sequences": {"主序列": [profile_id]}}
            with patch.object(store.service, "_mirror_projections", side_effect=OSError("interrupt")):
                result = store.publish(candidate, expected_revision=first.revision)
            self.assertTrue(result.maintenance_errors)
            active = store.load_active()
            self.assertNotEqual(active.revision, first.revision)
            self.assertEqual(active.profiles[profile_id]["display_name"], "changed")


if __name__ == "__main__":
    unittest.main()
