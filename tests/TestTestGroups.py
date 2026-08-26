import unittest
from pathlib import Path


class TestTestGroups(unittest.TestCase):
    def test_runner_declares_named_test_groups(self):
        runner = Path(__file__).resolve().parents[1] / "run_tests.ps1"
        text = runner.read_text(encoding="utf-8")
        for group in ("unit", "integration", "ui", "image", "fault_injection"):
            self.assertIn(group, text)


if __name__ == "__main__":
    unittest.main()
