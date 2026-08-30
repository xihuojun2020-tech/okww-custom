import re
import subprocess
import unittest
from pathlib import Path


TEXT_SUFFIXES = {
    ".ini", ".java", ".json", ".md", ".po", ".ps1", ".py",
    ".txt", ".toml", ".xml", ".yaml", ".yml",
}
PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
MASKED_PHONE = re.compile(r"(?<!\d)1[3-9]\d\*{4}\d{4}(?!\d)")
ALT_LOGIN = re.compile(
    r"(?<![A-Za-z0-9])U(?=[A-Za-z0-9]{5,30}(?![A-Za-z0-9]))"
    r"(?=[A-Za-z0-9]*\d)[A-Za-z0-9]+"
)
PROTECTED_UNTRACKED_PREFIXES = (
    "android/agent-app/",
    "docs/superpowers/plans/2026-08-26-android-agent-shell-phase01.md",
    "docs/superpowers/plans/2026-08-27-android-agent-phase02.md",
    "docs/superpowers/plans/2026-08-27-android-agent-phase03.md",
    "docs/superpowers/specs/2026-08-26-android-agent-complete-production-plan.md",
)


class TestSensitiveIdentifierScan(unittest.TestCase):
    def test_repository_uses_only_synthetic_account_identifiers(self):
        files = subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            text=True,
            encoding="utf-8",
        ).splitlines()
        violations = []
        for filename in files:
            normalized = filename.replace("\\", "/")
            if normalized.startswith(PROTECTED_UNTRACKED_PREFIXES):
                continue
            path = Path(filename)
            if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(not value.startswith("1991") for value in PHONE.findall(text)):
                violations.append(f"{filename}:phone")
            if any(not value.startswith("199****") for value in MASKED_PHONE.findall(text)):
                violations.append(f"{filename}:masked_phone")
            if any(not value.startswith("UTEST") for value in ALT_LOGIN.findall(text)):
                violations.append(f"{filename}:alternate_login")
        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
