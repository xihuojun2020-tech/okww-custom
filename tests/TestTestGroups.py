import unittest
from pathlib import Path
import re


class TestTestGroups(unittest.TestCase):
    def test_runner_declares_named_test_groups(self):
        runner = Path(__file__).resolve().parents[1] / "run_tests.ps1"
        text = runner.read_text(encoding="utf-8")
        for group in ("unit", "integration", "ui", "image", "fault_injection"):
            self.assertIn(group, text)

    def test_all_is_the_deduplicated_union_and_excludes_support_modules(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "run_tests.ps1").read_text(encoding="utf-8")
        self.assertNotIn("Get-ChildItem", text)
        self.assertIn("HashSet[string]", text)
        self.assertIn("scripts\\run_test_file.py", text)
        self.assertNotIn('"fixture_support.py"', text)

        configured = set(re.findall(r'"((?:Test|test_)[^"\\/]+\.py)"', text))
        expected = {
            path.name for path in (root / "tests").glob("*.py")
            if path.name.startswith("Test") or path.name.startswith("test_")
        }
        self.assertEqual(expected, configured)

    def test_workflows_delegate_discovery_to_the_runner(self):
        root = Path(__file__).resolve().parents[1]
        for relative in (".github/workflows/test.yml", ".github/workflows/build.yml"):
            text = (root / relative).read_text(encoding="utf-8")
            self.assertIn("run_tests.ps1", text)
            self.assertNotIn("tests\\*.py", text)


if __name__ == "__main__":
    unittest.main()
