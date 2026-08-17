import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import test_account_switch as account_switch
from src.task.TestAccountSwitchTask import DEFAULT_CONTINUOUS_ORDER, TestAccountSwitchTask


def _ocr_box(text, y=0):
    return {
        'text': text,
        'confidence': 1.0,
        'center': (5, y + 5),
        'box': [[0, y], [10, y], [10, y + 10], [0, y + 10]],
    }


class TestAccountSwitchStandalone(unittest.TestCase):

    def test_app_task_continuous_order_defaults_to_a1_a3_a4(self):
        self.assertEqual(DEFAULT_CONTINUOUS_ORDER, 'A1,A3,A4')
        self.assertEqual(
            TestAccountSwitchTask._parse_continuous_order('a1， A3 A4'),
            ['A1', 'A3', 'A4'],
        )

    def test_run_rejects_non_positive_round_count_before_touching_game(self):
        with redirect_stdout(io.StringIO()):
            self.assertFalse(account_switch.run_test(rounds=0))

    def test_parse_profiles_reads_nested_current_schema(self):
        data = {
            'profiles': {
                '【A1-测试-13000000001】': {
                    '备用识别名称内容': 'U123， demo@example.com',
                    'account_aliases': ['legacy@example.com'],
                },
            },
            'sequences': {'序列1': ['【A1-测试-13000000001】']},
        }
        self.assertEqual(
            account_switch._parse_profiles(data),
            {
                '【A1-测试-13000000001】': [
                    'U123',
                    'demo@example.com',
                    'legacy@example.com',
                ],
            },
        )

    def test_parse_profiles_supports_legacy_schema_without_metadata_entries(self):
        data = {
            '【A2-测试-13000000002】': {'Account Name': 'demo@example.com'},
            'sequences': {'序列1': ['【A2-测试-13000000002】']},
            'active_profile': '【A2-测试-13000000002】',
        }
        self.assertEqual(
            account_switch._parse_profiles(data),
            {'【A2-测试-13000000002】': ['demo@example.com']},
        )

    def test_switch_retries_when_selected_account_does_not_match(self):
        target_box = _ocr_box('153****0003')
        login_box = _ocr_box('登录', y=20)
        game_windows = [
            {'hwnd': 1, 'class': 'UnrealWindow', 'title': '', 'visible': True,
             'rect': (0, 0, 1920, 1080)},
            {'hwnd': 2, 'class': 'ComboBox', 'title': '', 'visible': True,
             'rect': (100, 100, 300, 140)},
        ]

        def find_control(class_name, _windows):
            if class_name == 'ComboBox':
                return 2, (100, 100, 300, 140)
            return None, None

        with patch.object(account_switch, '_find_game_hwnd', return_value=(1, game_windows)), \
                patch.object(account_switch, '_find_control_hwnd', side_effect=find_control), \
                patch.object(account_switch, '_wait_for_account_list',
                             return_value=(object(), (0, 0), [target_box], game_windows)), \
                patch.object(account_switch, '_selected_target_from_dialog',
                             side_effect=[
                                 (False, ['130****0001'], object(), (0, 0)),
                                 (True, ['153****0003'], object(), (0, 0)),
                             ]) as selected, \
                patch.object(account_switch, '_capture_hwnd',
                             return_value=(object(), (0, 0))), \
                patch.object(account_switch, '_ocr_frame', return_value=[login_box]), \
                patch.object(account_switch, '_screen_click'), \
                patch.object(account_switch, '_wait_for_login_completion', return_value=True), \
                patch.object(account_switch.time, 'sleep'), \
                redirect_stdout(io.StringIO()):
            result = account_switch._do_switch(
                'A3',
                ['153****0003'],
                dlg_hwnd=3,
                ocr_engine=object(),
                save_screenshots=False,
                max_select_retries=3,
            )

        self.assertTrue(result)
        self.assertEqual(selected.call_count, 2)

    def test_switch_fails_when_login_completion_cannot_be_confirmed(self):
        target_box = _ocr_box('153****0003')
        login_box = _ocr_box('登录', y=20)
        game_windows = [
            {'hwnd': 1, 'class': 'UnrealWindow', 'title': '', 'visible': True,
             'rect': (0, 0, 1920, 1080)},
        ]

        with patch.object(account_switch, '_find_game_hwnd', return_value=(1, game_windows)), \
                patch.object(account_switch, '_find_control_hwnd',
                             side_effect=lambda name, _windows: (
                                 (4, (0, 0, 300, 200)) if name == 'ComboLBox'
                                 else (2, (100, 100, 300, 140))
                             )), \
                patch.object(account_switch, '_wait_for_account_list',
                             return_value=(object(), (0, 0), [target_box], game_windows)), \
                patch.object(account_switch, '_selected_target_from_dialog',
                             return_value=(True, ['153****0003'], object(), (0, 0))), \
                patch.object(account_switch, '_capture_hwnd',
                             return_value=(object(), (0, 0))), \
                patch.object(account_switch, '_ocr_frame', return_value=[login_box]), \
                patch.object(account_switch, '_screen_click'), \
                patch.object(account_switch, '_wait_for_login_completion', return_value=False), \
                patch.object(account_switch.time, 'sleep'), \
                redirect_stdout(io.StringIO()):
            result = account_switch._do_switch(
                'A3',
                ['153****0003'],
                dlg_hwnd=3,
                ocr_engine=object(),
                save_screenshots=False,
            )

        self.assertFalse(result)

    def test_login_completion_requires_stable_dialog_disappearance(self):
        clock = {'now': 0.0}
        game_windows = [
            {'hwnd': 1, 'class': 'UnrealWindow', 'title': '', 'visible': True,
             'rect': (0, 0, 1920, 1080)},
        ]

        def monotonic():
            return clock['now']

        def sleep(seconds):
            clock['now'] += seconds

        with patch.object(account_switch, '_find_game_hwnd', return_value=(1, game_windows)), \
                patch.object(account_switch, '_find_dialog_hwnd', return_value=(None, None)), \
                patch.object(account_switch.time, 'monotonic', side_effect=monotonic), \
                patch.object(account_switch.time, 'sleep', side_effect=sleep):
            result = account_switch._wait_for_login_completion(
                timeout=5,
                stable_seconds=1,
            )

        self.assertTrue(result)
        self.assertGreaterEqual(clock['now'], 1)


if __name__ == '__main__':
    unittest.main()
