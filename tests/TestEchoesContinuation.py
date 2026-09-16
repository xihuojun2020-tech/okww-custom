import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch
from types import SimpleNamespace
from ok import TaskDisabledException
import cv2

from src.task.echoes_support import choose_support, unlocked, support_slot_state, enabled_start, challenge_prompt_state
from src.task.echoes_continuation import activity_role, event_echo, character_name_key
from src.task.EchoesRemainTask import EchoesRemainTask, canonical_stage
from src.char.BaseChar import CharType

ROOT = Path('tests/fixtures/echoes_remain/continuation')


class TestEchoesContinuation(unittest.TestCase):
    def test_lucilla_alias_is_exact_and_preserves_name_guards(self):
        import gettext
        self.assertEqual(character_name_key('洛瑟拉'), '洛瑟菈')
        for text in ('洛瑟', '洛瑟菈未知', '洛可可'):
            self.assertEqual(character_name_key(text), text)
        task = Mock(spec=EchoesRemainTask)
        task.tr = gettext.translation('ok', 'i18n', ['zh_CN']).gettext
        task.last_result = {'stage': '燃核兽形·浅梦'}
        task._formation_for_stage.return_value = True
        for names, confidence in ((('洛瑟拉', '绯雪', '千咲'), .79),
                                  (('洛瑟拉', '洛瑟菈', '千咲'), .99),
                                  (('未知角色', '绯雪', '千咲'), .99)):
            task.ocr.side_effect = [[SimpleNamespace(name=n, confidence=confidence)] for n in names]
            self.assertIsNone(EchoesRemainTask._read_formation_members(task, None))

    def test_confirm_names_requires_consecutive_matching_reads(self):
        task=Mock(spec=EchoesRemainTask)
        task.last_result={}
        a=[dict(identity='a',order=1,name='a',role='输出')]
        b=[dict(identity='b',order=1,name='b',role='输出')]
        task._read_formation_members.side_effect=[a,None,a,b,b]
        def wait(probe,reason):
            for _ in range(4):
                self.assertIsNone(probe(None))
            return probe(None)
        task._wait.side_effect=wait
        EchoesRemainTask._confirm_formation_members(task)
        self.assertEqual(task.last_result['members'],b)

    def test_formation_name_mapping_handles_luhesi_and_unknown(self):
        import gettext
        task=Mock(spec=EchoesRemainTask)
        task.tr=gettext.translation('ok','i18n',['zh_CN']).gettext
        task.last_result={'stage':'孤寂遗魂·浅梦'}
        task._formation_for_stage.return_value=True
        task.ocr.side_effect=[[SimpleNamespace(name=n,confidence=.99)] for n in ('爱弥斯','陆赫斯','莫宁')]
        members=EchoesRemainTask._read_formation_members(task,None)
        self.assertEqual([m['identity'] for m in members],['char_aemeath','char_luhesi','char_moning'])
        for text,conf in [('未知角色',.99),('陆赫斯',.5)]:
            task.ocr.side_effect=[[SimpleNamespace(name=text,confidence=conf)]]
            self.assertIsNone(EchoesRemainTask._read_formation_members(task,None))

    def retry_task(self, outcomes):
        task=Mock(spec=EchoesRemainTask)
        task.config={'Event Max Attempts':3}
        task.last_result={'stage':'堕梦神躯·浅梦'}
        task._fight_event.side_effect=outcomes
        task.ocr.return_value=[]
        task._formation_for_stage.return_value=False
        return task

    def test_retry_failure_then_success(self):
        task=self.retry_task(['failed','success'])
        self.assertEqual(EchoesRemainTask._challenge_event(task),'success')
        self.assertEqual(task._fight_event.call_count,2)
        self.assertEqual([c.args[0] for c in task.navigate_ui.call_args_list],
                         ['重新挑战若梦副本','退出若梦副本'])
        self.assertEqual(len(task.last_result['attempts']),2)

    def test_retry_limit_and_cancel(self):
        task=self.retry_task(['failed']*3)
        self.assertEqual(EchoesRemainTask._challenge_event(task),'failed')
        self.assertEqual(task._fight_event.call_count,3)
        self.assertEqual(task.navigate_ui.call_count,3)
        task=self.retry_task([TaskDisabledException('stop')])
        with self.assertRaises(TaskDisabledException):
            EchoesRemainTask._challenge_event(task)
        task.navigate_ui.assert_not_called()

    def test_retry_formation_reuses_equipment_verification(self):
        task=self.retry_task(['failed','success'])
        task._formation_for_stage.return_value=True
        EchoesRemainTask._challenge_event(task)
        task._equip_supports.assert_called_once()
        self.assertEqual(task._enter_event_map.call_count,2)

    def test_recovery_requires_positive_health(self):
        task=Mock(spec=EchoesRemainTask)
        task._settlement.return_value=None
        task.in_team.return_value=(True,1,3)
        task.ocr.side_effect=[[SimpleNamespace(name='0/100')],[SimpleNamespace(name='100/100')]]
        EchoesRemainTask._recover_event_character(task)
        task.send_key.assert_called_once()
        self.assertEqual(task.chars,[])

    def test_death_exception_reaches_recovery_before_generic_end(self):
        from src.task.BaseCombatTask import CharDeadException
        task=Mock(spec=EchoesRemainTask)
        task.combat_once.side_effect=CharDeadException('dead')
        task._wait.return_value='success'
        self.assertEqual(EchoesRemainTask._fight_event(task),'success')
        task._recover_event_character.assert_called_once()

    def test_unknown_failure_does_not_retry(self):
        task=self.retry_task([RuntimeError('unknown page')])
        with self.assertRaisesRegex(RuntimeError,'unknown page'):
            EchoesRemainTask._challenge_event(task)
        task.navigate_ui.assert_not_called()

    def test_recovery_timeout_stops(self):
        task=Mock(spec=EchoesRemainTask)
        with patch('src.task.echoes_continuation.time.monotonic',side_effect=[0,26]):
            with self.assertRaisesRegex(RuntimeError,'25秒'):
                EchoesRemainTask._recover_event_character(task)

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
            for role in ('输出', '治疗', '辅助'):
                self.assertEqual(choose_support(frame, role), 5)

    def test_gold_mask_priority_and_original_role_fallbacks(self):
        for role, order in {'输出': (7,8,0), '治疗': (6,2), '辅助': (1,3,4,5)}.items():
            with self.subTest(role=role):
                with patch('src.task.echoes_support.unlocked', return_value=True) as available:
                    self.assertEqual(choose_support(None, role), 5)
                    available.assert_called_once_with(None, 5)
                fallback = [i for i in order if i != 5]
                for offset, expected in enumerate(fallback):
                    with patch('src.task.echoes_support.unlocked',
                               side_effect=lambda f,i,allowed=fallback[offset:]: i in allowed):
                        self.assertEqual(choose_support(None, role), expected)
                with patch('src.task.echoes_support.unlocked', return_value=False):
                    self.assertIsNone(choose_support(None, role))

    def test_actual_equipment_and_disabled_button(self):
        for height in (720,1080,1440,2160):
            full = cv2.resize(cv2.imread(str(ROOT/'equipped.png')), (height*16//9,height))
            empty = cv2.resize(cv2.imread(str(ROOT/'empty.png')), (height*16//9,height))
            self.assertTrue(enabled_start(full))
            self.assertFalse(enabled_start(empty))
            for slot, echo in enumerate((6,0,1)):
                self.assertEqual(support_slot_state(full,slot), 'occupied', (height,slot))
                self.assertEqual(support_slot_state(empty,slot), 'empty')

    def test_actual_second_equipment_and_empty_third_slot(self):
        for name in ('equipment_failure_1', 'equipment_failure_2', 'equipment_failure_3'):
            original = cv2.imread(str(ROOT / f'{name}.png'))
            for height in (720, 1080, 1440, 2160):
                frame = cv2.resize(original, (height*16//9, height))
                with self.subTest(image=name, height=height):
                    self.assertEqual([support_slot_state(frame, slot) for slot in range(3)],
                                     ['occupied', 'occupied', 'empty'])
                    self.assertFalse(enabled_start(frame))

    def test_actual_second_equipment_verification_reaches_third_slot(self):
        task = Mock(spec=EchoesRemainTask)
        frame = cv2.imread(str(ROOT / 'equipment_failure_3.png'))
        # Synthetic final frame: copy the already verified first support into slot 3.
        from src.task.echoes_support import normalized
        final = normalized(frame).copy()
        final[830:912,1548:1630] = final[830:912,351:433]
        final[1040:1075,1660:1850] = 255
        task.last_result = {'stage':'test', 'members':[
            {'name':'洛瑟菈','role':'辅助'}, {'name':'绯雪','role':'输出'}, {'name':'千咲','role':'辅助'}]}
        task._verify_team_names.return_value = True
        task._equipped_slots.side_effect = lambda f, slots: EchoesRemainTask._equipped_slots(task, f, slots)
        task._wait_support_choice.side_effect = [1, 7, 1]
        task._support_selection_state.return_value = dict(page=True, category=True, selected=True)
        task._wait.side_effect = lambda probe, reason: probe(final)
        visited = []
        def navigate(label, source, target, **kwargs):
            if label == '装配支援声骸':
                slot = kwargs['identity'][1]
                self.assertTrue(target(final if slot == 2 else frame))
                visited.append(slot)
            return frame
        task.navigate_ui.side_effect = navigate
        EchoesRemainTask._equip_supports(task)
        self.assertEqual(visited, [0, 1, 2])
        self.assertEqual(task.last_result['supports'], [1, 7, 1])

    def test_missing_plus_without_visible_artwork_is_unknown(self):
        import numpy as np
        for value in (0, 80, 255):
            frame = np.full((1152, 2048, 3), value, np.uint8)
            self.assertEqual([support_slot_state(frame, i) for i in range(3)], ['unknown']*3)
        frame = cv2.imread(str(ROOT/'empty.png'))
        frame[845:900,365:420] = frame[845,365]
        self.assertEqual(support_slot_state(frame, 0), 'unknown')

    def test_wrong_page_and_empty_previous_slot_block_confirmation(self):
        task = Mock(spec=EchoesRemainTask)
        task.last_result = {}
        frame = cv2.imread(str(ROOT/'equipment_failure_3.png'))
        task._verify_team_names.return_value = False
        self.assertFalse(EchoesRemainTask._equipped_slots(task, frame, range(2)))
        task._verify_team_names.return_value = True
        self.assertTrue(EchoesRemainTask._equipped_slots(task, frame, range(2)))
        self.assertFalse(EchoesRemainTask._equipped_slots(task, frame, range(3)))
        self.assertEqual(task.last_result['support_slot_observation']['slots'],
                         ['occupied', 'occupied', 'empty'])

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
        task._identify_team.assert_not_called()
        task._confirm_formation_members.assert_called_once()
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
        task._wait_support_choice.side_effect=[1,0,1]
        with patch('src.task.echoes_continuation.choose_support',side_effect=[1,0,1]):
            EchoesRemainTask._equip_supports(task)
        self.assertEqual(task.last_result['supports'],[1,0,1])
        self.assertEqual(task.navigate_ui.call_count,6)

    def test_support_choice_waits_for_repeated_valid_frame(self):
        task=Mock(spec=EchoesRemainTask)
        task._support_page.return_value=True
        def wait(probe,reason,timeout):
            for _ in range(4):
                self.assertIsNone(probe(None))
            return probe(None)
        task._wait.side_effect=wait
        with patch('src.task.echoes_continuation.choose_support',side_effect=[None,1,None,0,0]):
            self.assertEqual(EchoesRemainTask._wait_support_choice(task,{'name':'test','role':'输出'}),0)

    def test_real_support_flash_then_normal_page(self):
        task=Mock(spec=EchoesRemainTask)
        task._support_page.return_value=True
        flash=cv2.imread(str(ROOT/'support_flash.png'))
        normal=cv2.imread(str(ROOT/'support.png'))
        self.assertIsNone(choose_support(flash,'辅助'))
        def wait(probe,reason,timeout):
            self.assertIsNone(probe(flash))
            self.assertIsNone(probe(normal))
            return probe(normal)
        task._wait.side_effect=wait
        self.assertEqual(EchoesRemainTask._wait_support_choice(task,{'name':'达妮娅','role':'辅助'}),5)

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
        self.assertFalse(all(support_slot_state(frame,i) == 'occupied' for i in range(3)))


if __name__=='__main__':unittest.main()
