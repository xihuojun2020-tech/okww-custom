from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

import cv2
import numpy as np
from ok import TaskDisabledException
from src.task.EchoesRemainTask import EchoesRemainTask
from src.task.echoes_remain import (INITIAL, FINAL, NUMBER_REGION, card_region, crop,
                                    correction, inspect_roster, trial_clock)


def rect(frame, index, region):
    h, w = frame.shape[:2]
    a, b, c, d = card_region(index, region)
    return round(a*w), round(b*h), round(c*w), round(d*h)


def synthesized_final(initial, unselected):
    """Synthetic UI changes only; never claimed as a real post-click capture."""
    final = initial.copy()
    for index in range(3):
        a,b,c,d = rect(final, index, (0, -.07, 1.1, 1.02))
        final[b:d,a:c] = unselected[b:d,a:c]
        for side in ((0,0,.045,.7),(.955,0,1,.7)):
            source = crop(initial, card_region(index, side))
            a,b,c,d = rect(final,index+3,side)
            final[b:d,a:c] = cv2.resize(source,(c-a,d-b))
        source = crop(initial,card_region(index,NUMBER_REGION))
        a,b,c,d = rect(final,index+3,NUMBER_REGION)
        final[b:d,a:c] = cv2.resize(source,(c-a,d-b))
    return final


class TestEchoesRemainTask(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.initial = cv2.imread('tests/fixtures/echoes_remain/initial.png')
        cls.other = cv2.imread('tests/fixtures/echoes_remain/other_trials.png')
        cls.final = synthesized_final(cls.initial, cls.other)

    def test_real_initial_and_synthetic_final_at_four_resolutions(self):
        for height in (720,1080,1440,2160):
            for source,expected in ((self.initial,INITIAL),(self.final,FINAL)):
                with self.subTest(height=height,expected=expected):
                    state = inspect_roster(cv2.resize(source,(height*16//9,height)))
                    self.assertTrue(state['valid'],state)
                    self.assertEqual(state['numbers'],expected)

    def test_clock_is_independent_of_character_identity(self):
        for source in (self.initial,self.other):
            for height in (720,1080,1440,2160):
                frame=cv2.resize(source,(height*16//9,height))
                self.assertEqual([trial_clock(frame,i) for i in range(7)], [False]*3+[True]*3+[False])

    def test_missing_clock_wrong_order_and_wrong_aspect_are_rejected(self):
        image=self.initial.copy()
        a,b,c,d=rect(image,4,(.62,.46,1.02,.83))
        image[b:d,a:c]=0
        self.assertFalse(inspect_roster(image)['valid'])
        with self.assertRaises(ValueError):inspect_roster(image[:,:1000])
        self.assertIsNone(correction((0,0,0,2,1,3,0)))
        self.assertEqual(correction((0,0,0,1,2,0,0)),5)

    def make_task(self,states):
        task=EchoesRemainTask.__new__(EchoesRemainTask)
        task.info_set=Mock();task.sleep=Mock();task._click=Mock();task.screenshot=Mock()
        task.last_result={}
        task._observe_roster=Mock(side_effect=[(self.initial,s) for s in states])
        return task

    def state(self,numbers,valid=True):
        return {'numbers':numbers,'valid':valid}

    def test_six_clicks_then_one_fresh_review(self):
        task=self.make_task([self.state(INITIAL),self.state(FINAL)])
        task._choose()
        self.assertEqual([c.args for c in task._click.call_args_list],[(.131+.1221*i,.24) for i in range(6)])
        self.assertEqual(task._observe_roster.call_count,2)

    def test_already_selected_does_not_toggle(self):
        task=self.make_task([self.state(FINAL),self.state(FINAL)])
        task._choose();task._click.assert_not_called()

    def test_unsafe_initial_never_clicks(self):
        task=self.make_task([self.state(INITIAL,False)]*2)
        with self.assertRaises(RuntimeError):task._choose()
        task._click.assert_not_called()

    def test_only_missing_last_member_is_repaired(self):
        missing=self.state((0,0,0,1,2,0,0))
        task=self.make_task([self.state(INITIAL),missing,missing,self.state(FINAL)])
        task._choose();self.assertEqual(task._click.call_count,7)
        self.assertEqual(task._click.call_args.args,(.131+.1221*5,.24))

    def test_conflicting_numbers_stop_without_replaying_six_clicks(self):
        wrong=self.state((0,0,0,2,1,3,0))
        task=self.make_task([self.state(INITIAL),wrong,wrong])
        with self.assertRaises(RuntimeError):task._choose()
        self.assertEqual(task._click.call_count,6)

    def test_run_executes_continuation_and_preserves_result(self):
        task=self.make_task([])
        task.log_info=Mock();task.log_warning=Mock();task._navigate=Mock()
        task._save_run_summary=Mock()
        def continuation():
            task.last_result['phase']='challenge_failed'
        task._continue_event=Mock(side_effect=continuation)
        verification=Mock();verification.begin.return_value=verification
        verification.finish.return_value='verified';verification.profile_id='test';verification.run_id='run'
        task.ensure_main=Mock()
        verification.finish.side_effect=lambda: (task.ensure_main.assert_called_once_with(time_out=60) or 'verified')
        with patch('src.task.WWOneTimeTask.WWOneTimeTask.run'), patch('src.account_repository.get_default_repository',return_value=Mock()), \
                patch('src.task.account_feature_verification.FeatureRun',return_value=verification), \
                patch('src.task.account_feature_verification.expected_profile',return_value='test'):
            task.run()
        task._continue_event.assert_called_once()
        self.assertEqual(task.last_result['phase'],'challenge_failed')
        self.assertFalse(task.last_result['activity_complete'])

    def test_stop_interrupts_click_sequence(self):
        task=self.make_task([self.state(INITIAL)])
        task._click.side_effect=TaskDisabledException('stopped')
        with self.assertRaises(TaskDisabledException):task._choose()
        self.assertEqual(task._click.call_count,1)

    def test_navigation_only_clicks_single_and_quick_on_current_stage(self):
        task=self.make_task([]);task.name='若梦仍有回声'
        task.next_frame=Mock(return_value=self.initial)
        task._stage_name=Mock(return_value='荣城武神·浅梦')
        task._button=Mock(return_value=object());task._wait=Mock();task._open_event=Mock()
        task._open_quick=Mock()
        task._click_transition=Mock()
        task._selected_stage_pending=Mock(return_value=True)
        task._navigate()
        task._click.assert_not_called()
        self.assertEqual(task._click_transition.call_args.args[:2], ('单人挑战', 'single'))
        task._open_quick.assert_called_once()
        task._open_event.assert_not_called()
        self.assertEqual(task.last_result['stage'],'荣城武神·浅梦')

    def test_navigation_from_event_uses_both_transitions(self):
        task=self.make_task([])
        task.next_frame=Mock(return_value=self.initial)
        task._stage_page=Mock(side_effect=[None, '溺梦魔影·浅梦'])
        task._open_event=Mock(); task._open_quick=Mock()
        task._click_transition=Mock(return_value=self.initial)
        task._selected_stage_pending=Mock(return_value=True)
        task._navigate()
        self.assertEqual([call.args[:2] for call in task._click_transition.call_args_list],
                         [('前往','event_enter'), ('单人挑战','single')])
        task._click.assert_not_called()
        task._open_quick.assert_called_once()

    def test_proof_is_saved_synchronously_without_account_overlay(self):
        import tempfile,json
        task=self.make_task([]);task.last_result={'phase':'formation_verified','activity_complete':False}
        with tempfile.TemporaryDirectory() as folder, patch('src.runtime.diagnostic_storage.storage_path',return_value=Path(folder)):
            task._save_proof(self.initial)
            path=Path(task.last_result['proof'])
            self.assertTrue(path.is_file())
            saved=cv2.imread(str(path))
            self.assertFalse(saved[:round(len(saved)*.025)].any())
            self.assertFalse(saved[round(len(saved)*.975):].any())
            self.assertEqual(json.loads(path.with_suffix('.json').read_text())['phase'],'formation_verified')


class TestQuickFormationRetry(unittest.TestCase):
    def test_support_and_retry_navigation_recover_lost_click_and_stop_at_target(self):
        for label, delay in (('选中支援声骸',3),('重新挑战若梦副本',5)):
            for enter_on in (0,1,2,4):
                with self.subTest(label=label,enter_on=enter_on):
                    task,clock,frames=self.make_task(enter_on=enter_on)
                    times=[]
                    task._click.side_effect=lambda *args: times.append(clock[0])
                    def navigate():
                        return task.navigate_ui(label,task._formation_page,task._roster_page,
                            action=lambda _:task._click(.3,.4), attempts=3,retry_after=delay)
                    with patch('src.task.EchoesRemainTask.time.monotonic',side_effect=lambda:clock[0]):
                        if enter_on==4:
                            with self.assertRaisesRegex(RuntimeError,'上限'):
                                navigate()
                        else:
                            self.assertIs(navigate(),frames[2])
                    self.assertEqual(task._click.call_count,min(enter_on,3))
                    for previous,current in zip(times,times[1:]):
                        self.assertGreaterEqual(current-previous,delay)

    def test_navigation_transitions_use_requested_target_and_retry(self):
        for label, key in (('前往','event_enter'), ('单人挑战','single')):
            for height in (1080,1440):
                with self.subTest(label=label,height=height):
                    task, clock, frames = self.make_task(height)
                    source, target = task._formation_page, task._roster_page
                    task._roster_page = Mock(side_effect=AssertionError('wrong target probe'))
                    with patch('src.task.EchoesRemainTask.time.monotonic', side_effect=lambda: clock[0]):
                        result = task._click_transition(label,key,source,target)
                    self.assertIs(result, frames[2])
                    self.assertEqual(task._click.call_count,2)
                    self.assertEqual(task.last_result[f'{key}_entry_attempts'][-1]['result'],'entered')

    def test_single_challenge_rejects_changed_stage_before_click(self):
        task, clock, frames = self.make_task()
        task._stage_page = Mock(return_value='其他关卡·浅梦')
        with self.assertRaisesRegex(RuntimeError,'关卡已变化'):
            task._single_button(frames[1], '溺梦魔影·浅梦')
        task._click.assert_not_called()

    def test_formation_requires_matching_stage(self):
        task, _, frames = self.make_task()
        for observed in ('溺梦魔影·浅梦','其他关卡·浅梦',None):
            task.ocr = Mock(return_value=[SimpleNamespace(name=observed)] if observed else [])
            if observed == '其他关卡·浅梦':
                with self.assertRaisesRegex(RuntimeError,'不一致'):
                    task._formation_for_stage(frames[1], '溺梦魔影·浅梦')
            else:
                self.assertEqual(task._formation_for_stage(frames[1], '溺梦魔影·浅梦'), bool(observed))

    def make_task(self, height=1440, enter_on=2):
        task = EchoesRemainTask.__new__(EchoesRemainTask)
        task.last_result = {}
        task.info_set = Mock(); task.log_info = Mock(); task.log_warning = Mock()
        task.screenshot = Mock(); task._click = Mock()
        clock = [0.]
        task.sleep = lambda seconds: clock.__setitem__(0, clock[0]+seconds)
        width = height*16//9
        frames = {n: np.full((height,width,3),n,np.uint8) for n in (1,2,3)}
        task.next_frame = Mock(side_effect=lambda: frames[2 if task._click.call_count >= enter_on else 1])
        button = Mock(); button.center.return_value = (.698*width,.92*height)
        task._formation_page = lambda frame: button if frame[0,0,0] == 1 else None
        task._roster_page = lambda frame: frame[0,0,0] == 2
        task._guard = Mock(); task._guard_account_input = Mock()
        task._executor = SimpleNamespace(check_enabled=Mock(), current_task=task,
            device_manager=SimpleNamespace(hwnd_window=SimpleNamespace(hwnd=1, exists=True)),
            method=SimpleNamespace(width=width, height=height), _last_frame_time=0)
        task.require_game_frame = lambda: task.next_frame.return_value if isinstance(task.next_frame.return_value, np.ndarray) else frames[2 if task._click.call_count >= enter_on else 1]
        original_next = task.next_frame
        def fresh():
            frame = original_next()
            task._executor._last_frame_time += 1
            task._test_frame = frame
            return frame
        task.next_frame = Mock(side_effect=fresh)
        task.require_game_frame = lambda: task._test_frame
        return task, clock, frames

    def test_ignored_first_click_retries_fresh_button_at_both_resolutions(self):
        for height in (1080,1440):
            with self.subTest(height=height):
                task, clock, _ = self.make_task(height)
                click_times = []
                task._click.side_effect = lambda *args: click_times.append(clock[0])
                with patch('src.task.EchoesRemainTask.time.monotonic', side_effect=lambda: clock[0]):
                    task._open_quick()
                self.assertGreaterEqual(click_times[0], .7)
                self.assertEqual(task._click.call_count, 2)
                for actual, expected in zip(task._click.call_args.args, (.698,.92)):
                    self.assertAlmostEqual(actual, expected)
                self.assertEqual([e['result'] for e in task.last_result['quick_entry_attempts']],
                                 ['still_formation','entered'])
                self.assertEqual(task.screenshot.call_count, 4)
                for call in task.screenshot.call_args_list:
                    saved = call.kwargs['frame']
                    self.assertFalse(saved[:round(height*.025)].any())
                    self.assertFalse(saved[round(height*.975):].any())

    def test_three_missed_clicks_stop(self):
        task, clock, _ = self.make_task(enter_on=99)
        with patch('src.task.EchoesRemainTask.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(RuntimeError, '点击次数'):
                task._open_quick()
        self.assertEqual(task._click.call_count, 3)

    def test_changed_page_is_never_clicked_again(self):
        task, clock, frames = self.make_task()
        def changed():
            task._executor._last_frame_time += 1
            task._test_frame = frames[3 if task._click.call_count else 1]
            return task._test_frame
        task.next_frame.side_effect = changed
        with patch('src.task.EchoesRemainTask.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(RuntimeError, '耗尽'):
                task._open_quick()
        self.assertEqual(task._click.call_count, 1)

    def test_already_entered_does_not_click(self):
        task, clock, _ = self.make_task(enter_on=0)
        with patch('src.task.EchoesRemainTask.time.monotonic', side_effect=lambda: clock[0]):
            task._open_quick()
        task._click.assert_not_called()

    def test_late_transition_before_retry_does_not_double_click(self):
        task, clock, frames = self.make_task()
        calls_after_click = [0]
        def frame():
            if task._click.call_count:
                calls_after_click[0] += 1
            # Destination arrives on the last observation before a retry is allowed.
            task._executor._last_frame_time += 1
            task._test_frame = frames[2 if calls_after_click[0] >= 9 else 1]
            return task._test_frame
        task.next_frame.side_effect = frame
        with patch('src.task.EchoesRemainTask.time.monotonic', side_effect=lambda: clock[0]):
            task._open_quick()
        self.assertEqual(task._click.call_count, 1)

    def test_diagnostic_failure_does_not_break_successful_entry(self):
        task, clock, _ = self.make_task(enter_on=1)
        task.screenshot.side_effect = OSError('disk unavailable')
        with patch('src.task.EchoesRemainTask.time.monotonic', side_effect=lambda: clock[0]):
            task._open_quick()
        self.assertEqual(task.last_result['quick_entry_attempts'][0]['result'], 'entered')
        self.assertEqual(task.log_warning.call_count, 2)

    def test_unstable_button_does_not_click(self):
        task, clock, _ = self.make_task()
        button = Mock()
        button.center.side_effect = lambda: (1700 if task.next_frame.call_count % 2 else 1800, 1300)
        task._formation_page = Mock(return_value=button)
        with patch('src.task.EchoesRemainTask.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(RuntimeError, '耗尽'):
                task._open_quick()
        task._click.assert_not_called()

    def test_user_stop_is_not_retried(self):
        task, clock, _ = self.make_task()
        task._click.side_effect = TaskDisabledException('stopped')
        with patch('src.task.EchoesRemainTask.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(TaskDisabledException):
                task._open_quick()
        self.assertEqual(task._click.call_count, 1)


if __name__=='__main__':unittest.main()
