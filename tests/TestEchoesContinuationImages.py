import unittest
import gettext
from pathlib import Path
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.EchoesRemainTask import EchoesRemainTask
from src.task.echoes_support import selected_support, challenge_prompt_state
from src.task.character_trial import start_prompt


class TestEchoesContinuationImages(TaskTestCase):
    task_class=EchoesRemainTask
    config=config

    def page(self,name):
        self.set_image(f'tests/fixtures/echoes_remain/continuation/{name}.png')
        return self.task.frame

    def test_support_selection_and_type(self):
        f=self.page('support')
        self.assertTrue(self.task._support_page(f))
        self.assertTrue(selected_support(f,0))
        self.assertFalse(selected_support(f,1))
        self.assertIsNotNone(self.task._button(f,(.86,.10,.97,.18),'攻击型'))

    def test_start_with_ocr_missing_f(self):
        f=self.page('start_f_icon')
        boxes=self.task.ocr(.60,.43,.86,.61,frame=f)
        boxes=[b for b in boxes if b.name != 'F']
        state=challenge_prompt_state(f,boxes)
        self.assertTrue(state['text'],state)
        self.assertFalse(state['key_ocr'],state)
        self.assertTrue(state['key_template'],state)

    def test_actual_failed_settlement(self):
        f=self.page('failed_retry')
        self.assertEqual(self.task._settlement(f),'failed')
        self.assertIsNotNone(self.task._button(f,(.54,.79,.73,.90),'重新挑战'))

    def test_next_stage_zero_score_is_pending(self):
        f=self.page('zero_score')
        self.task.last_result={}
        stage=self.task._stage_page(f)
        self.assertTrue(stage and stage.endswith('浅梦'),stage)
        self.assertTrue(self.task._selected_stage_pending(f,stage))

    def test_lynae_identity_translates_and_matches_formation(self):
        self.task.tr=gettext.translation('ok',localedir='i18n',languages=['zh_CN']).gettext
        self.task.last_result={'stage':'堕梦神躯·浅梦'}
        members=self.task._identify_team(self.page('lynae_roster'))
        self.assertEqual([m['name'] for m in members],['爱弥斯','莫宁','琳奈'])
        self.assertEqual([m['role'] for m in members],['输出','治疗','辅助'])
        f=self.page('lynae_formation')
        self.assertTrue(self.task._verify_team_names(f))
        self.task.last_result['members'].reverse()
        self.assertFalse(self.task._verify_team_names(f))

    def test_control_support_failure_screenshot(self):
        f=self.page('control_selected')
        state=self.task._support_selection_state(f,1)
        self.assertTrue(all(state[key] for key in ('page','category','selected')),state)
        self.assertIsNotNone(self.task._button(f,(.76,.86,.95,.96),'装配'))
        self.assertFalse(self.task._support_selection_state(f,0)['category'])
        self.assertFalse(self.task._support_selection_state(f,3)['selected'])

    def test_selected_roster_identity_order_and_activity_role(self):
        f=self.page('roster')
        self.task.last_result={}
        # TaskTestCase has no application translator; production uses the app catalog.
        self.task.tr=lambda name: {'Suisui':'穗穗','Yangyang: Xuanling':'秧秧·玄翎','Chisa':'千咲'}.get(name,name)
        members=self.task._identify_team(f)
        self.assertEqual([m['identity'] for m in members],['char_suisui','yangyang_sp','char_chisa'])
        self.assertEqual([m['name'] for m in members],['穗穗','秧秧·玄翎','千咲'])
        self.assertEqual([m['role'] for m in members],['治疗','输出','辅助'])

    def test_formation_names_are_in_real_order(self):
        f=self.page('equipped')
        self.task.last_result={'stage':'溺梦魔影·浅梦','members':[
            {'name':'穗穗'},{'name':'秧秧·玄翎'},{'name':'千咲'}]}
        self.assertTrue(self.task._verify_team_names(f))
        self.task.last_result['members'].reverse()
        self.assertFalse(self.task._verify_team_names(f))

    def test_start_prompt_and_settlement(self):
        f=self.page('map')
        self.assertFalse(start_prompt(self.task.ocr(.60,.43,.86,.61,frame=f),self.task.height))
        f=self.page('start')
        self.assertTrue(start_prompt(self.task.ocr(.60,.43,.86,.61,frame=f),self.task.height))
        self.assertIsNone(self.task._settlement(f))
        f=self.page('result')
        self.assertEqual(self.task._settlement(f),'success')

    def test_next_difficulty_pending(self):
        f=self.page('next')
        self.assertEqual(self.task._stage_page(f),'溺梦魔影·深梦')
        self.assertTrue(self.task._selected_stage_pending(f,'溺梦魔影·深梦'))
        self.assertFalse(self.task._selected_stage_pending(f,'溺梦魔影·浅梦'))


if __name__=='__main__':unittest.main()
