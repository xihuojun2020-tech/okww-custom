import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

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

    def test_republishing_same_revision_reuses_verified_bundle(self):
        service = AccountPublishService(self.root)
        first = service.publish(expected_revision="", profiles=self.profiles,
                                index=self.index, sequences=self.sequences)
        marker = first.bundle_dir / "reuse-marker"
        marker.write_text("keep", encoding="utf-8")

        second = service.publish(expected_revision=first.revision, profiles=self.profiles,
                                 index=self.index, sequences=self.sequences)

        self.assertEqual(first.revision, second.revision)
        self.assertTrue(marker.is_file())
        self.assertEqual(first.revision, service.load_active().revision)

    def test_active_pointer_failure_keeps_previous_revision_readable(self):
        service = AccountPublishService(self.root)
        old = service.publish(expected_revision="", profiles=self.profiles,
                              index=self.index, sequences=self.sequences)
        changed = {self.a1: {"profile_id": self.a1, "display_name": "changed"}}

        with patch.object(service, "_write_active_pointer",
                          side_effect=OSError("forced pointer failure")):
            with self.assertRaises(OSError):
                service.publish(expected_revision=old.revision, profiles=changed,
                                index=self.index, sequences=self.sequences)

        self.assertEqual(old.revision, service.load_active().revision)
        self.assertTrue(old.bundle_dir.is_dir())

    def test_mirror_failure_keeps_new_active_bundle_readable(self):
        service = AccountPublishService(self.root)
        old = service.publish(expected_revision="", profiles=self.profiles,
                              index=self.index, sequences=self.sequences)
        changed = {self.a1: {"profile_id": self.a1, "display_name": "changed"}}

        with patch.object(service, "_mirror_projections",
                          side_effect=OSError("forced mirror failure")):
            with self.assertRaises(OSError):
                service.publish(expected_revision=old.revision, profiles=changed,
                                index=self.index, sequences=self.sequences)

        self.assertNotEqual(old.revision, service.load_active().revision)
        self.assertTrue(old.bundle_dir.is_dir())

    def test_corrupt_active_same_revision_is_never_deleted(self):
        service = AccountPublishService(self.root)
        active = service.publish(expected_revision="", profiles=self.profiles,
                                 index=self.index, sequences=self.sequences)
        damaged = active.bundle_dir / "profiles" / f"{self.a1}.json"
        damaged.write_text("{}", encoding="utf-8")

        with self.assertRaises(ValueError):
            service.publish(expected_revision=active.revision, profiles=self.profiles,
                            index=self.index, sequences=self.sequences)

        self.assertTrue(active.bundle_dir.is_dir())
        self.assertEqual("{}", damaged.read_text(encoding="utf-8"))

    def test_corrupt_inactive_same_revision_is_quarantined_and_rebuilt(self):
        service = AccountPublishService(self.root)
        original = service.publish(expected_revision="", profiles=self.profiles,
                                   index=self.index, sequences=self.sequences)
        changed = {self.a1: {"profile_id": self.a1, "display_name": "changed"}}
        current = service.publish(expected_revision=original.revision, profiles=changed,
                                  index=self.index, sequences=self.sequences)
        (original.bundle_dir / "profiles" / f"{self.a1}.json").write_text(
            "{}", encoding="utf-8")

        rebuilt = service.publish(expected_revision=current.revision, profiles=self.profiles,
                                  index=self.index, sequences=self.sequences)

        self.assertEqual(original.revision, rebuilt.revision)
        self.assertEqual(original.revision, service.load_active().revision)

    def test_publication_retains_two_latest_valid_bundles(self):
        service = AccountPublishService(self.root)
        revision = service.publish(expected_revision="", profiles=self.profiles,
                                   index=self.index, sequences=self.sequences)
        for display in ("changed-1", "changed-2"):
            revision = service.publish(
                expected_revision=revision.revision,
                profiles={self.a1: {"profile_id": self.a1, "display_name": display}},
                index=self.index,
                sequences=self.sequences,
            )

        bundles = [path for path in service.bundles_dir.iterdir()
                   if path.is_dir() and not path.name.startswith(".")]
        self.assertEqual(2, len(bundles))
        self.assertTrue((service.bundles_dir / revision.revision).is_dir())


if __name__ == "__main__":
    unittest.main()
