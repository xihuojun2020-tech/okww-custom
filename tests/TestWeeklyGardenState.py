import os
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

from src.task.GardenTask import GardenTask
from src.task.weekly_garden import (
    BEIJING,
    GARDEN_CLOSED,
    GARDEN_DAILY,
    GARDEN_INDEPENDENT,
    garden_completed_this_week,
    garden_week_key,
    normalize_garden_mode,
)


class TestWeeklyGardenState(unittest.TestCase):
    def test_game_week_changes_at_monday_four_am_beijing(self):
        before = datetime(2026, 9, 28, 3, 59, tzinfo=BEIJING)
        boundary = datetime(2026, 9, 28, 4, 0, tzinfo=BEIJING)
        self.assertEqual(garden_week_key(before), '2026-09-21T04:00:00+08:00')
        self.assertEqual(garden_week_key(boundary), '2026-09-28T04:00:00+08:00')

    def test_completion_accepts_legacy_naive_timestamp_and_rejects_future_or_invalid(self):
        now = datetime(2026, 9, 28, 12, 0, tzinfo=BEIJING)
        self.assertTrue(garden_completed_this_week('2026-09-28T05:00:00', now))
        self.assertFalse(garden_completed_this_week('2026-09-28T12:01:00+08:00', now))
        self.assertFalse(garden_completed_this_week('not-a-timestamp', now))
        self.assertFalse(garden_completed_this_week(None, now))

    def test_mode_normalization_keeps_explicit_values_and_closes_bad_legacy_values(self):
        self.assertEqual(normalize_garden_mode(GARDEN_DAILY, 'bad day'), GARDEN_DAILY)
        self.assertEqual(normalize_garden_mode(None, 'Monday'), GARDEN_INDEPENDENT)
        self.assertEqual(normalize_garden_mode('old-mode', '星期八'), GARDEN_CLOSED)
        self.assertEqual(normalize_garden_mode(None, None), GARDEN_CLOSED)

    @staticmethod
    def _reader(ocr_text, frame=object()):
        task = object.__new__(GardenTask)
        task.next_frame = Mock(return_value=frame)
        task.ocr = Mock(return_value=[] if ocr_text is None else [SimpleNamespace(name=ocr_text)])
        task.log_info = Mock()
        return task

    def test_score_parser_reads_earned_points_not_just_target(self):
        for text, expected in (('5999/6000', 5999), ('6000/6000', 6000)):
            with self.subTest(text=text):
                task = self._reader(text)
                self.assertEqual(task.read_weekly_garden_points(), expected)

    def test_single_target_blank_ocr_and_missing_frame_are_unknown(self):
        self.assertIsNone(self._reader('6000').read_weekly_garden_points())
        self.assertIsNone(self._reader(None).read_weekly_garden_points())
        task = self._reader('6000/6000', frame=None)
        self.assertIsNone(task.read_weekly_garden_points())
        task.ocr.assert_not_called()

    def test_end_screen_requires_full_score_pair(self):
        task = object.__new__(GardenTask)
        self.assertTrue(task.is_garden_done(['6000/6000']))
        self.assertFalse(task.is_garden_done(['6000']))
        self.assertFalse(task.is_garden_done([]))

    def test_state_and_score_checks_run_in_a_fresh_process(self):
        script = r'''from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
from src.task.GardenTask import GardenTask
from src.task.weekly_garden import BEIJING, garden_week_key
assert garden_week_key(datetime(2026, 9, 28, 3, 59, tzinfo=BEIJING)) == '2026-09-21T04:00:00+08:00'
task = object.__new__(GardenTask)
task.next_frame = Mock(return_value=object())
task.ocr = Mock(return_value=[SimpleNamespace(name='6000/6000')])
task.log_info = Mock()
assert task.read_weekly_garden_points() == 6000
'''
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
        result = subprocess.run([sys.executable, '-c', script],
                                cwd=Path(__file__).resolve().parents[1], env=env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @staticmethod
    def _run_with_mocked_end_screen(scores, end_text, frame_values=None):
        from src.task.WWOneTimeTask import WWOneTimeTask
        task = object.__new__(GardenTask)
        task.last_result = None
        task.ensure_main = Mock()
        task.open_garden_weekly_page = Mock()
        values = iter(scores)
        task.read_weekly_garden_points = Mock(side_effect=lambda: next(values, None))
        task.record_verified_result = Mock(return_value='weekly_garden:test:week')
        task.find_best_garden_feature = Mock(return_value=None)
        frame_values = list(frame_values if frame_values is not None else (object(), object(), object()))
        task.next_frame = Mock(side_effect=frame_values)
        restart, back = object(), object()
        task.find_one = Mock(side_effect=lambda name: {
            'a_garden_restart': restart,
            'a_garden_back': back,
        }.get(name))
        task.ocr = Mock(return_value=[SimpleNamespace(name=text) for text in end_text])
        task.click = Mock()
        task.sleep = Mock()
        task.wait_feature = Mock(return_value=False)
        task.wait_book = Mock(return_value=False)
        task.back = Mock()
        task.log_info = Mock()
        task.log_warning = Mock()
        task.info_set = Mock()
        with patch.object(WWOneTimeTask, 'run'), \
             patch('src.task.GardenTask.garden_week_key', return_value='2026-09-28T04:00:00+08:00'), \
             patch('src.evidence.service.record_task_evidence'):
            try:
                task.run()
            except RuntimeError:
                # An unresolved result may still raise so the task scheduler records failure.
                pass
        return task, restart

    def test_single_starting_frame_at_cap_does_not_verify_completion(self):
        task, _ = self._run_with_mocked_end_screen([6000, None, None], [])
        self.assertFalse(task.last_result.verified)
        task.record_verified_result.assert_not_called()

    def test_ambiguous_end_screen_is_rechecked_without_restart_spam_or_success_message(self):
        cases = (([], (object(), object(), object())),
                 (['6000'], (object(), object(), object())),
                 ([], (None, None, None)))
        for text, frames in cases:
            with self.subTest(text=text, frames_have_data=any(frame is not None for frame in frames)):
                task, restart = self._run_with_mocked_end_screen([0, None, None], text, frames)
                restart_clicks = [call for call in task.click.call_args_list
                                  if call.args and call.args[0] is restart]
                self.assertEqual(restart_clicks, [])
                self.assertLessEqual(task.ocr.call_count, 3)
                if all(frame is None for frame in frames):
                    task.ocr.assert_not_called()
                else:
                    ocr_frames = [call.kwargs.get('frame') for call in task.ocr.call_args_list]
                    self.assertTrue(all(frame is not None for frame in ocr_frames))
                    self.assertEqual(len({id(frame) for frame in ocr_frames}), len(ocr_frames))
                    for index, frame in enumerate(ocr_frames):
                        self.assertIs(frame, frames[index])
                self.assertEqual(task.last_result.status, 'pending')
                log_text = ' '.join(str(call) for call in task.log_info.call_args_list)
                self.assertNotIn('已达到上限', log_text)

    def test_verified_terminal_score_returns_to_weekly_page_and_main(self):
        task, _ = self._run_with_mocked_end_screen(
            [0, 6000, 6000], ['6000/6000'], (object(), object(), object()))

        self.assertEqual(task.last_result.status, 'completed')
        self.assertTrue(task.last_result.verified)
        self.assertEqual(task.last_result.points, 6000)
        self.assertEqual(task.open_garden_weekly_page.call_count, 2)
        task.record_verified_result.assert_called_once_with(
            6000, '2026-09-28T04:00:00+08:00')
        task.ensure_main.assert_any_call(time_out=180)
        task.wait_feature.assert_called_once_with('garden_start_game', settle_time=1, time_out=5)
        task.wait_book.assert_called_once_with('gray_book_quest', time_out=30)


if __name__ == '__main__':
    unittest.main()
