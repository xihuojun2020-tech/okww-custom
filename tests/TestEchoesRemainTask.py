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

    def test_full_run_stops_after_done_and_does_not_mark_activity_complete(self):
        import tempfile
        task=self.make_task([])
        task.log_info=Mock();task.log_warning=Mock();task._navigate=Mock();task._choose=Mock(return_value=self.final)
        task._wait=Mock()
        verification=Mock();verification.begin.return_value=verification
        verification.finish.return_value='verified';verification.profile_id='test';verification.run_id='run'
        with tempfile.TemporaryDirectory() as folder:
            def save(frame):task.last_result['proof']=str(Path(folder)/'proof.png')
            task._save_proof=save
            with patch('src.task.WWOneTimeTask.WWOneTimeTask.run'), patch('src.account_repository.get_default_repository',return_value=Mock()), \
                    patch('src.task.account_feature_verification.FeatureRun',return_value=verification), \
                    patch('src.task.account_feature_verification.expected_profile',return_value='test'):
                task.run()
        task._click.assert_called_once_with(.831,.912)
        self.assertEqual(task.last_result['phase'],'formation_ready')
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
        task._navigate()
        self.assertEqual([c.args for c in task._click.call_args_list],[(.894,.912),(.695,.919)])
        task._open_event.assert_not_called()
        self.assertEqual(task.last_result['stage'],'荣城武神·浅梦')

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


if __name__=='__main__':unittest.main()
