import ast
import unittest
from pathlib import Path

from ok import WaitFailedException
from src.task.DomainTask import DomainTask


class TestDomainRecoveryLoop(unittest.TestCase):
    def setUp(self):
        module = ast.parse(Path("src/task/DomainTask.py").read_text(encoding="utf-8"))
        class_node = next(
            node for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == "DomainTask"
        )
        self.method_node = next(
            node for node in class_node.body
            if isinstance(node, ast.FunctionDef) and node.name == "farm_domain_with_recovery_loop"
        )

    def test_method_has_retry_parameter_with_default(self):
        args = self.method_node.args.args
        self.assertEqual(args[-1].arg, "max_recovery_retries")
        self.assertEqual(len(self.method_node.args.defaults), 3)
        default_value = self.method_node.args.defaults[-1]
        self.assertIsInstance(default_value, ast.Constant)
        self.assertEqual(default_value.value, 3)

    def test_method_increments_retries(self):
        has_increment = any(
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "recovery_retries"
            and isinstance(node.op, ast.Add)
            and isinstance(node.value, ast.Constant)
            and node.value.value == 1
            for node in ast.walk(self.method_node)
        )
        self.assertTrue(has_increment)

    def test_method_stops_when_retry_budget_exceeded(self):
        has_retry_guard = any(
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Name)
            and node.left.id == "recovery_retries"
            and any(isinstance(op, ast.GtE) for op in node.ops)
            and any(
                isinstance(comp, ast.Name) and comp.id == "max_recovery_retries"
                for comp in node.comparators
            )
            for node in ast.walk(self.method_node)
        )
        self.assertTrue(has_retry_guard)

        has_make_sure_in_world_call = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
            and node.func.attr == "make_sure_in_world"
            for node in ast.walk(self.method_node)
        )
        self.assertTrue(has_make_sure_in_world_call)

    def test_loop_unpacks_must_use_from_farm_in_domain(self):
        has_unpack = any(
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Tuple)
            and len(node.targets[0].elts) == 2
            and {elt.id for elt in node.targets[0].elts if isinstance(elt, ast.Name)} == {"finished", "must_use"}
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "farm_in_domain"
            for node in ast.walk(self.method_node)
        )
        self.assertTrue(has_unpack)

    def test_unknown_and_live_targets_never_mean_rewards(self):
        from unittest.mock import Mock
        for target in (True, False):
            task = Mock(spec=DomainTask)
            task.has_target.return_value = target
            task.check_health_bar.return_value = False
            task.has_claim_stamina.return_value = False
            task.find_f_with_claim_text.return_value = False
            task.find_treasure_icon.return_value = False
            self.assertEqual(DomainTask._domain_reward_state(task), 'combat' if target else 'unknown')
        task.has_claim_stamina.return_value = True
        self.assertEqual(DomainTask._domain_reward_state(task), 'claim')

    def test_same_challenge_recovers_only_once(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from src.task.BaseCombatTask import CombatStateUnknown
        import threading
        for states, success in ((['combat', 'claim'], True), (['combat', 'combat'], False)):
            task = Mock(spec=DomainTask)
            task.executor = SimpleNamespace(check_enabled=Mock(), next_frame=Mock(), exit_event=threading.Event())
            task.combat_once.side_effect = CombatStateUnknown('switch')
            task._domain_reward_state.side_effect = states
            task.in_team.return_value = (True, 0, 3)
            task.frame = None
            if success:
                self.assertEqual(DomainTask._finish_domain_combat(task), 'claim')
            else:
                with self.assertRaises(CombatStateUnknown):
                    DomainTask._finish_domain_combat(task)
            self.assertEqual(task.combat_once.call_count, 2)
            task.walk_until_f.assert_not_called()
            task.use_stamina.assert_not_called()

    def test_claim_skips_treasure_and_unknown_does_not_spend(self):
        from unittest.mock import Mock
        from src.task.BaseCombatTask import CombatStateUnknown
        for state in ('claim', 'unknown'):
            task = Mock(spec=DomainTask)
            task.stamina_once = 40
            task.wait_until.return_value = True
            task.use_stamina.return_value = (False, 40)
            if state == 'unknown':
                task._finish_domain_combat.side_effect = CombatStateUnknown('unknown')
                with self.assertRaises(CombatStateUnknown):
                    DomainTask.farm_in_domain(task, must_use=40)
                task.use_stamina.assert_not_called()
                task.make_sure_in_world.assert_not_called()
            else:
                task._finish_domain_combat.return_value = 'claim'
                self.assertEqual(DomainTask.farm_in_domain(task, must_use=40), (True, 0))
            task.walk_to_treasure.assert_not_called()

    def test_frame_and_stop_errors_propagate_before_rewards(self):
        from unittest.mock import Mock
        from types import SimpleNamespace
        from ok import TaskDisabledException
        from src.runtime.game_runtime_errors import FrameUnavailable
        for error in (TaskDisabledException('stop'), FrameUnavailable('no frame')):
            task = Mock(spec=DomainTask)
            task.executor = SimpleNamespace(check_enabled=Mock(), next_frame=Mock(side_effect=error))
            with self.assertRaises(type(error)):
                DomainTask._finish_domain_combat(task)
            task._domain_reward_state.assert_not_called()


if __name__ == "__main__":
    unittest.main()
