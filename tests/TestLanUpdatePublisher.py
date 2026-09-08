import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.publish_lan_update import PublishError, publish


class TestLanUpdatePublisher(unittest.TestCase):
    @patch("scripts.publish_lan_update.verify_update")
    def test_publishes_version_before_latest_and_is_idempotent(self, verify):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "okww_update_v1.40.03.zip"
            archive.write_bytes(b"package")
            digest = hashlib.sha256(b"package").hexdigest()
            verify.return_value = {"version": "1.40.03", "sha256": digest}
            destination = root / "nas"
            when = datetime(2026, 9, 8, 10, tzinfo=timezone.utc)
            latest = publish(archive, destination, previous_ref="v1.40.02", published_at=when)
            self.assertTrue(destination.joinpath("stable/releases/v1.40.03", archive.name).is_file())
            self.assertEqual("1.40.03", json.loads(latest.read_text())["version"])
            self.assertEqual(latest, publish(archive, destination, previous_ref="v1.40.02", published_at=when))

    @patch("scripts.publish_lan_update.verify_update")
    def test_refuses_conflicting_version(self, verify):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "okww_update_v1.40.03.zip"
            archive.write_bytes(b"new")
            digest = hashlib.sha256(b"new").hexdigest()
            verify.return_value = {"version": "1.40.03", "sha256": digest}
            existing = root / "nas/stable/releases/v1.40.03/okww_update_v1.40.03.zip"
            existing.parent.mkdir(parents=True)
            existing.write_bytes(b"old")
            with self.assertRaises(PublishError):
                publish(archive, root / "nas", previous_ref="v1.40.02")


if __name__ == "__main__":
    unittest.main()
