import unittest
from unittest.mock import Mock
from tests import TestNavigationAdapter as nav_tests
from src.task.AutoAbyssTask import AutoAbyssTask

class TestAbyssFormationBack(unittest.TestCase):
    def test_page_classifier_requires_compound_markers(self):
        from types import SimpleNamespace
        from src.task.AutoAbyssTask import TOWER_NAMES
        task = Mock()
        cases = [
            (['详情'], ['完成'], [], 0),
            (['编辑队伍'], ['开启挑战'], [], 1),
            ([TOWER_NAMES[0]], [], ['挑战目标'], 2),
            (list(TOWER_NAMES), [], [], 3),
            (['详情'], [], [], None),
            (['编辑队伍'], ['确认'], [], None),
            ([TOWER_NAMES[0]], [], [], None),
            ([], ['完成'], ['挑战目标'], None),
            (['挑战失败'], ['返回深塔'], [], None),
        ]
        for titles, buttons, body, expected in cases:
            def ocr(*args, **kwargs):
                names = titles if args and args[0] in (.01, .054) else buttons if args else body
                return [SimpleNamespace(name=name) for name in names]
            task.ocr = ocr
            with self.subTest(titles=titles, buttons=buttons, body=body):
                self.assertEqual(AutoAbyssTask._formation_back_page(task, object()), expected)

    def task(self):
        harness=nav_tests.TestNavigationAdapter();self.addCleanup(harness.doCleanups)
        task=harness.task();task.send_key=Mock()
        return task
    def test_three_known_pages_then_overview(self):
        task=self.task();task._formation_back_page=lambda frame:min(task.send_key.call_count,3)
        self.assertTrue(AutoAbyssTask._return_from_team_to_towers(task))
        self.assertEqual(task.send_key.call_count,3)
    def test_lost_first_key_recovered_within_shared_budget(self):
        task=self.task();task._formation_back_page=lambda frame:max(0,min(task.send_key.call_count-1,3))
        self.assertTrue(AutoAbyssTask._return_from_team_to_towers(task))
        self.assertEqual(task.send_key.call_count,4)
    def test_unknown_initial_page_never_escapes(self):
        task=self.task();task._formation_back_page=lambda frame:None
        with self.assertRaisesRegex(RuntimeError,'页面未知'):
            AutoAbyssTask._return_from_team_to_towers(task)
        task.send_key.assert_not_called()
    def test_unknown_after_key_never_replays_it(self):
        task=self.task();task._formation_back_page=lambda frame:None if task.send_key.called else 0
        with self.assertRaises(RuntimeError):AutoAbyssTask._return_from_team_to_towers(task)
        task.send_key.assert_called_once_with('esc')
    def test_return_direction_cannot_reverse(self):
        task=self.task();task._formation_back_page=lambda frame:0 if task.send_key.called else 1
        with self.assertRaisesRegex(RuntimeError,'方向异常'):
            AutoAbyssTask._return_from_team_to_towers(task)
        task.send_key.assert_called_once()

    def test_start_without_confirmed_loading_is_never_replayed(self):
        from types import SimpleNamespace
        task=self.task();task.click_box=Mock();task._abyss_environment_hint=lambda frame:None
        button=SimpleNamespace(name='开启挑战',center=lambda:(700,900))
        task.ocr=lambda *args,**kwargs:[SimpleNamespace(name='编辑队伍'),button]
        with self.assertRaises(RuntimeError):AutoAbyssTask._click_start_challenge(task)
        task.click_box.assert_called_once()
    def test_environment_escape_retries_only_while_hint_remains(self):
        task=self.task();task._set_status=Mock()
        task._abyss_environment_hint=lambda frame:True if task.send_key.call_count<2 else None
        task.in_team_and_world=lambda **kwargs:task.send_key.call_count>=2
        AutoAbyssTask._prepare_challenge_map(task,'残响之塔',1)
        self.assertEqual(task.send_key.call_count,2)


if __name__=='__main__':unittest.main()
