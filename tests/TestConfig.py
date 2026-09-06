import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import config


class TestMonthlyHour(unittest.TestCase):
    def test_task_initialization_migrates_legacy_midnight_before_gui_clamping(self):
        from src.task.BaseWWTask import BaseWWTask
        values = {'Monthly Card Time': 24}
        with patch('ok.BaseTask.__init__', return_value=None), \
                patch.object(BaseWWTask, 'get_global_config', return_value=values):
            task = BaseWWTask()
            self.assertEqual(task.monthly_card_config['Monthly Card Time'], 0)

    def test_valid_and_legacy_hours_and_invalid_types(self):
        from src.task.BaseWWTask import normalize_monthly_hour
        for value, expected in ((0, 0), (23, 23), (24, 0)):
            self.assertEqual(normalize_monthly_hour(value), expected)
        for value in (-1, 25, True, False, '4', 'abc', 4.0, None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Monthly Card Time'):
                normalize_monthly_hour(value)
        self.assertEqual(config.monthly_card_config_option.config_type['Monthly Card Time'], {'min': 0, 'max': 23})

    def test_schedule_advances_after_popup_including_midnight(self):
        from src.task.BaseWWTask import BaseWWTask
        for hour, now, next_day, expected in (
            (4, datetime(2026, 9, 6, 3), False, datetime(2026, 9, 6, 4)),
            (4, datetime(2026, 9, 6, 4), False, datetime(2026, 9, 7, 4)),
            (4, datetime(2026, 9, 6, 3), True, datetime(2026, 9, 7, 4)),
            (23, datetime(2026, 9, 6, 23, 1), False, datetime(2026, 9, 7, 23)),
            (0, datetime(2026, 9, 6), False, datetime(2026, 9, 7)),
            (24, datetime(2026, 9, 6, 23, 59), False, datetime(2026, 9, 7)),
        ):
            with self.subTest(hour=hour, now=now), patch('src.task.BaseWWTask.datetime') as clock:
                clock.now.return_value = now
                task = SimpleNamespace(monthly_card_config={'Check Monthly Card': True, 'Monthly Card Time': hour})
                BaseWWTask.set_check_monthly_card(task, next_day=next_day)
                self.assertEqual(task.next_monthly_card_start, (expected - timedelta(seconds=30)).timestamp())


class TestCalculatePcExePath(unittest.TestCase):

    def test_none_path_uses_most_recently_run_executable(self):
        expected = r"C:\Games\Wuthering Waves.exe"

        with patch.object(config, "_find_most_recently_run_pc_exe", return_value=expected) as find:
            with patch.object(config, "_find_pc_exe_from_registry") as find_registry:
                result = config.calculate_pc_exe_path(None)

        find.assert_called_once_with()
        find_registry.assert_not_called()
        self.assertEqual(expected, result)

    def test_none_path_falls_back_to_registry_lookup(self):
        expected = r"C:\Games\Wuthering Waves.exe"

        with patch.object(config, "_find_most_recently_run_pc_exe", return_value=None):
            with patch.object(config, "_find_pc_exe_from_registry", return_value=expected) as find:
                result = config.calculate_pc_exe_path(None)

        find.assert_called_once_with()
        self.assertEqual(expected, result)

    def test_none_path_returns_none_when_no_installation_is_found(self):
        with patch.object(config, "_find_most_recently_run_pc_exe", return_value=None):
            with patch.object(config, "_find_pc_exe_from_registry", return_value=None):
                result = config.calculate_pc_exe_path(None)

        self.assertIsNone(result)

    def test_running_path_still_derives_game_executable(self):
        running_path = (
            r"C:\Games\Wuthering Waves Game\Client\Binaries"
            r"\Win64\Client-Win64-Shipping.exe"
        )

        result = config.calculate_pc_exe_path(running_path)

        self.assertEqual(r"C:\Games\Wuthering Waves Game\Wuthering Waves.exe", result)

    def test_registered_launcher_path_finds_sibling_game_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            install_root = Path(temp)
            launcher = install_root / "Wuthering Waves bilibili" / "launcher.exe"
            game_exe = install_root / "Wuthering Waves Game" / "Wuthering Waves.exe"
            launcher.parent.mkdir()
            game_exe.parent.mkdir()
            game_exe.touch()

            result = config._find_pc_exe_near_registered_path(str(launcher))

        self.assertEqual(str(game_exe), result)


if __name__ == "__main__":
    unittest.main()
