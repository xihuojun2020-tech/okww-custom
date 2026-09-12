import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np
from ok import TaskDisabledException
from src.task.character_trial import (
    exact_button, reward_state, start_prompt, detect_portraits, unique_match,
    merge_view, portrait_selected, Portrait,
)
from src.task.CharacterTrialTask import CharacterTrialTask, TrialTimeout, TrialFinished
from src.task.BaseCombatTask import BaseCombatTask, CharDeadException, CombatStateUnknown
from src.task.WWOneTimeTask import WWOneTimeTask
from src.char.BaseChar import BaseChar
from src.char.TrialGenericChar import TrialGenericChar
from src.gui.navigation_sections import classify_task, task_category

FIXTURES = Path(__file__).parent / 'fixtures' / 'character_trial'


def box(name, x=0, y=0):
    return SimpleNamespace(name=name, x=x, y=y, width=40, height=20)


class TestTrialRecognition(unittest.TestCase):
    def test_activity_title_only_normalizes_known_glyphs(self):
        for text in ('初露峥嵘','初露崢嵘','初露崢嶸','初露崢蝶'):
            candidate=box(text)
            self.assertIs(CharacterTrialTask._activity_title([candidate]),candidate)
        self.assertIsNone(CharacterTrialTask._activity_title([box('初露峥嵘奖励')]))
        self.assertIsNone(CharacterTrialTask._activity_title([box('初露峥嵘'),box('初露崢嵘')]))

    def test_reward_states_are_exclusive(self):
        for text, state in [('进行中','pending'), ('领取','claim'), ('已完成','complete')]:
            self.assertEqual(reward_state([box(text)]), state)
        for names in [[], ['前往试用'], ['已完成','领取'], ['领取','进行中'], ['奖励预览']]:
            self.assertIsNone(reward_state([box(n) for n in names]))

    def test_confirm_does_not_match_dialog_message_or_duplicates(self):
        message, button = box('确认离开'), box('确认')
        self.assertIs(exact_button([message,button], '确认'), button)
        self.assertIsNone(exact_button([message], '确认'))
        self.assertIsNone(exact_button([button,box('确认')], '确认'))

    def test_start_requires_same_row_key_and_correct_text(self):
        self.assertTrue(start_prompt([box('F',100,100),box('开启挑战',160,100)],1152))
        for names in [[box('开启挑战')], [box('F',100,20),box('开启挑战',160,100)],
                      [box('F',100,100),box('开始挑战',160,100)]]:
            self.assertFalse(start_prompt(names,1152))

    def test_real_portraits_and_selection_across_scaling(self):
        reference = detect_portraits(cv2.imread(str(FIXTURES/'claim.png')))[0]
        for name, selected in [('claim',1),('pending',0),('complete',3)]:
            original = cv2.imread(str(FIXTURES/f'{name}.png'))
            for height in (720,1080,1440,2160):
                with self.subTest(name=name,height=height):
                    image = cv2.resize(original, (height*16//9,height))
                    cards,left,right = detect_portraits(image)
                    self.assertEqual(len(cards),4)
                    self.assertFalse(left)
                    self.assertTrue(right)
                    self.assertEqual([portrait_selected(image,c) for c in cards],
                                     [i==selected for i in range(4)])
                    self.assertEqual([unique_match(c.image,reference) for c in cards],list(range(4)))

    def test_unknown_layout_is_rejected(self):
        for image in [np.zeros((1152,2048,3),np.uint8),np.zeros((800,1000,3),np.uint8)]:
            with self.assertRaises(RuntimeError):
                detect_portraits(image)

    def test_contiguous_overlap_covers_five_and_six_without_duplicates(self):
        rng=np.random.default_rng(4)
        cards=[Portrait(i*176,1013,160,61,rng.integers(0,255,(61,160,3),dtype=np.uint8)) for i in range(6)]
        for count in (5,6):
            merged=merge_view(cards[:4],cards[count-4:count])
            self.assertEqual(merged,cards[:count])
            self.assertEqual(merge_view(merged,cards[count-4:count]),merged)
        with self.assertRaises(RuntimeError):
            merge_view(cards[:2],cards[3:])
        with self.assertRaises(RuntimeError):
            merge_view(cards[:4],[cards[2],cards[1],cards[4]])
        with self.assertRaises(RuntimeError):
            unique_match(cards[0].image,[cards[0],cards[0]])

    def test_fixture_identity_region_is_blank(self):
        for path in FIXTURES.glob('*.png'):
            image=cv2.imread(str(path))
            self.assertFalse(np.any(image[round(image.shape[0]*.95):]),path.name)


class TestTrialFlow(unittest.TestCase):
    def test_intro_appearing_during_map_settle_is_closed_with_escape(self):
        t=self.task();clock=[0.0];t.next_frame=Mock();t.send_key=Mock()
        t.sleep=Mock(side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds))
        t._intro=Mock(side_effect=lambda: .4 <= clock[0] < .8)
        t._map_ready=Mock(return_value=True)
        with patch('src.task.CharacterTrialTask.time.monotonic',side_effect=lambda:clock[0]):
            t._wait_trial_map()
        t.send_key.assert_called_once_with('esc')
        self.assertGreaterEqual(clock[0],2.8)

    def test_intro_close_retries_are_bounded(self):
        t=self.task();clock=[0.0];t.next_frame=Mock();t.send_key=Mock()
        t.sleep=Mock(side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds))
        t._intro=Mock(return_value=True);t._map_ready=Mock()
        with patch('src.task.CharacterTrialTask.time.monotonic',side_effect=lambda:clock[0]):
            with self.assertRaisesRegex(TrialTimeout,'Esc三次'):t._wait_trial_map()
        self.assertEqual(t.send_key.call_count,3);t._map_ready.assert_not_called()

    def test_intro_stop_prevents_escape(self):
        t=self.task();t.next_frame=Mock(side_effect=TaskDisabledException());t.send_key=Mock()
        with self.assertRaises(TaskDisabledException):t._wait_trial_map()
        t.send_key.assert_not_called()

    def test_intro_needs_next_and_close_marker(self):
        t=self.task()
        for next_button,close in ((False,True),(True,False),(True,True)):
            t._button=Mock(return_value=next_button);t.find_one=Mock(return_value=close)
            self.assertEqual(t._intro(),next_button and close)

    def activity_task(self):
        t=self.task()
        t.next_frame=Mock(); t._page=Mock(return_value=False)
        t._ocr=Mock(return_value=[box('初露峥嵘',100,200)])
        t.click=Mock(); t._wait=Mock()
        return t

    def test_activity_retries_with_fresh_target(self):
        t=self.activity_task()
        first,second=box('初露峥嵘',100,200),box('初露峥嵘',100,300)
        t._ocr.side_effect=lambda region: ([first if t.next_frame.call_count==1 else second]
                                         if region==t.LIST else [box('若梦仍有回声')])
        t._wait.side_effect=[TrialTimeout('ignored click'),True]
        t._select_activity()
        self.assertEqual(t.next_frame.call_count,2)
        self.assertEqual([c.args[0] for c in t.click.call_args_list],[first,second])

    def test_activity_already_open_never_clicks(self):
        t=self.activity_task();t._page.return_value=True
        t._select_activity();t.click.assert_not_called()

    def test_activity_failure_is_bounded(self):
        t=self.activity_task();t._wait.side_effect=TrialTimeout('wrong page')
        with self.assertRaisesRegex(TrialTimeout,'3次后仍未切换'):t._select_activity()
        self.assertEqual(t.click.call_count,3)

    def test_activity_disappeared_never_reuses_old_target(self):
        t=self.activity_task();t._wait.side_effect=TrialTimeout('wrong page')
        t._ocr.side_effect=lambda region: [box('初露峥嵘')] if t.next_frame.call_count==1 else []
        with self.assertRaisesRegex(TrialTimeout,'入口消失'):t._select_activity()
        self.assertEqual(t.click.call_count,1)

    def test_activity_stop_and_capture_errors_do_not_retry(self):
        for error in (TaskDisabledException(),RuntimeError('capture failed')):
            t=self.activity_task();t._wait.side_effect=error
            with self.assertRaises(type(error)):t._select_activity()
            self.assertEqual(t.click.call_count,1)

    def test_open_routes_visible_entry_to_confirmed_selection(self):
        t=self.activity_task();t._button=Mock(return_value=True);t._select_activity=Mock()
        t._open();t._select_activity.assert_called_once();t.click.assert_not_called()

    def task(self):
        task=object.__new__(CharacterTrialTask)
        task._executor=Mock()
        task._battle_deadline=None
        task._trial_map=False
        task._frame_serial=0
        task._last_done_frame=-1
        task._done_count=0
        task._held_keys=set()
        task._held_mouse=set()
        task.config={'Trial Combat Timeout':180}
        task.info={}
        task.logger=Mock()
        task._stage=Mock()
        task.info_set=Mock()
        task.screenshot=Mock()
        return task

    def test_complete_never_enters_even_with_trial_button(self):
        t=self.task(); t._select=Mock(); t._state=Mock(return_value='complete')
        t._enter=Mock(); t._claim=Mock()
        self.assertEqual(t._process(object()),'already_complete')
        t._enter.assert_not_called(); t._claim.assert_not_called()

    def test_direct_and_trial_claim_paths(self):
        for state in ('claim','pending'):
            t=self.task(); t._state=Mock(side_effect=[state,'claim'])
            for method in ('_select','_claim','_enter','_start','_fight','_leave'):
                setattr(t,method,Mock())
            self.assertEqual(t._process(object()),'direct_claimed' if state=='claim' else 'trial_claimed')
            self.assertEqual(t._enter.call_count,int(state=='pending'))
            t._claim.assert_called_once()

    def test_return_still_pending_cannot_claim(self):
        t=self.task(); t._state=Mock(return_value='pending')
        for method in ('_select','_claim','_enter','_start','_fight','_leave'):
            setattr(t,method,Mock())
        with self.assertRaisesRegex(RuntimeError,'未变为领取'): t._process(object())
        t._claim.assert_not_called()

    def test_stopping_at_each_trial_step_prevents_later_steps(self):
        methods=('_select','_enter','_start','_fight','_leave','_claim')
        for stop_at in methods:
            t=self.task(); t._state=Mock(side_effect=['pending','claim'])
            for method in methods: setattr(t,method,Mock())
            getattr(t,stop_at).side_effect=TaskDisabledException()
            with self.assertRaises(TaskDisabledException): t._process(object())
            for method in methods[methods.index(stop_at)+1:]:
                getattr(t,method).assert_not_called()

    def test_completion_requires_two_distinct_frames(self):
        t=self.task(); t._button=Mock(return_value=box('离开模拟领域'))
        self.assertFalse(t._finished()); self.assertFalse(t._finished())
        t._frame_serial+=1; self.assertTrue(t._finished())
        t._frame_serial+=1; t._button.return_value=None
        self.assertFalse(t._finished())

    def test_deadline_checked_before_input_and_during_sleep(self):
        t=self.task(); t._battle_deadline=0
        for call in (lambda:t.send_key('f'),lambda:t.click(1,1),t.sleep_check):
            with self.assertRaises(TrialTimeout): call()
        t.executor.interaction.send_key.assert_not_called()

    def test_stop_guard_prevents_click(self):
        t=self.task(); t.executor.check_enabled.side_effect=TaskDisabledException()
        with self.assertRaises(TaskDisabledException):t.click(1,1)
        t.executor.interaction.click.assert_not_called()

    def test_release_bypasses_disabled_executor(self):
        t=self.task(); t._held_keys={'w'}; t._held_mouse={'left'}
        t.executor.check_enabled.side_effect=TaskDisabledException()
        t.validate_key=Mock(side_effect=lambda key:key)
        t._release()
        t.executor.interaction.send_key_up.assert_called_once_with('w')
        t.executor.interaction.mouse_up.assert_called_once_with(key='left')
        self.assertFalse(t._held_keys or t._held_mouse)

    def test_fight_death_and_unknown_do_not_leave(self):
        for error in (CharDeadException(),CombatStateUnknown()):
            t=self.task(); t._release=Mock(); t.combat_once=Mock(side_effect=error)
            t._wait=Mock(return_value='combat')
            with self.assertRaises(type(error)):t._fight()
            self.assertIsNone(t._battle_deadline)
            self.assertTrue(t.skip_combat_check)

    def test_fight_completion_interrupt_is_success(self):
        t=self.task(); t._release=Mock(); t.combat_once=Mock(side_effect=TrialFinished())
        t._fight()
        self.assertIsNone(t._battle_deadline)

    def test_normalized_slots_at_1080p_and_1440p(self):
        for width,height in ((1920,1080),(2560,1440)):
            t=self.task(); t._drag_strip=Mock();t._wait=Mock();t.click=Mock();t.sleep=Mock();t._state=Mock()
            with patch.object(CharacterTrialTask,'width',property(lambda self:width)), \
                    patch.object(CharacterTrialTask,'height',property(lambda self:height)):
                for target,x in enumerate((.324,.410,.495,.581,.650,.650)):
                    t._select(target)
                    t.click.assert_called_with(round(width*x),round(height*.905))
                    t._drag_strip.assert_called_with('right' if target==5 else 'left')
            self.assertEqual(t._state.call_count,6)

    def test_configured_roster_count(self):
        t=self.task()
        self.assertEqual(t._scan(),list(range(5)))
        t.config['试用人数']='6人'
        self.assertEqual(t._scan(),list(range(6)))
        t.config['试用人数']='7人'
        with self.assertRaises(ValueError):t._scan()

    def test_drag_scales_and_releases_on_stop(self):
        t=self.task(); t._wait=Mock();t.swipe=Mock(side_effect=TaskDisabledException())
        with patch.object(CharacterTrialTask,'width',property(lambda self:1920)), \
                patch.object(CharacterTrialTask,'height',property(lambda self:1080)):
            with self.assertRaises(TaskDisabledException):t._drag_strip('right')
        t.swipe.assert_called_once_with(1277,977,549,977,duration=.8,after_sleep=.5)
        t.executor.interaction.mouse_up.assert_called_once_with(key='left')
        self.assertFalse(t._held_mouse)

    def test_unknown_state_is_not_skipped(self):
        t=self.task();t._drag_strip=Mock();t._wait=Mock();t._trial_point=Mock(return_value=(100,100))
        t.click=Mock();t.sleep=Mock();t._state=Mock(side_effect=TrialTimeout('unknown'))
        with self.assertRaises(TrialTimeout):t._select(4)

    def test_enter_clears_old_party_before_click(self):
        t=self.task(); t.chars=[object()]; t.reset_to_false=Mock()
        t._button=Mock(return_value=box('前往试用'))
        t.click=Mock(side_effect=lambda *a:self.assertEqual(t.chars,[]))
        t._wait_trial_map=Mock()
        t._enter(); self.assertEqual(t.chars,[])

    def test_fallback_only_replaces_basechar(self):
        t=self.task(); old=BaseChar(t,0,char_name='unknown'); old.is_current_char=True
        known=object(); t.chars=[old,known]
        with patch.object(BaseCombatTask,'load_chars',return_value=True):t.load_chars()
        self.assertIsInstance(t.chars[0],TrialGenericChar)
        self.assertTrue(t.chars[0].is_current_char)
        self.assertIs(t.chars[1],known)

    def test_generic_attacks_and_does_not_switch_solo(self):
        for count in (1,3):
            char=object.__new__(TrialGenericChar); char.task=SimpleNamespace(chars=[None]*count)
            for method in ('wait_intro','click_echo','click_liberation','click_resonance',
                           'continues_normal_attack','heavy_attack','switch_next_char'):
                setattr(char,method,Mock())
            char.is_forte_full=Mock(return_value=True); char.do_perform()
            char.continues_normal_attack.assert_called_once()
            self.assertEqual(char.switch_next_char.call_count,int(count>1))

    def test_run_final_recheck_failure_never_reports_complete(self):
        t=self.task(); t._open=Mock(); t._scan=Mock(return_value=[object()])
        t._process=Mock(return_value='already_complete'); t._select=Mock()
        t._state=Mock(return_value='pending'); t._release=Mock()
        with patch.object(WWOneTimeTask,'run'),self.assertRaises(RuntimeError):t.run()
        self.assertFalse(t.last_result['complete'])

    def test_permanent_activity_navigation(self):
        t=self.task()
        self.assertEqual(classify_task(t),'tasks')
        self.assertEqual(task_category(t),'活动')
        self.assertEqual(t.activity_category,'常驻活动')


if __name__=='__main__':
    unittest.main()
