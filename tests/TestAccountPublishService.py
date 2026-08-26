import tempfile
import unittest
import uuid
from pathlib import Path

from src.account_publish_service import AccountPublishService
from src.account_repository import ProfileRevisionConflict


class TestAccountPublishService(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.a1 = str(uuid.uuid4())
        self.profiles = {self.a1: {"profile_id": self.a1, "display_name": "A1",
                                   "task_config": {}}}
        self.index = {"config_id": "test", "timezone": "Asia/Shanghai",
                      "profile_ids": [self.a1]}
        self.sequences = {"序列一": [self.a1]}

    def tearDown(self):
        self.temp.cleanup()

    def test_publish_and_load_active_validate_manifest(self):
        service = AccountPublishService(self.root, program_version="test")
        revision = service.publish(expected_revision="", profiles=self.profiles,
                                   index=self.index, sequences=self.sequences)
        loaded = service.load_active()
        self.assertEqual(revision.revision, loaded.revision)
        self.assertIn("account_master_config.json", loaded.manifest["files"])
        self.assertTrue((loaded.bundle_dir / "profiles" / f"{self.a1}.json").is_file())
        self.assertTrue((self.root / "configs" / "accounts" / "profiles" / f"{self.a1}.json").is_file())

    def test_interrupted_publish_keeps_previous_active_bundle(self):
        service = AccountPublishService(self.root)
        old = service.publish(expected_revision="", profiles=self.profiles,
                              index=self.index, sequences=self.sequences)
        failing = AccountPublishService(self.root, fail_after_bundle_write=True)
        with self.assertRaises(RuntimeError):
            failing.publish(expected_revision=old.revision,
                            profiles={self.a1: {"profile_id": self.a1, "display_name": "changed"}},
                            index=self.index, sequences=self.sequences)
        self.assertEqual(old.revision, service.load_active().revision)

    def test_stale_publish_is_rejected(self):
        service = AccountPublishService(self.root)
        old = service.publish(expected_revision="", profiles=self.profiles,
                              index=self.index, sequences=self.sequences)
        service.publish(expected_revision=old.revision,
                        profiles={self.a1: {"profile_id": self.a1, "display_name": "changed"}},
                        index=self.index, sequences=self.sequences)
        with self.assertRaises(ProfileRevisionConflict):
            service.publish(expected_revision=old.revision, profiles=self.profiles,
                            index=self.index, sequences=self.sequences)


if __name__ == "__main__":
    unittest.main()
