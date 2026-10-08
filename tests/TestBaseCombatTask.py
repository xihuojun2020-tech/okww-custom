import ast
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.task.BaseCombatTask import BaseCombatTask, NotInCombatException


class TestBaseCombatTask(unittest.TestCase):
    def test_unexpected_combat_exit_is_not_success(self):
        task = Mock(spec=BaseCombatTask)
        task.info = {}
        task.chars = []
        task.switch_healer_enabled.return_value = False
        task.in_combat.return_value = True
        task.is_expected_combat_end.return_value = False
        task.perform_combat_rotation.side_effect = NotInCombatException('not in_team while switching')
        with self.assertRaises(RuntimeError):
            BaseCombatTask.combat_once(task)
        task.combat_end.assert_not_called()

    def recovery_task(self):
        from types import SimpleNamespace
        task = object.__new__(BaseCombatTask)
        task.info = {}
        task.skip_combat_check = False
        task._combat_held_keys = {}
        task._combat_held_mouse = {}
        task.chars = []
        task._last_combat_error = None
        task._last_combat_error_log = 0
        task._suppressed_combat_errors = 0
        task._executor = SimpleNamespace(check_enabled=Mock(), _frame=None, frame=None)
        task.next_frame = Mock()
        task.in_combat = Mock(return_value=True)
        task.is_expected_combat_end = Mock(return_value=False)
        task.load_chars = Mock(return_value=True)
        task.info_set = Mock()
        task.sleep = Mock()
        task.get_current_char = Mock(return_value=Mock())
        return task

    def test_rotation_recovers_more_than_old_retry_limit_then_uses_character_script(self):
        task = self.recovery_task()
        char = task.get_current_char.return_value
        task.chars = identities = [char]
        char.perform.side_effect = [ValueError('skill failed')] * 8 + [None]
        task.perform_combat_rotation()
        self.assertEqual(9, char.perform.call_count)
        self.assertIs(task.chars, identities)
        self.assertEqual(8, task.load_chars.call_count)
        self.assertEqual([2, 4, 8, 16, 30, 30, 30, 30], [c.args[0] for c in task.sleep.call_args_list])
        task.load_chars.assert_called_with(reset_state=False)

    def test_combat_probe_recovers_and_wait_disables_stale_sleep_checks(self):
        task = self.recovery_task()
        task.in_combat.side_effect = [ValueError('frame failed'), True]
        task.sleep.side_effect = lambda delay: self.assertTrue(task.skip_combat_check)
        self.assertTrue(task.combat_is_active())
        self.assertFalse(task.skip_combat_check)
        task.get_current_char.assert_not_called()

    def test_rotation_stop_death_and_handoff_are_not_swallowed(self):
        from ok import TaskDisabledException
        from ok.task.exceptions import FinishedException
        from src.combat.CombatCheck import CombatFlowInterrupt
        from src.task.BaseCombatTask import CharDeadException
        for error in (TaskDisabledException(), FinishedException(), CombatFlowInterrupt(), CharDeadException()):
            task = self.recovery_task()
            task.get_current_char.return_value.perform.side_effect = error
            with self.assertRaises(type(error)):
                task.perform_combat_rotation()
            task.sleep.assert_not_called()

    def test_transient_character_combat_loss_revalidates_and_resumes(self):
        task = self.recovery_task()
        char = task.get_current_char.return_value
        char.perform.side_effect = [NotInCombatException('team briefly missing'), None]
        task.perform_combat_rotation()
        self.assertEqual(2, char.perform.call_count)
        task.load_chars.assert_called_once_with(reset_state=False)
        self.assertFalse(task._rotation_recovering)

    def test_death_rejection_requires_gray_portrait_and_explicit_no_revival_message(self):
        from types import SimpleNamespace
        task = self.recovery_task()
        char = SimpleNamespace(index=2, has_intro=True, has_sub_dps_intro=True)
        task._switch_portrait_gray = Mock(return_value=True)
        task.ocr = Mock(return_value=[SimpleNamespace(name='暂无可用的意识恢复物品')])
        task.log_warning = Mock()
        self.assertTrue(task._switch_rejected_by_death(char))
        self.assertTrue(char._switch_unrevivable)
        self.assertFalse(char.has_intro)
        self.assertFalse(char.has_sub_dps_intro)
        task._switch_portrait_gray.return_value = False
        self.assertFalse(task._unrevivable_switch_target(char))
        self.assertFalse(char._switch_unrevivable)
        for gray, message in ((True, '切换冷却中'), (False, '暂无可用的意识恢复物品'),
                              (None, '暂无可用的意识恢复物品')):
            task._switch_portrait_gray.return_value = gray
            task.ocr.return_value = [SimpleNamespace(name=message)]
            self.assertFalse(task._switch_rejected_by_death(char))
            self.assertFalse(char._switch_unrevivable)

    def test_revival_item_cooldown_temporarily_skips_rejected_switch(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        task = self.recovery_task()
        char = SimpleNamespace(index=1, has_intro=True, has_sub_dps_intro=True)
        task._switch_portrait_gray = Mock(return_value=False)
        task.ocr = Mock(return_value=[SimpleNamespace(name='意识恢复物品冷却中，请等待21秒后再使用')])
        task.log_warning = Mock()
        with patch('src.task.BaseCombatTask.time.monotonic', return_value=100):
            self.assertTrue(task._switch_rejected_by_death(char))
            self.assertTrue(task._unrevivable_switch_target(char))
        self.assertFalse(char.has_intro)
        self.assertFalse(char.has_sub_dps_intro)
        self.assertFalse(char.__dict__.get('_switch_unrevivable', False))
        with patch('src.task.BaseCombatTask.time.monotonic', return_value=122):
            self.assertFalse(task._unrevivable_switch_target(char))

    def test_dead_switch_yields_after_first_rejected_input_and_next_rotation_uses_survivor(self):
        from src.char.BaseChar import BaseChar, CharType
        task = self.recovery_task()
        current = BaseChar(task, 0, char_type=CharType.MAIN_DPS)
        dead = BaseChar(task, 1, char_type=CharType.SUB_DPS)
        live = BaseChar(task, 2, char_type=CharType.HEALER)
        task.chars = [current, dead, live]
        task.update_lib_portrait_icon = Mock()
        task.check_combat = Mock()
        task._wait_switch_team = Mock(return_value=(True, 0, 3))
        current.get_current_con = Mock(return_value=0)
        current.is_con_full = Mock(return_value=False)
        dead.wait_switch = Mock(return_value=False)
        task.send_key = task.click = task.log_debug = Mock()
        task._choose_switch_target = Mock(return_value=dead)
        task._switch_portrait_gray = Mock(return_value=True)
        task.ocr = Mock(return_value=[Mock(name='banner')])
        task.ocr.return_value[0].name = '暂无可用的意识恢复物品'
        task.log_warning = Mock()
        post = Mock()
        task.switch_next_char(current, post_action=post)
        self.assertTrue(dead._switch_unrevivable)
        self.assertEqual(1, len([c for c in task.send_key.call_args_list if c.args == (2,)]))
        post.assert_not_called()
        task.next_frame.assert_not_called()
        del task._choose_switch_target
        for char in (current, dead, live):
            char.healer_full_con_switch_locked = Mock(return_value=False)
            char.get_switch_priority = Mock(return_value=200)
        self.assertIs(live, task._choose_switch_target(current, False))
        live._switch_unrevivable = True
        self.assertIs(current, task._choose_switch_target(current, False))
        current.continues_normal_attack = Mock()
        task.switch_next_char(current)
        current.continues_normal_attack.assert_called_once_with(.2)

    def test_rotation_leaving_combat_cannot_retry_blindly(self):
        task = self.recovery_task()
        task.get_current_char.return_value.perform.side_effect = ValueError('skill failed')
        task.in_combat.return_value = False
        with self.assertRaises(NotInCombatException):
            task.perform_combat_rotation()
        self.assertEqual(1, task.get_current_char.return_value.perform.call_count)
        task.load_chars.assert_not_called()

    def test_release_after_backend_replacement_uses_original_keyboard_and_mouse(self):
        task = self.recovery_task()
        original = Mock()
        replacement = Mock()
        task.executor.interaction = replacement
        task.validate_key = lambda key: key
        task._combat_held_keys['w'] = original
        task._combat_held_mouse['left'] = original
        task.send_key_up('w')
        task.mouse_up(key='left')
        original.send_key_up.assert_called_once_with(key='w')
        original.mouse_up.assert_called_once_with(key='left')
        replacement.send_key_up.assert_not_called()
        replacement.mouse_up.assert_not_called()
        self.assertEqual({}, task._combat_held_keys)
        self.assertEqual({}, task._combat_held_mouse)

    def test_rotation_release_failure_blocks_actions_until_original_backend_recovers(self):
        task = self.recovery_task()
        backend = Mock()
        backend.send_key_up.side_effect = [OSError('window gone'), OSError('window gone'), None]
        task._combat_held_keys['w'] = backend
        task.perform_combat_rotation()
        self.assertEqual(3, backend.send_key_up.call_count)
        self.assertEqual({}, task._combat_held_keys)
        task.get_current_char.return_value.perform.assert_called_once()

    def test_switch_team_wait_uses_new_frames_without_input(self):
        from types import SimpleNamespace
        task = Mock(spec=BaseCombatTask)
        task._switch_missing_saved = False
        task.frame = None
        task.executor = SimpleNamespace(check_enabled=Mock(), next_frame=Mock())
        task.in_team.side_effect = [(False, -1, 1), (True, 2, 3), (True, 2, 3)]
        self.assertEqual(BaseCombatTask._wait_switch_team(task), (True, 2, 3))
        self.assertEqual(task.executor.next_frame.call_count, 2)
        task.send_key.assert_not_called()
        task.click.assert_not_called()
        task.screenshot.assert_called_once()

    def test_expected_end_and_death_keep_their_contracts(self):
        from src.task.BaseCombatTask import CharDeadException
        for error in (NotInCombatException('expected'), CharDeadException('dead')):
            task = Mock(spec=BaseCombatTask)
            task.info = {}
            task.chars = []
            task.switch_healer_enabled.return_value = False
            task.in_combat.return_value = True
            task.is_expected_combat_end.return_value = True
            task.wait_combat.return_value = 'entered'
            task.perform_combat_rotation.side_effect = error
            if isinstance(error, CharDeadException):
                with self.assertRaises(CharDeadException):
                    BaseCombatTask.combat_once(task)
                task.combat_end.assert_not_called()
            else:
                self.assertEqual(BaseCombatTask.combat_once(task), 'entered')
                task.combat_end.assert_called_once()

    def test_probe_errors_and_stop_are_not_combat_end(self):
        from src.combat.CombatCheck import CombatCheck
        from ok import TaskDisabledException
        from types import SimpleNamespace
        for error in (TaskDisabledException('stop'), ValueError('probe failed')):
            task = SimpleNamespace(do_check_in_combat=Mock(side_effect=error))
            with self.assertRaises(type(error)):
                CombatCheck.in_combat(task)
            self.assertFalse(task.in_sleep_check)

    def test_switch_team_timeout_preserves_exception(self):
        from types import SimpleNamespace
        task = Mock(spec=BaseCombatTask)
        task._switch_missing_saved = False
        task.frame = None
        task.executor = SimpleNamespace(check_enabled=Mock(), next_frame=Mock())
        task.in_team.return_value = (False, -1, 1)
        task.raise_not_in_combat.side_effect = NotInCombatException('missing')
        with patch('src.task.BaseCombatTask.time.monotonic', side_effect=[0, 2]):
            with self.assertRaises(NotInCombatException):
                BaseCombatTask._wait_switch_team(task)
        task.send_key.assert_not_called()

    def test_unconfirmed_liberation_records_context_without_extra_input(self):
        from src.char.BaseChar import BaseChar
        from types import SimpleNamespace
        char = object.__new__(BaseChar)
        char.task = SimpleNamespace(executor=SimpleNamespace(_last_frame_time=99),
                                    hwnd=SimpleNamespace(exists=True, visible=False))
        char.logger = Mock()
        with patch('src.char.BaseChar.time.time', return_value=100):
            char._log_liberation_unconfirmed(98, 3)
        message = char.logger.warning.call_args.args[0]
        for text in ('send_attempts=3', 'frame_age=1', 'visible=False', 'input_delivery=unverified'):
            self.assertIn(text, message)

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
