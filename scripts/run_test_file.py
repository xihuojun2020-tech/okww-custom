"""Run one unittest file with redaction installed before project imports."""

from __future__ import annotations

import builtins
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.observability import install_redaction_filters, redact_message


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: run_test_file.py TEST_FILE")
    test_file = sys.argv[1]
    original_print = builtins.print

    def safe_print(*values, **kwargs):
        original_print(*(redact_message(value) for value in values), **kwargs)

    install_redaction_filters()
    builtins.print = safe_print
    sys.argv[0] = str(ROOT / "python.exe -m unittest")
    unittest.main(module=None, argv=[sys.argv[0], test_file])


if __name__ == "__main__":
    main()
