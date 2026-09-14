import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
import numpy as np
from src.task.AutoAbyssTask import AutoAbyssTask, CharacterScanRecord, TOWER_NAMES

class TestAbyssReturnRecovery(unittest.TestCase):
    def make_task(self, mode):
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        self.now = 0
        frame = np.zeros((100,160,3),np.uint8)
        task.next_frame = Mock()
        task.require_game_frame = Mock(return_value=frame)
        task.log_info = Mock()
        task.screenshot = Mock()
        task.ensure_in_front = Mock()
        task.click_box = Mock()
        def sleep(n): self.now += n
        task.sleep = sleep
        def ocr(*args, **kwargs):
            if args[0] == .02:
                if mode == 'overview' or (mode == 'retry' and task.click_box.call_count >= 2):
                    return [SimpleNamespace(name=n) for n in TOWER_NAMES]
                return []
            if mode == 'unknown': return []
            return [SimpleNamespace(name=n) for n in ('挑战失败','返回深塔','再次挑战')]
        task.ocr = ocr
        return task

    def test_retry_then_overview(self):
        task=self.make_task('retry')
        with patch('src.task.AutoAbyssTask.time.monotonic',side_effect=lambda:self.now):
            task._return_from_result('残响之塔',4)
        self.assertEqual(task.click_box.call_count,2)
        self.assertTrue(all(c.args[0].name=='返回深塔' for c in task.click_box.call_args_list))

    def test_existing_overview_never_clicks(self):
        task=self.make_task('overview')
        task._return_from_result('残响之塔',4)
        task.click_box.assert_not_called()

    def test_unknown_never_clicks_and_error_has_context(self):
        task=self.make_task('unknown')
        with patch('src.task.AutoAbyssTask.time.monotonic',side_effect=lambda:self.now):
            with self.assertRaisesRegex(RuntimeError,'残响之塔第4层.*点击0次'):
                task._return_from_result('残响之塔',4)
        task.click_box.assert_not_called()

    def test_retries_are_bounded(self):
        task=self.make_task('failed')
        with patch('src.task.AutoAbyssTask.time.monotonic',side_effect=lambda:self.now):
            with self.assertRaisesRegex(RuntimeError,'点击3次'):
                task._return_from_result('残响之塔',4)
        self.assertEqual(task.click_box.call_count,3)

    def test_stop_prevents_input(self):
        from ok import TaskDisabledException
        task=self.make_task('failed')
        task.next_frame.side_effect=TaskDisabledException()
        with self.assertRaises(TaskDisabledException): task._return_from_result('残响之塔',4)
        task.click_box.assert_not_called()

    def test_already_selected_never_toggles(self):
        task=self.make_task('failed')
        record=CharacterScanRecord('a','A',10,90,.9,1,0)
        task._show_character_page=Mock(return_value=np.zeros((100,160,3),np.uint8))
        task._relocate_record=Mock(return_value=record)
        task._selection_marker_present=Mock(return_value=True)
        task.click_relative=Mock()
        self.assertTrue(task._click_character_record(record,1))
        task.click_relative.assert_not_called()

    def test_failed_tower_is_excluded_before_next_tower_planning(self):
        from src.task.AutoAbyssTask import AVAILABLE, CENTER_TOWER_FIRST
        task=self.make_task('overview')
        task.config={'Tower Priority':CENTER_TOWER_FIRST}
        task._set_status=Mock()
        task._enter_and_scan_characters=Mock(return_value=[])
        seen=[]
        def plan(*args,**kwargs):
            tower,_,remaining,_=task._allocation_context
            seen.append((tower,dict(remaining)))
            return SimpleNamespace(members=('a','b','c'))
        task._plan_and_form_team=plan
        task._planned_team_energy=Mock(return_value=10)
        task._fight_selected_tower=Mock(return_value=('失败',0))
        scans={name:(AVAILABLE,) for name in TOWER_NAMES}
        outcomes=task._run_towers(scans)
        self.assertTrue(all(value=='失败（0层）' for value in outcomes.values()))
        self.assertEqual(seen[1][1]['深境之塔'],())
        self.assertEqual(seen[2][1]['残响之塔'],())
        self.assertEqual(task._enter_and_scan_characters.call_count,3)
        self.assertEqual(scans,{name:(AVAILABLE,) for name in TOWER_NAMES})
