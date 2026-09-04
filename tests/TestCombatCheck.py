import time
import unittest
from unittest.mock import patch
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.char.BaseChar import BaseChar
from src.Labels import Labels
from src.char.CharFactory import get_char_by_pos
from src.task.AutoCombatTask import AutoCombatTask
from src.task.BaseCombatTask import BaseCombatTask, CharDeadException, NotInCombatException
from src.combat.CombatCheck import CombatCheck
from tests.fixture_support import require_fixture

config['debug'] = True


def return_true():
    return True


class TestCombatCheck(TaskTestCase):
    task_class = AutoCombatTask
    config = config

    def test_in_combat_check(self):
        self.task.ensure_levitator = return_true
        self.task.do_reset_to_false()
        self.set_image('tests/images/in_combat.png')
        in_combat = self.task.in_combat()
        # self.task.screenshot('in_combat.png', show_box=True)
        # time.sleep(1)
        self.assertTrue(in_combat)

    def test_4k_combat_check(self):
        require_fixture(self, 'ok_templates/57d8d801-BitBlt_True_3840x2160_1759986393607.1733_original.png')
        self.task.ensure_levitator = return_true
        self.task.do_reset_to_false()
        self.set_image("ok_templates/57d8d801-BitBlt_True_3840x2160_1759986393607.1733_original.png")
        in_combat = self.task.in_combat()
        # self.task.screenshot('in_combat4k.png', show_box=True)
        # time.sleep(1)
        self.assertTrue(in_combat)

    def test_not_in_combat_check(self):
        self.task.ensure_levitator = return_true
        self.task.do_reset_to_false()
        self.set_image('tests/images/in_combat3.png')
        in_combat = self.task.in_combat()
        self.assertFalse(in_combat)

    def test_in_combat_cloud(self):
        self.task.ensure_levitator = return_true
        self.task.do_reset_to_false()
        self.task.is_browser = return_true
        self.set_image('tests/images/cloud_game_combat.png')
        in_combat = self.task.in_combat()
        self.assertTrue(in_combat)

    def test_in_combat_cloud2(self):
        require_fixture(self, 'ok_templates/browser_in_combat.png')
        self.task.ensure_levitator = return_true
        self.task.do_reset_to_false()
        self.task.is_browser = return_true
        self.set_image('ok_templates/browser_in_combat.png')
        in_combat = self.task.in_combat()
        self.assertTrue(in_combat)

    def test_target_box_short(self):
        require_fixture(self, 'ok_templates/25.png')
        self.set_image('ok_templates/25.png')
        self.task.chars = [BaseChar(self.task, 0)]
        self.task.chars[0].is_current_char = True
        self.assertFalse(self.task.has_target())

        self.task.chars[0].target_box_short_combat_check = True
        self.assertTrue(self.task.has_target())
        self.assertTrue(BaseChar(self.task, 0).has_short_action())

    def test_lucilla_enables_target_box_short_combat_check_from_char_factory(self):
        class Box:
            def __init__(self, name):
                self.name = name

        class Match:
            def __init__(self, name):
                self.name = name
                self.confidence = 0.95

        class Task:
            char_config = {}

            def find_one(self, name, box=None, threshold=0.6):
                return Match(name) if name == Labels.char_lucilla else None

            def find_best_match_in_box(self, box, names, threshold=0.6):
                return Match(Labels.char_lucilla)

            def log_info(self, *args, **kwargs):
                pass

        lucilla = get_char_by_pos(Task(), Box('box_char_1'), 0, None)

        self.assertTrue(lucilla.target_box_short_combat_check)

    def test_enter_combat_loads_chars_before_target_check(self):
        task = AutoCombatTask.__new__(AutoCombatTask)
        task._in_combat = False
        task.in_liberation = False
        task.chars = [None, None, None]
        task.config = {'Auto Target': True}
        task.target_enemy_error_notified = False
        task.find_one = lambda *args, **kwargs: False
        task.log_info = lambda *args, **kwargs: None
        order = []

        class Char:
            is_current_char = True

        def load_chars():
            order.append('load_chars')
            task.chars = [Char()]
            return True

        def has_target():
            order.append(('has_target', task.get_current_char() is not None))
            return True

        task.load_chars = load_chars
        task.has_target = has_target

        self.assertTrue(task.do_check_in_combat(False))
        self.assertEqual(order, ['load_chars', ('has_target', True)])


class TestCombatTargetLossGuard(unittest.TestCase):

    @staticmethod
    def make_task():
        task = CombatCheck.__new__(CombatCheck)
        task._in_combat = True
        task._in_liberation = False
        task.target_loss_started_at = None
        task.target_loss_grace_period = 6
        task.combat_end_condition = None
        task.check_f_break = lambda: None
        task.get_current_char = lambda: None
        task.on_combat_check = lambda: True
        task.has_target = lambda: False
        task.check_health_bar = lambda: False
        task.target_enemy = lambda wait=True: False
        task.should_check_monthly_card = lambda: False
        task.handle_monthly_card = lambda: False
        task.resets = []
        task.reset_to_false = lambda reason='': task.resets.append(reason) or False

        class Scene:
            def in_combat(self):
                return None

            def set_in_combat(self):
                return True

        task.scene = Scene()
        return task

    def test_first_failed_retarget_stays_in_combat_during_grace_period(self):
        task = self.make_task()

        with patch('src.combat.CombatCheck.time.time', return_value=100):
            self.assertTrue(task.do_check_in_combat(False))

        self.assertEqual(100, task.target_loss_started_at)
        self.assertEqual([], task.resets)

    def test_retarget_time_counts_towards_target_loss_grace_period(self):
        task = self.make_task()
        now = [100]
        attempts = []

        def target_enemy(wait=True):
            attempts.append(wait)
            now[0] += 3
            return False

        task.target_enemy = target_enemy
        with patch('src.combat.CombatCheck.time.time', side_effect=lambda: now[0]):
            self.assertTrue(task.do_check_in_combat(False))
            self.assertFalse(task.do_check_in_combat(False))

        self.assertEqual([True, True], attempts)
        self.assertEqual([CombatCheck.TARGET_GONE_END_REASON], task.resets)

    def test_successful_retarget_clears_pending_target_loss(self):
        task = self.make_task()
        task.target_loss_started_at = 100
        task.target_enemy = lambda wait=True: True

        with patch('src.combat.CombatCheck.time.time', return_value=102):
            self.assertTrue(task.do_check_in_combat(False))

        self.assertIsNone(task.target_loss_started_at)
        self.assertEqual([], task.resets)

    def test_scene_false_does_not_end_combat_while_enemy_health_bar_exists(self):
        task = self.make_task()
        task.scene._in_combat = False
        task.scene.in_combat = lambda: False
        task.check_health_bar = lambda: True

        self.assertTrue(task.do_check_in_combat(False))
        self.assertIsNone(task.target_loss_started_at)
        self.assertEqual([], task.resets)

    def test_repeated_failed_retarget_after_grace_period_exits_combat(self):
        task = self.make_task()
        task.target_loss_started_at = 100

        with patch('src.combat.CombatCheck.time.time', return_value=107):
            self.assertFalse(task.do_check_in_combat(False))

        self.assertEqual([CombatCheck.TARGET_GONE_END_REASON], task.resets)

    def test_explicit_combat_end_condition_is_immediate(self):
        task = self.make_task()
        task.combat_end_condition = lambda: True

        with patch('src.combat.CombatCheck.time.time', return_value=100):
            self.assertFalse(task.do_check_in_combat(False))

        self.assertEqual([CombatCheck.EXPLICIT_END_REASON], task.resets)


class TestExpectedCombatEnd(unittest.TestCase):

    @staticmethod
    def make_task(reason):
        task = BaseCombatTask.__new__(BaseCombatTask)
        task.out_of_combat_reason = reason
        task._in_combat = False
        task.skip_combat_check = False
        task.find_one = lambda *args, **kwargs: None
        task.wait_feature = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError('normal combat end must not wait for a revive dialog')
        )
        return task

    def test_expected_combat_end_skips_blocking_revive_wait(self):
        task = self.make_task(CombatCheck.TARGET_GONE_END_REASON)

        with self.assertRaises(NotInCombatException):
            task.raise_not_in_combat('combat check not in combat', expected=True)

    def test_expected_combat_end_still_detects_visible_revive_dialog(self):
        task = AutoCombatTask.__new__(AutoCombatTask)
        task.out_of_combat_reason = CombatCheck.TARGET_GONE_END_REASON
        task._in_combat = False
        task.find_one = lambda *args, **kwargs: object()
        task.wait_feature = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError('the current frame already contains the revive dialog')
        )
        task.log_info = lambda *args, **kwargs: None
        task.reset_to_false = lambda reason='': False
        task.info_set = lambda *args, **kwargs: None

        with self.assertRaises(CharDeadException):
            task.raise_not_in_combat('combat check not in combat', expected=True)

    def test_check_combat_marks_target_loss_as_expected(self):
        task = self.make_task(CombatCheck.TARGET_GONE_END_REASON)
        task._in_combat = True

        def in_combat():
            task._in_combat = False
            return False

        calls = []
        task.in_combat = in_combat
        task.raise_not_in_combat = lambda message, expected=False: calls.append((message, expected))

        task.check_combat()

        self.assertEqual([('combat check not in combat', True)], calls)

    def test_check_combat_keeps_unexpected_failure_on_diagnostic_path(self):
        task = self.make_task('switch failed')
        task._in_combat = True

        def in_combat():
            task._in_combat = False
            return False

        calls = []
        task.in_combat = in_combat
        task.raise_not_in_combat = lambda message, expected=False: calls.append((message, expected))

        task.check_combat()

        self.assertEqual([('combat check not in combat', False)], calls)


if __name__ == '__main__':
    unittest.main()
