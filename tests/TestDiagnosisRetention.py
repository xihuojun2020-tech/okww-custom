import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.diagnose import _identifier_summary, save_diagnosis


class TestDiagnosisRetention(unittest.TestCase):
    def test_device_identifier_is_only_exposed_as_stable_digest(self):
        raw = "device-identifier-for-test"
        summary = _identifier_summary(raw)
        self.assertNotIn(raw, summary)
        self.assertEqual(summary, _identifier_summary(raw))

    def test_normal_main_start_has_no_automatic_diagnosis_call(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertNotIn("from src.diagnose import save_diagnosis", source)

    def test_save_diagnosis_retains_only_ten_recent_files(self):
        with tempfile.TemporaryDirectory() as temp:
            log_dir = Path(temp) / "logs" / "实验性日志"
            log_dir.mkdir(parents=True)
            now = datetime(2026, 8, 30, 22, 30, 0)
            timestamp = now.timestamp()
            for index in range(11):
                path = log_dir / f"诊断_old_{index:02d}.log"
                path.write_text("old", encoding="utf-8")
                os.utime(path, (timestamp - 100 + index, timestamp - 100 + index))
            with patch("src.diagnose.collect_diagnosis", return_value="safe"):
                created = Path(save_diagnosis(temp, now=now))
            self.assertTrue(created.is_file())
            self.assertEqual(10, len(list(log_dir.glob("*.log"))))


if __name__ == "__main__":
    unittest.main()
