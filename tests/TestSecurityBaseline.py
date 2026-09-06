import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestSecurityBaseline(unittest.TestCase):
    def test_runtime_data_directories_are_ignored(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for entry in ("config_bundle_transactions/", "config_integrity_incidents/", "账号备份/"):
            self.assertIn(entry, ignored)

    def test_release_metadata_uses_same_version(self):
        config = (ROOT / "config.py").read_text(encoding="utf-8")
        version = re.search(r'version\s*=\s*"([0-9]+\.[0-9]{2}\.[0-9]{2})"', config).group(1)
        self.assertIn(version, (ROOT / "更新日志.md").read_text(encoding="utf-8"))
        from scripts.validate_release import validate_release
        self.assertEqual(version, validate_release(ROOT))


if __name__ == "__main__":
    unittest.main()
