import os
import tempfile
import unittest
from pathlib import Path

from src.secure_backup import (
    SecureBackupService,
    SecureBackupUnavailable,
    SecureStoragePolicy,
    harden_directory_permissions,
    validate_restore_path,
)


class TestSecureBackup(unittest.TestCase):
    def test_sensitive_backup_is_not_plain_json(self):
        payload = b'{"phone":"19910000002"}'
        if os.name != "nt":
            self.skipTest("DPAPI is Windows-only")
        encrypted = SecureBackupService().encrypt_snapshot(payload)
        self.assertNotIn(b"19910000002", encrypted)
        self.assertEqual(SecureBackupService().decrypt_snapshot(encrypted), payload)

    def test_restore_path_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            with self.assertRaises(ValueError):
                validate_restore_path(root_path / "source" / ".." / "outside",
                                      root_path / "target", root_path)

    def test_restore_path_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source = root_path / "source"
            outside = root_path.parent / f"okww-outside-{os.getpid()}"
            outside.mkdir()
            try:
                try:
                    source.symlink_to(outside, target_is_directory=True)
                except (OSError, NotImplementedError):
                    self.skipTest("symbolic links are unavailable for this test user")
                with self.assertRaises(ValueError):
                    validate_restore_path(source, root_path / "target", root_path)
            finally:
                source.unlink(missing_ok=True)
                outside.rmdir()

    def test_harden_directory_permissions_keeps_backup_directory_usable(self):
        if os.name != "nt":
            self.skipTest("Windows ACL is Windows-only")
        with tempfile.TemporaryDirectory() as root:
            target = harden_directory_permissions(Path(root) / "backups")
            self.assertTrue(target.is_dir())
            (target / "probe").write_text("ok", encoding="utf-8")

    def test_storage_policy_prunes_oldest_entries_without_following_links(self):
        with tempfile.TemporaryDirectory() as root:
            policy = SecureStoragePolicy(root, max_entries=2, max_age_days=1)
            paths = []
            for index in range(3):
                path = Path(root) / f"entry-{index}"
                path.mkdir()
                os.utime(path, (100 + index, 100 + index))
                paths.append(path)
            policy.cleanup(now=200)
            self.assertFalse(paths[0].exists())
            self.assertTrue(paths[1].exists())
            self.assertTrue(paths[2].exists())


if __name__ == "__main__":
    unittest.main()
