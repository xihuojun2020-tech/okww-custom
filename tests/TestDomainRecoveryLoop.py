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

    def test_domain_combat_finished_when_team_and_enemy_signals_are_gone(self):
        class FakeTask:
            _domain_combat_finished = DomainTask._domain_combat_finished
            _in_combat = False

            @staticmethod
            def is_expected_combat_end():
                return False

            @staticmethod
            def has_target():
                return False

            @staticmethod
            def check_health_bar():
                return False

        self.assertTrue(FakeTask()._domain_combat_finished())

    def test_domain_combat_finished_rejects_live_target(self):
        class FakeTask:
            _domain_combat_finished = DomainTask._domain_combat_finished
            _in_combat = False

            @staticmethod
            def is_expected_combat_end():
                return False

            @staticmethod
            def has_target():
                return True

            @staticmethod
            def check_health_bar():
                return False

        self.assertFalse(FakeTask()._domain_combat_finished())

    def test_farm_in_domain_skips_treasure_timeout_after_combat_end(self):
        class FakeTask:
            farm_in_domain = DomainTask.farm_in_domain
            stamina_once = 40
            _in_combat = False
            picked = 0
            world = 0

            def walk_until_f(self, **_kwargs):
                return True

            def pick_f(self, **_kwargs):
                self.picked += 1

            def combat_once(self):
                pass

            def sleep(self, _seconds):
                pass

            def walk_to_treasure(self):
                raise WaitFailedException()

            def _domain_combat_finished(self):
                return True

            def use_stamina(self, **_kwargs):
                return False, 40

            def info_incr(self, *_args):
                pass

            def click(self, *_args, **_kwargs):
                pass

            def make_sure_in_world(self):
                self.world += 1

            def log_warning(self, *_args):
                pass

            def log_info(self, *_args):
                pass

        task = FakeTask()
        self.assertEqual((True, -40), task.farm_in_domain())
        self.assertEqual(2, task.picked)
        self.assertEqual(1, task.world)


if __name__ == "__main__":
    unittest.main()
