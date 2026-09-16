import unittest
from types import SimpleNamespace, MethodType
from unittest.mock import Mock, patch

from src.task.BaseWWTask import BaseWWTask
from src.task.DailyTask import DailyTask, DailyActivityIncomplete
from src.task.NightmareNestTask import NightmareNestTask
from src.task.daily_observation import resource_values, objective_progress
from src.task.daily_reserve_policy import DailyReservePolicy


class TestDailyOutcomeRecovery(unittest.TestCase):
    def box(self, name, x, y=0, width=30, height=20):
        return SimpleNamespace(name=name, x=x, y=y, width=width, height=height)

    def test_resource_parser_binds_positions_and_rejects_ambiguity(self):
        boxes=[self.box('80 ／ 240',730),self.box('159',540),self.box('80',900)]
        self.assertEqual(resource_values(boxes,1000),(80,159,239))
        self.assertEqual(resource_values(boxes+[self.box('160',590)],1000),(-1,-1,-1))
        self.assertEqual(resource_values([self.box('80',730),self.box('159',540)],1000),(-1,-1,-1))

    def test_objective_neighbour_and_unknown_do_not_mean_complete(self):
        boxes=[self.box('获得任意1个声骸',300,200,240),self.box('0/1',300,235),self.box('1/1',300,300)]
        self.assertEqual(objective_progress(boxes,'声骸'),(0,1))
        self.assertIsNone(objective_progress(boxes[1:],'声骸'))

    def test_budget_uses_remaining_objective_not_another_180(self):
        for used, ready, expected in ((160,False,40),(180,False,0),(None,False,0),
                                       (0,None,0),(0,True,0),(0,False,200)):
            self.assertEqual(BaseWWTask.daily_stamina_budget(ready,40,used),expected)

    def reserve_task(self, ready=False, amount=32):
        policy=DailyReservePolicy('synthetic')
        policy.observe(ready)
        task=Mock(spec=BaseWWTask)
        task.executor=SimpleNamespace(_daily_reserve_policy=policy)
        task.get_verified_stamina.side_effect=[(8,167,175),(40,135,175)]
        task.ocr.side_effect=[[self.box('167',540)],
                             [self.box('备用结晶波片',0),self.box(f'转化数量：{amount}',0)],
                             [self.box('确认',0)]]
        return task,policy

    def test_precombat_exact_shortfall_verified_before_return(self):
        task,policy=self.reserve_task()
        self.assertEqual(BaseWWTask.prepare_daily_reserve(task,40,40),(40,135,175))
        self.assertEqual(task.click.call_count,2)
        self.assertFalse(policy.pending_conversion)

    def test_precombat_full_unknown_stale_or_insufficient_budget_cannot_convert(self):
        for ready,budget,stale in ((True,40,False),(None,40,False),(False,0,False),(False,40,True)):
            task,policy=self.reserve_task(ready)
            if stale:policy.observed_at-=60
            self.assertEqual(BaseWWTask.prepare_daily_reserve(task,40,budget),(8,167,175))
            task.click.assert_not_called()

    def test_batch_conversion_and_uncertain_result_never_repeat(self):
        task,policy=self.reserve_task(amount=167)
        self.assertEqual(BaseWWTask.prepare_daily_reserve(task,40,40),(8,167,175))
        self.assertEqual(task.click.call_count,1)  # resource entry only, no confirm
        task,policy=self.reserve_task()
        task.get_verified_stamina.side_effect=[(8,167,175),(8,167,175),(8,167,175)]
        with self.assertRaises(RuntimeError):BaseWWTask.prepare_daily_reserve(task,40,40)
        self.assertTrue(policy.pending_conversion)
        with self.assertRaises(RuntimeError):BaseWWTask.prepare_daily_reserve(task,40,40)
        self.assertEqual(task.click.call_count,2)

    def recovery_task(self, progress, ready=False):
        task=Mock(spec=DailyTask)
        task.support_tasks=['Tacet Suppression','Forgery Challenge','Simulation Challenge']
        task._profile_get.side_effect=lambda key,default=None:'Forgery Challenge' if key=='Which to Farm' else default
        task._daily_objective.side_effect=progress
        task.open_daily.return_value=(None,ready)
        return task

    def test_local_stamina_repair_continues_only_on_progress_and_is_bounded(self):
        task=self.recovery_task([(100,180),(140,180),(140,180),(180,180)])
        task.open_daily.side_effect=[(100,False),(140,False),(140,False),(180,True)]
        self.assertTrue(DailyTask._complete_missing_daily_stamina(task,False,{}))
        farm=task.get_task_by_class.return_value.farm_forgery
        self.assertEqual([c.kwargs['used_stamina'] for c in farm.call_args_list],[100,140])
        self.assertEqual(task._guard_bound_profile_identity.call_count,2)

    def test_local_stamina_no_progress_unknown_or_full_stops(self):
        for progress,calls in (([(160,180),(160,180)],1),([None],0),([(180,180)],0)):
            task=self.recovery_task(progress)
            self.assertFalse(DailyTask._complete_missing_daily_stamina(task,False,{}))
            self.assertEqual(task.get_task_by_class.call_count,calls)
        task=self.recovery_task([])
        self.assertTrue(DailyTask._complete_missing_daily_stamina(task,True,{}))
        task._daily_objective.assert_not_called()

    def test_echo_zero_and_unknown_never_verify(self):
        for progress in ((0,1),None):
            task=Mock(spec=DailyTask);task._daily_objective.return_value=progress
            with self.assertRaises(DailyActivityIncomplete):DailyTask._verify_daily_echo(task)

    def test_capture_candidate_does_not_skip_next_target_without_result(self):
        task=Mock(spec=NightmareNestTask)
        task._unreachable_nests=set()
        task.get_nest_to_go.side_effect=['one','two',None]
        task.combat_nest.side_effect=lambda nest:setattr(task,'_capture_success',True)
        verify=Mock(side_effect=[False,True])
        with patch('src.task.NightmareNestTask.WWOneTimeTask.run'):
            NightmareNestTask.run_capture_mode(task,verify_capture=verify)
        self.assertEqual(task.combat_nest.call_count,2)
        self.assertEqual(verify.call_count,2)

    def daily_flow(self):
        task=DailyTask.__new__(DailyTask)
        task.integrity_service=None
        task._verified_profile_id='synthetic'
        task._runtime_overrides={}
        task.support_tasks=['Tacet Suppression','Forgery Challenge','Simulation Challenge']
        flags={'Which to Farm':'Forgery Challenge','Farm Nightmare Nest for Daily Echo':True,
               'Screenshot After Daily Task':False,'Record After Daily Task':False,
               'Logout PC After Daily Task':False}
        task._profile_get=lambda key,default=None:flags.get(key,default)
        for name in ('_publish_daily_stage','_ensure_run_account_confirmation','validate_daily_tasks',
                     'log_info','log_warning','log_error','ensure_main','ensure_daily_profiles',
                     '_sync_sequence_options','sleep','record_last_completed','screenshot',
                     'claim_daily','claim_mail','claim_battle_pass','run_weekly_tasks',
                     '_guard_bound_profile_identity','info_set','_notify_incomplete_daily_activity'):
            setattr(task,name,Mock())
        task._readonly_profile_config=Mock(return_value={})
        task.get_active_profile_name=Mock(return_value='Synthetic')
        task.check_weekly_boss=Mock()
        task._daily_step_completed=Mock(return_value=True)
        task.open_daily=Mock(return_value=(180,False))
        task._daily_objective=Mock(side_effect=lambda kind:(0,1) if kind=='echo' else (180,180))
        child=Mock();child.config={}
        task.get_task_by_class=Mock(return_value=child)
        return task,child,flags

    def run_daily_flow(self,task):
        with patch('src.task.DailyTask.require_account_runtime_for_task'), \
                patch('src.task.DailyTask.WWOneTimeTask.run'), \
                patch('src.evidence.service.begin_daily_run',return_value={}), \
                patch.object(DailyTask,'logged_in',False):
            task._run_daily_inner()

    def test_stale_checkpoint_is_overruled_and_local_capture_error_can_recover(self):
        task,child,_=self.daily_flow()
        def capture(**kwargs):
            if child.run_capture_mode.call_count==1:
                raise DailyActivityIncomplete('candidate did not acquire echo')
            task._daily_objective.side_effect=lambda kind:(1,1) if kind=='echo' else (180,180)
            task.open_daily.return_value=(180,True)
            self.assertTrue(kwargs['verify_capture']())
        child.run_capture_mode.side_effect=capture
        self.run_daily_flow(task)
        self.assertEqual(child.run_capture_mode.call_count,2)
        task.claim_daily.assert_called_once()
        self.assertIn('Daily Task',[c.args[0] for c in task.record_last_completed.call_args_list])

    def test_local_capture_failure_still_claims_partial_but_never_marks_daily_done(self):
        task,child,_=self.daily_flow()
        child.run_capture_mode.side_effect=DailyActivityIncomplete('still 0/1')
        with self.assertRaises(DailyActivityIncomplete):self.run_daily_flow(task)
        task.claim_daily.assert_called_once()
        self.assertNotIn('Daily Task',[c.args[0] for c in task.record_last_completed.call_args_list])

    def test_full_clear_failure_is_not_erased_by_echo_completion(self):
        task,child,flags=self.daily_flow()
        flags['Auto Farm all Nightmare Nest']=True
        task._daily_step_completed.return_value=False
        task.open_daily.return_value=(180,True)
        task._daily_objective.return_value=(1,1);task._daily_objective.side_effect=None
        task.run_task_by_class=Mock(side_effect=RuntimeError('full clear failed'))
        with self.assertRaisesRegex(RuntimeError,'梦魇巢穴未完整完成'):self.run_daily_flow(task)
        self.assertNotIn('Daily Task',[c.args[0] for c in task.record_last_completed.call_args_list])

    def test_real_reward_claim_continues_tail_and_stuck_overlay_never_completes(self):
        for stuck in (False, True):
            with self.subTest(stuck=stuck):
                task, _, flags = self.daily_flow()
                flags['Farm Nightmare Nest for Daily Echo'] = False
                flags['Record After Daily Task'] = True
                task.open_daily.return_value = (180, True)
                task.claim_daily = MethodType(DailyTask.claim_daily, task)
                events = []
                state = {'chest': True, 'overlay': False}
                for name in ('_open_daily_page', '_claim_daily_objectives', 'next_frame'):
                    setattr(task, name, Mock())
                task.require_game_frame = Mock(return_value=object())
                task._daily_page_ready = Mock(return_value=True)  # Dim background may match.
                task._daily_reward_overlay = Mock(side_effect=lambda f: 'ready' if state['overlay'] else None)
                def click(x, y, **kwargs):
                    if y == .887:
                        state.update(chest=False, overlay=True)
                        events.append('chest')
                    else:
                        state['overlay'] = stuck
                        events.append('dismiss')
                task.click_relative = Mock(side_effect=click)
                for name in ('claim_mail', 'claim_battle_pass', 'run_weekly_tasks', 'record_progress'):
                    setattr(task, name, Mock(side_effect=lambda n=name: events.append(n)))
                task.record_last_completed.side_effect = lambda name, **kw: events.append(name)
                def tiers(frame):
                    self.assertFalse(state['overlay'], 'Must never inspect red dots beneath an overlay')
                    return [20,40,60,80,100] if state['chest'] else []
                with patch('src.task.daily_observation.claimable_tiers', side_effect=tiers):
                    if stuck:
                        with self.assertRaises(DailyActivityIncomplete):
                            self.run_daily_flow(task)
                        task.claim_mail.assert_not_called()
                        task.claim_battle_pass.assert_not_called()
                        task.run_weekly_tasks.assert_not_called()
                        task.record_progress.assert_not_called()
                        self.assertNotIn('Daily Task', events)
                    else:
                        self.run_daily_flow(task)
                        self.assertEqual(events[-7:], ['chest', 'dismiss', 'claim_mail',
                                         'claim_battle_pass', 'run_weekly_tasks', 'record_progress', 'Daily Task'])


if __name__=='__main__':unittest.main()
