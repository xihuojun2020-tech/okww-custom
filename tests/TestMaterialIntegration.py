import unittest
from datetime import datetime
from unittest.mock import Mock
from uuid import uuid4

from ok import TaskDisabledException
from src.materials.model import Counts, GAME_ZONE
from src.task.DomainTask import DomainTask
from src.task.MaterialPlannerTask import MaterialPlannerTask
from tests import TestStaminaAccounting as accounting
from src.task.BaseWWTask import BaseWWTask


class TestMaterialIntegration(unittest.TestCase):
    def domain(self):
        task = Mock(spec=DomainTask)
        task.stamina_once = 40
        task._finish_domain_combat.return_value = 'claim'
        task.wait_until.return_value = True
        task.use_stamina.return_value = (False,40)
        task.material_planner = Mock()
        task.material_planner.max_claims = 1
        return task

    def test_last_claim_is_saved_before_exit(self):
        task = self.domain()
        order=Mock()
        order.attach_mock(task.use_stamina,'spend')
        order.attach_mock(task.material_planner.begin_claim,'intent')
        order.attach_mock(task.material_planner.collect_claim,'collect')
        order.attach_mock(task.click,'click')
        self.assertEqual(DomainTask.farm_in_domain(task,must_use=40),(True,0))
        names=[call[0] for call in order.mock_calls]
        self.assertEqual(names,['intent','spend','collect','click'])
        task.material_planner.collect_claim.assert_called_once_with(40)
        self.assertEqual(task.use_stamina.call_args.kwargs['max_claims'],1)

    def test_failed_capture_never_retries_or_exits(self):
        task=self.domain()
        task.material_planner.collect_claim.side_effect=RuntimeError('partial')
        with self.assertRaisesRegex(RuntimeError,'partial'):
            DomainTask.farm_in_domain(task,40)
        task.click.assert_not_called()
        task.material_planner.capture_failure.assert_called_once()

    def test_stop_does_not_take_more_frames(self):
        task=self.domain()
        task.use_stamina.side_effect=TaskDisabledException('stop')
        with self.assertRaises(TaskDisabledException): DomainTask.farm_in_domain(task,40)
        task.material_planner.capture_failure.assert_not_called()
        task.click.assert_not_called()

    def test_near_target_forces_single_claim(self):
        task=accounting.TestStaminaAccounting._stamina_task(240,0)
        self.assertEqual(BaseWWTask.use_stamina(task,once=40,max_claims=1),(True,40))
        self.assertEqual(task.clicked,'single')

    def test_echo_handoff_cannot_round_remaining_budget_up(self):
        from src.task.TacetTask import TacetTask
        task=Mock(spec=TacetTask)
        task.config={}; task.stamina_once=60
        task.get_stamina.return_value=(240,0,240)
        task.use_stamina.return_value=(False,60)
        TacetTask.farm_tacet(task,daily=True,stamina_budget=80)
        self.assertEqual(task.use_stamina.call_args.kwargs['must_use'],60)
        self.assertEqual(task.use_stamina.call_count,1)

    def test_budget_exhaustion_still_refreshes_target_without_echo_spending(self):
        task=Mock(spec=MaterialPlannerTask)
        task.game_lang='zh_CN'; task.width=1920; task.height=1080
        task.repository=Mock()
        task.repository.pending_claims.return_value=[]
        task.repository.latest_complete_snapshot.return_value={'captured_at':datetime.now(GAME_ZONE).isoformat()}
        task.daily_stamina_budget.return_value=80
        task.scan_target.side_effect=[{'pistol_a':dict(stock=Counts(),need=Counts(gold=8))},
                                      {'pistol_a':dict(stock=Counts(gold=8),need=Counts(gold=8))}]
        domain=Mock()
        domain.farm_domain_with_recovery_loop.side_effect=lambda *a,**kw:setattr(task,'total_used',80)
        task.get_task_by_class.return_value=domain
        MaterialPlannerTask.run_for_profile(task,str(uuid4()),{},Mock())
        self.assertEqual(task.scan_target.call_count,2)
        task.scan_inventory.assert_not_called()
        domain.farm_tacet.assert_not_called()
        self.assertIsNone(domain.material_planner)
