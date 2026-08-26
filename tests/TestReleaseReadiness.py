import re
import unittest
from pathlib import Path


class TestReleaseReadiness(unittest.TestCase):
    def test_version_and_release_notes_are_synchronized(self):
        version = re.search(r'version\s*=\s*"([0-9]+\.[0-9]{2}\.[0-9]{2})"',
                            Path("config.py").read_text(encoding="utf-8")).group(1)
        self.assertEqual(version, "1.19.01")
        self.assertIn(version, Path("更新日志.md").read_text(encoding="utf-8"))
        self.assertIn(f"V{version}", Path("custom_ok/ok/gui/about/AboutTab.py").read_text(encoding="utf-8"))

    def test_sensitive_runtime_boundaries_are_ignored(self):
        ignored = Path(".gitignore").read_text(encoding="utf-8")
        for entry in ("账号备份/", "config_bundle_transactions/", "config_integrity_incidents/"):
            self.assertIn(entry, ignored)

    def test_required_runtime_interfaces_exist(self):
        from src.account_graph_store import AccountGraphStore
        from src.observability import CorrelationContext, redact_message
        from src.runtime import AccountSelectionService, SequenceSnapshotService, TaskRunCoordinator
        self.assertTrue(all((AccountGraphStore, CorrelationContext, redact_message,
                             AccountSelectionService, SequenceSnapshotService, TaskRunCoordinator)))


if __name__ == "__main__":
    unittest.main()
