import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch
from types import SimpleNamespace
from ok import TaskDisabledException
import cv2

from src.task.echoes_support import choose_support, unlocked, equipped, enabled_start, challenge_prompt_state
from src.task.echoes_continuation import activity_role, event_echo
from src.task.EchoesRemainTask import EchoesRemainTask, canonical_stage
from src.char.BaseChar import CharType

ROOT = Path('tests/fixtures/echoes_remain/continuation')


class TestEchoesContinuation(unittest.TestCase):
    def test_stage_separator_normalization_preserves_identity(self):
        for text in ('堕梦神躯··浅梦','堕梦神躯・浅梦',' 堕梦神躯 · · 浅梦 '):
            self.assertEqual(canonical_stage(text),'堕梦神躯·浅梦')
        task=Mock(spec=EchoesRemainTask)
        task._stage_page.return_value='堕梦神躯·浅梦'
        self.assertIsNotNone(EchoesRemainTask._single_button(task,None,'堕梦神躯··浅梦'))
        for actual in ('堕梦神躯·深梦','溺梦魔影·浅梦'):
            task._stage_page.return_value=actual
            with self.assertRaisesRegex(RuntimeError,'关卡已变化'):
                EchoesRemainTask._single_button(task,None,'堕梦神躯·浅梦')

    def test_zero_score_pending_and_unreadable_score_rejected(self):
        task=Mock(spec=EchoesRemainTask)
        task.height=1152
        label=SimpleNamespace(name='浅梦',y=280)
        for text,expected in [('最高分数：0',True),('最高分数：1241',False),('最高分数：1,241',False)]:
            task.ocr.side_effect=[[label],[SimpleNamespace(name=text)]]
            self.assertEqual(EchoesRemainTask._selected_stage_pending(task,None,'堕梦神躯·浅梦'),expected)
        task.ocr.side_effect=[[label],[SimpleNamespace(name='最高分数：')]]
        with self.assertRaisesRegex(RuntimeError,'无法读取'):
            EchoesRemainTask._selected_stage_pending(task,None,'堕梦神躯·浅梦')

    def test_f_icon_resolutions_and_missing_or_misaligned_key(self):
        original=cv2.imread(str(ROOT/'start_f_icon.png'))
        for height in (720,1080,1440,2160):
            frame=cv2.resize(original,(height*16//9,height))
            scale=height/1152
            label=SimpleNamespace(name='开启挑战',x=1423*scale,y=580*scale,height=29*scale)
            self.assertTrue(challenge_prompt_state(frame,[label])['key_template'],height)
            self.assertFalse(challenge_prompt_state(frame,[])['key_template'])
            missing=frame.copy()
            missing[int(575*scale):int(617*scale),int(1290*scale):int(1340*scale)]=0
            self.assertFalse(challenge_prompt_state(missing,[label])['key_template'])
            label.y += 100*scale
            self.assertFalse(challenge_prompt_state(frame,[label])['key_template'])

    def test_support_category_alias_is_exact_and_local(self):
        task=EchoesRemainTask.__new__(EchoesRemainTask)
        task._support_page=Mock(return_value=True)
        with patch('src.task.echoes_continuation.selected_support',return_value=True):
            for text, expected in [('控制型',True),('控製型',True),(' 控 製 型 ',True),
                                   ('攻击型',False),('控制',False),('控制型未解锁',False)]:
                task.ocr=Mock(return_value=[SimpleNamespace(name=text)])
                self.assertEqual(task._support_selection_state(None,1)['category'],expected,text)
            task.ocr=Mock(return_value=[])
            self.assertFalse(task._support_selection_state(None,1)['category'])
            task.ocr=Mock(return_value=[SimpleNamespace(name='控制型'),SimpleNamespace(name='控製型')])
            self.assertFalse(task._support_selection_state(None,1)['category'])

    def test_support_preferences_and_locked_exclusion(self):
        for height in (720, 1080, 1440, 2160):
            frame = cv2.resize(cv2.imread(str(ROOT/'support.png')), (height*16//9, height))
            self.assertEqual([unlocked(frame,i) for i in range(9)], [True]*7+[False]*2)
            self.assertEqual(choose_support(frame, '输出'), 0)
            self.assertEqual(choose_support(frame, '治疗'), 6)
            self.assertEqual(choose_support(frame, '辅助'), 1)

    def test_actual_equipment_and_disabled_button(self):
        for height in (720,1080,1440,2160):
            full = cv2.resize(cv2.imread(str(ROOT/'equipped.png')), (height*16//9,height))
            empty = cv2.resize(cv2.imread(str(ROOT/'empty.png')), (height*16//9,height))
            self.assertTrue(enabled_start(full))
            self.assertFalse(enabled_start(empty))
            for slot, echo in enumerate((6,0,1)):
                self.assertTrue(equipped(full,slot,echo), (height,slot))
                self.assertFalse(equipped(empty,slot,echo))

    def test_role_override_is_activity_only(self):
        self.assertEqual(activity_role('char_suisui'), '治疗')
        self.assertEqual(activity_role('yangyang_sp'), '输出')
        self.assertEqual(activity_role('char_chisa'), '辅助')
        with self.assertRaises(RuntimeError): activity_role('not_registered')

    def test_event_echo_uses_single_press_without_native_duration(self):
        char=Mock();char.last_echo=0;char.echo_available.return_value=True
        self.assertTrue(event_echo(char,duration=30))
        char.send_echo_key.assert_called_once()
        char.record_echo_use.assert_called_once()

    def test_failure_exits_once_without_retry(self):
        task=Mock(spec=EchoesRemainTask)
        task.last_result={'stage':'溺梦魔影·浅梦'}
        task._identify_team.return_value=[{'confidence':1}]*3
        task._challenge_event.return_value='failed'
        EchoesRemainTask._continue_event(task)
        task._challenge_event.assert_called_once()
        task._record_stage_result.assert_called_once()
        task._open_quick.assert_not_called()
        self.assertEqual(task.last_result['phase'],'challenge_failed')

    def test_success_advances_to_next_difficulty_then_stops_on_failure(self):
        task=Mock(spec=EchoesRemainTask)
        task.last_result={'stage':'溺梦魔影·浅梦'}
        task._identify_team.return_value=[{'confidence':1}]*3
        task._challenge_event.side_effect=['success','failed']
        task._stage_page.return_value='溺梦魔影·深梦'
        task._selected_stage_pending.return_value=True
        EchoesRemainTask._continue_event(task)
        self.assertEqual(task._challenge_event.call_count,2)
        task._open_quick.assert_called_once()
        self.assertEqual(task.last_result['rounds'],[
            {'stage':'溺梦魔影·浅梦','outcome':'success'},
            {'stage':'溺梦魔影·深梦','outcome':'failed'}])

    def test_same_stage_pending_after_success_does_not_replay(self):
        task=Mock(spec=EchoesRemainTask)
        task.last_result={'stage':'溺梦魔影·浅梦'}
        task._identify_team.return_value=[{'confidence':1}]*3
        task._challenge_event.return_value='success'
        task._stage_page.return_value='溺梦魔影·浅梦'
        task._selected_stage_pending.return_value=True
        with self.assertRaisesRegex(RuntimeError,'未推进'):
            EchoesRemainTask._continue_event(task)
        task._challenge_event.assert_called_once()

    def test_stop_propagates_without_recording_success(self):
        task=Mock(spec=EchoesRemainTask)
        task.last_result={'stage':'溺梦魔影·浅梦'}
        task._choose.side_effect=TaskDisabledException('stop')
        with self.assertRaises(TaskDisabledException): EchoesRemainTask._continue_event(task)
        task._record_stage_result.assert_not_called()
        task._challenge_event.assert_not_called()

    def test_newly_unlocked_attack_precedes_original(self):
        with patch('src.task.echoes_support.unlocked',side_effect=lambda f,i:i in (0,8)):
            self.assertEqual(choose_support(None,'输出'),8)
        with patch('src.task.echoes_support.unlocked',return_value=False):
            self.assertIsNone(choose_support(None,'输出'))

    def test_unknown_settlement_never_equals_success(self):
        task=Mock(spec=EchoesRemainTask)
        task._button.side_effect=lambda f,r,text: object() if text=='退出副本' else None
        self.assertIsNone(EchoesRemainTask._settlement(task,object()))

    def test_equipment_follows_real_roles_and_allows_duplicate_support(self):
        task=Mock(spec=EchoesRemainTask)
        task.last_result={'stage':'test','members':[
            {'name':'a','role':'辅助'},{'name':'b','role':'输出'},{'name':'c','role':'辅助'}]}
        with patch('src.task.echoes_continuation.choose_support',side_effect=[1,0,1]):
            EchoesRemainTask._equip_supports(task)
        self.assertEqual(task.last_result['supports'],[1,0,1])
        self.assertEqual(task.navigate_ui.call_count,6)

    def test_combat_slot_identity_uses_verified_order(self):
        task=Mock(spec=EchoesRemainTask)
        task.in_team.return_value=(True,1,3)
        task.last_result={'members':[{'identity':name,'confidence':1} for name in ('a','b','c')]}
        classes=[Mock(return_value=Mock()) for _ in range(3)]
        info={n:{'cls':cls,'canonical_name':n,'char_type':CharType.MAIN_DPS}
              for n,cls in zip(('a','b','c'),classes)}
        with patch('src.task.echoes_continuation.char_dict',info), \
             patch('src.task.echoes_continuation._apply_char_config'), \
             patch('src.task.echoes_continuation._get_buff_time',return_value=0):
            self.assertTrue(EchoesRemainTask.load_chars(task))
        self.assertEqual([c.call_args.args[1] for c in classes],[0,1,2])
        self.assertEqual([c.is_current_char for c in task.chars],[False,True,False])

    def test_complete_requires_all_eight_game_counts(self):
        task=Mock(spec=EchoesRemainTask);task.last_result={};task.height=1000
        roman=('I','II','III','IV','V','VI','VII','VIII')
        boxes=[]
        for i,n in enumerate(roman):
            boxes += [SimpleNamespace(name=n,x=50,y=100+i*80),
                      SimpleNamespace(name='2/2',x=100,y=110+i*80)]
        task.ocr.return_value=boxes
        EchoesRemainTask._audit_completion(task)
        self.assertTrue(task.last_result['activity_complete'])
        task.last_result={};boxes[-1].name='1/2'
        EchoesRemainTask._audit_completion(task)
        self.assertFalse(task.last_result['activity_complete'])

    def test_partial_equipment_never_allows_start(self):
        frame=cv2.imread(str(ROOT/'equipped.png'))
        empty=cv2.imread(str(ROOT/'empty.png'))
        frame[830:912,950:1032]=empty[830:912,950:1032]
        self.assertFalse(all(equipped(frame,i,e) for i,e in enumerate((6,0,1))))


if __name__=='__main__':unittest.main()
