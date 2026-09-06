import ast
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.task.BaseCombatTask import BaseCombatTask


class TestBaseCombatTask(unittest.TestCase):
    def test_combat_wait_rejects_nonpositive_before_any_input(self):
        task = Mock(spec=BaseCombatTask)
        for value in (0, -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                BaseCombatTask.combat_once(task, wait_combat_time=value)
        self.assertEqual(task.mock_calls, [])

    def test_positive_combat_wait_preserves_result_and_completion(self):
        task = Mock(spec=BaseCombatTask)
        task.info = {}
        task.switch_healer_enabled.return_value = False
        task.in_combat.return_value = False
        task.wait_combat.return_value = 'entered'
        self.assertEqual(BaseCombatTask.combat_once(task, wait_combat_time=2), 'entered')
        task.wait_combat.assert_called_once_with(target=False, time_out=2, raise_if_not_found=True)
        task.combat_end.assert_called_once()
        self.assertEqual(task.info['Combat Count'], 1)

    def setUp(self):
        module = ast.parse(Path("src/task/BaseCombatTask.py").read_text(encoding="utf-8"))
        class_node = next(
            node for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == "BaseCombatTask"
        )
        self.method_node = next(
            (node for node in class_node.body
             if isinstance(node, ast.FunctionDef) and node.name == "get_revive_search_boss_name"),
            None,
        )
        self.revive_method_node = next(
            node for node in class_node.body
            if isinstance(node, ast.FunctionDef) and node.name == "revive_at_tower_and_heal"
        )

    def _build_method_owner(self):
        self.assertIsNotNone(self.method_node, "BaseCombatTask should define get_revive_search_boss_name")
        compiled = ast.fix_missing_locations(ast.Module(body=[
            ast.ClassDef(
                name="MethodOwner",
                bases=[],
                keywords=[],
                decorator_list=[],
                body=[self.method_node],
            )
        ], type_ignores=[]))
        namespace = {}
        exec(compile(compiled, "<test>", "exec"), namespace)
        return namespace["MethodOwner"]

    def test_revive_search_boss_name_matches_game_language(self):
        method_owner = self._build_method_owner()
        cases = {
            "zh_CN": "无冠者",
            "zh_TW": "無冠者",
            "en_US": "Crownless",
            "unknown_lang": "无冠者",
        }

        for lang, expected in cases.items():
            with self.subTest(lang=lang):
                task = method_owner()
                task.game_lang = lang
                self.assertEqual(task.get_revive_search_boss_name(), expected)

    def test_revive_flow_uses_language_aware_search_name(self):
        has_call = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
            and node.func.attr == "input_text"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Attribute)
            and isinstance(node.args[0].func.value, ast.Name)
            and node.args[0].func.value.id == "self"
            and node.args[0].func.attr == "get_revive_search_boss_name"
            for node in ast.walk(self.revive_method_node)
        )
        self.assertTrue(has_call)

    @patch("src.task.BaseCombatTask.time.monotonic", side_effect=[0, 1, 2, 31])
    def test_concerto_anomaly_logs_are_rate_limited_and_aggregated(self, _clock):
        task = object.__new__(BaseCombatTask)
        task.logger = Mock()

        for _ in range(4):
            task._log_con_anomaly("not_full", "协奏值异常")

        self.assertEqual(task.logger.warning.call_count, 2)
        self.assertIn("已合并 2 次", task.logger.warning.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
