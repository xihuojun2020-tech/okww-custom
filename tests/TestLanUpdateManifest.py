import json
import unittest

from src.update.lan_manifest import LanManifestError, LanRelease, parse_version


def manifest(**changes):
    value = {"schema_version": 1, "channel": "stable", "version": "1.40.03",
             "package": "releases/v1.40.03/okww_update_v1.40.03.zip", "sha256": "a" * 64,
             "size": 12, "published_at": "2026-09-08T10:00:00Z"}
    value.update(changes)
    return json.dumps(value).encode()


class TestLanUpdateManifest(unittest.TestCase):
    def test_valid_release_and_numeric_order(self):
        release = LanRelease.from_bytes(manifest())
        self.assertTrue(release.is_newer_than("1.39.12"))
        self.assertEqual((1, 40, 3), parse_version(release.version))

    def test_rejects_bad_values(self):
        bad = [
            {"schema_version": True}, {"channel": "beta"}, {"version": "1.4.03"},
            {"sha256": "A" * 64}, {"size": 0}, {"size": 536870913},
            {"published_at": "2026-09-08T10:00:00+00:00"},
            {"package": "releases/v1.40.03/../evil.zip"},
            {"package": "/releases/v1.40.03/okww_update_v1.40.03.zip"},
            {"package": "releases\\v1.40.03\\okww_update_v1.40.03.zip"},
        ]
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises(LanManifestError):
                LanRelease.from_bytes(manifest(**changes))

    def test_rejects_unknown_key_and_invalid_json(self):
        record = json.loads(manifest())
        record["extra"] = 1
        with self.assertRaises(LanManifestError):
            LanRelease.from_bytes(json.dumps(record).encode())
        with self.assertRaises(LanManifestError):
            LanRelease.from_bytes(b"{")


if __name__ == "__main__":
    unittest.main()
