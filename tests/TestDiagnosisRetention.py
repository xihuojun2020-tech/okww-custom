import os
import json
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.diagnose import _identifier_summary, save_diagnosis
from src.observability import register_sensitive_values, _reset_sensitive_values_for_tests


class TestDiagnosisRetention(unittest.TestCase):
    def tearDown(self):
        _reset_sensitive_values_for_tests()

    def test_actual_gui_export_redacts_nested_events_and_omits_private_pixels(self):
        import cv2
        import numpy as np
        from custom_ok.ok.gui.start.StartTab import StartTab
        from src.account_switch_evidence import AccountSwitchEvidenceSession
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            identity, nickname, secret = '19910000002', '合成昵称', 'SYNTHETIC PRIVATE SECRET'
            register_sensitive_values([nickname])
            (root / 'logs').mkdir()
            log = root / 'logs' / 'private.log'
            log.write_text(f'phone={identity}, nickname="{nickname}", token="{secret}"', encoding='utf-8')
            image = np.zeros((100, 400, 3), np.uint8)
            cv2.putText(image, identity, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, .8, (255, 255, 255), 1)
            session = AccountSwitchEvidenceSession(identity, root=root / 'screenshots' / 'failures')
            session.record_frame(image)
            session.events.append({'nested': [{'nickname': nickname, 'authorization': secret, 'phone': identity}]})
            event_dir = session.fail(f'token="{secret}"')
            local_event = (event_dir / 'event.json').read_bytes()
            self.assertIn(identity, local_event.decode('utf-8'))
            original_log = log.read_bytes()
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch('ok.og.config', {'gui_title': 'SYNTHETIC'}), \
                        patch('ok.util.file.get_downloads_folder', return_value=str(root / 'export')), \
                        patch('custom_ok.ok.gui.start.StartTab.reveal_in_explorer') as reveal:
                    StartTab.export_logs()
                    reveal.assert_called_once()
            finally:
                os.chdir(previous_cwd)
            with zipfile.ZipFile(root / 'export' / 'SYNTHETIC-log.zip') as archive:
                content = '\n'.join(archive.read(name).decode('utf-8') for name in archive.namelist())
                for value in (identity, nickname, secret):
                    self.assertNotIn(value, content)
                self.assertFalse(any(name.endswith(('.png', '.jpg')) for name in archive.namelist()))
                event = json.loads(next(archive.read(name) for name in archive.namelist() if name.endswith('.json')))
                self.assertEqual(event['target_account'], '[REDACTED]')
            self.assertEqual(original_log, log.read_bytes())
            self.assertEqual(local_event, (event_dir / 'event.json').read_bytes())
            self.assertTrue(list(event_dir.glob('*.jpg')))

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
